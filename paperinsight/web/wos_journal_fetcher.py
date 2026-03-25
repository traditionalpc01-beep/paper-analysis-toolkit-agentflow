from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests

from paperinsight.utils.journal_metadata import canonicalize_journal_title, normalize_issn
from paperinsight.web.http_client import create_retryable_session
from paperinsight.web.impact_factor_fetcher import ImpactFactorLookupResult


@dataclass(frozen=True)
class WOSJournalCandidate:
    journal_id: Optional[str]
    title: Optional[str]
    iso_title: Optional[str]
    issn: Optional[str]
    eissn: Optional[str]
    jif: Optional[float]
    jif_year: Optional[int]
    source_url: str

    @property
    def display_title(self) -> Optional[str]:
        return self.iso_title or self.title


class WOSJournalFetcher:
    BASE_URL = "https://api.clarivate.com/apis/wos-journals/v1"

    def __init__(
        self,
        api_key: str,
        timeout: int = 30,
        session: Optional[requests.Session] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.session = session or create_retryable_session(timeout=timeout)
        self.session.headers.setdefault("User-Agent", "PaperInsight/3.0")
        self.session.headers.setdefault("Accept", "application/json")
        self.session.headers["X-ApiKey"] = self.api_key

    def lookup(
        self,
        *,
        journal_title: Optional[str] = None,
        issn: Optional[str] = None,
        eissn: Optional[str] = None,
    ) -> ImpactFactorLookupResult:
        search_value = normalize_issn(issn) or normalize_issn(eissn) or journal_title
        if not search_value:
            return ImpactFactorLookupResult(
                status="NO_QUERY",
                source_name="WOS_JOURNALS_API",
                source_url=f"{self.base_url}/journals",
            )

        url = f"{self.base_url}/journals"
        response = self.session.get(
            url,
            params={"q": search_value, "limit": 10, "page": 1},
            timeout=self.timeout,
        )

        if response.status_code == 401:
            return ImpactFactorLookupResult(
                status="NO_ACCESS",
                source_name="WOS_JOURNALS_API",
                source_url=response.url or url,
                error_message="Web of Science API key is invalid or missing.",
            )
        if response.status_code == 404:
            return ImpactFactorLookupResult(
                status="NO_MATCH",
                source_name="WOS_JOURNALS_API",
                source_url=response.url or url,
            )
        if response.status_code >= 400:
            return ImpactFactorLookupResult(
                status="ERROR",
                source_name="WOS_JOURNALS_API",
                source_url=response.url or url,
                error_message=f"HTTP {response.status_code}",
            )

        payload = response.json()
        candidates = self._extract_candidates(payload, response.url or url)
        candidate = self._select_candidate(
            candidates,
            journal_title=journal_title,
            issn=issn,
            eissn=eissn,
        )

        if not candidate:
            return ImpactFactorLookupResult(
                status="NO_MATCH",
                source_name="WOS_JOURNALS_API",
                source_url=response.url or url,
            )

        if candidate.jif is None:
            return ImpactFactorLookupResult(
                status="NOT_VISIBLE",
                source_name="WOS_JOURNALS_API",
                source_url=candidate.source_url,
            )

        return ImpactFactorLookupResult(
            status="OK",
            source_name="WOS_JOURNALS_API",
            source_url=candidate.source_url,
            impact_factor=candidate.jif,
            year=candidate.jif_year,
        )

    def _extract_candidates(self, payload: Any, source_url: str) -> list[WOSJournalCandidate]:
        records = self._find_record_list(payload)
        candidates: list[WOSJournalCandidate] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            title = self._pick_text(record, "title", "journalTitle", "name", "sourceTitle")
            iso_title = self._pick_text(record, "isoTitle", "titleIso", "abbreviation", "sourceTitleISO")
            issn = normalize_issn(
                self._pick_text(record, "issn", "printIssn", "issnPrint", "sourceIssn")
            )
            eissn = normalize_issn(
                self._pick_text(record, "eissn", "electronicIssn", "onlineIssn", "sourceEissn")
            )
            jif = self._extract_jif(record)
            jif_year = self._extract_year(record)
            journal_id = self._pick_text(record, "id", "journalId", "uid")
            candidates.append(
                WOSJournalCandidate(
                    journal_id=journal_id,
                    title=title,
                    iso_title=iso_title,
                    issn=issn,
                    eissn=eissn,
                    jif=jif,
                    jif_year=jif_year,
                    source_url=source_url,
                )
            )
        return candidates

    def _select_candidate(
        self,
        candidates: list[WOSJournalCandidate],
        *,
        journal_title: Optional[str],
        issn: Optional[str],
        eissn: Optional[str],
    ) -> Optional[WOSJournalCandidate]:
        normalized_issn = normalize_issn(issn)
        normalized_eissn = normalize_issn(eissn)
        wanted_title = canonicalize_journal_title(journal_title)

        for candidate in candidates:
            if normalized_issn and candidate.issn == normalized_issn:
                return candidate
            if normalized_eissn and candidate.eissn == normalized_eissn:
                return candidate

        if wanted_title:
            title_matches = [
                candidate
                for candidate in candidates
                if canonicalize_journal_title(candidate.display_title) == wanted_title
                or canonicalize_journal_title(candidate.title) == wanted_title
            ]
            if title_matches:
                return title_matches[0]

        return candidates[0] if candidates else None

    def _find_record_list(self, payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []

        for key in ("hits", "records", "data", "journals", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = self._find_record_list(value)
                if nested:
                    return nested

        return []

    def _pick_text(self, payload: Any, *keys: str) -> Optional[str]:
        values = self._collect_values_by_keys(payload, set(keys))
        for value in values:
            if value in (None, ""):
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _extract_jif(self, payload: Any) -> Optional[float]:
        direct_keys = {
            "jif",
            "journalimpactfactor",
            "impactfactor",
            "jifvalue",
            "value",
        }
        for value in self._collect_values_by_keys(payload, direct_keys):
            numeric = self._coerce_float(value)
            if numeric is not None and 0.1 <= numeric <= 200:
                return numeric

        for key, value in self._walk_key_values(payload):
            if "jif" not in key.lower() and "impact" not in key.lower():
                continue
            numeric = self._coerce_float(value)
            if numeric is not None and 0.1 <= numeric <= 200:
                return numeric
        return None

    def _extract_year(self, payload: Any) -> Optional[int]:
        for key in ("jcrYear", "year", "reportYear"):
            value = self._pick_text(payload, key)
            if not value:
                continue
            try:
                year = int(value)
            except ValueError:
                continue
            if 2000 <= year <= 2100:
                return year
        return None

    def _collect_values_by_keys(self, payload: Any, keys: set[str]) -> list[Any]:
        results: list[Any] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in keys:
                    results.append(value)
                results.extend(self._collect_values_by_keys(value, keys))
        elif isinstance(payload, list):
            for item in payload:
                results.extend(self._collect_values_by_keys(item, keys))
        return results

    def _walk_key_values(self, payload: Any) -> list[tuple[str, Any]]:
        items: list[tuple[str, Any]] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                items.append((key, value))
                items.extend(self._walk_key_values(value))
        elif isinstance(payload, list):
            for item in payload:
                items.extend(self._walk_key_values(item))
        return items

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if isinstance(value, (int, float)):
            return float(value)
        if value in (None, ""):
            return None
        text = str(value).strip()
        if not text:
            return None
        digits = []
        for char in text:
            if char.isdigit() or char == ".":
                digits.append(char)
            elif digits:
                break
        if not digits:
            return None
        try:
            return float("".join(digits))
        except ValueError:
            return None
