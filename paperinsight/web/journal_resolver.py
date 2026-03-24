from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import requests

from paperinsight.utils.journal_metadata import (
    build_journal_match_keys,
    canonicalize_journal_title,
    normalize_exact_journal_title,
    normalize_issn,
)
from paperinsight.web.journal_if_database import JOURNAL_ALIASES


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MJLJournalCandidate:
    publication_seq_no: str
    publication_title: str
    publication_title_iso: Optional[str]
    issn: Optional[str]
    eissn: Optional[str]
    publisher_name: Optional[str]
    search_identifier: Optional[str]
    search_url: str
    profile_url: str
    source_name: str = "mjl"

    @property
    def display_title(self) -> str:
        return self.publication_title_iso or self.publication_title


@dataclass(frozen=True)
class MJLJournalResolution:
    status: str
    match_method: Optional[str]
    search_value: Optional[str]
    candidate: Optional[MJLJournalCandidate] = None
    candidates: tuple[MJLJournalCandidate, ...] = field(default_factory=tuple)
    error_message: Optional[str] = None

    @property
    def matched_journal_title(self) -> Optional[str]:
        return self.candidate.display_title if self.candidate else None

    @property
    def matched_issn(self) -> Optional[str]:
        if not self.candidate:
            return None
        return self.candidate.issn or self.candidate.eissn


class MJLJournalResolver:
    SEARCH_API_URL = "https://mjl.clarivate.com/api/mjl/jprof/public/rank-search"
    SEARCH_RESULTS_URL = "https://mjl.clarivate.com/search-results"
    JOURNAL_PROFILE_URL = "https://mjl.clarivate.com/journal-profile"
    DEFAULT_PRODUCT_CODES = ("D", "J", "SS", "H", "EX")

    def __init__(
        self,
        timeout: int = 30,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )
        self.session.headers.setdefault("Accept", "application/json, text/plain, */*")
        self.session.headers.setdefault("Content-Type", "application/json")
        self.session.headers.setdefault("Referer", self.SEARCH_RESULTS_URL)
        self.session.headers.setdefault("Authorization", "Bearer")
        self.session.headers.setdefault("x-1p-appid", "mjl")
        self.session.headers.setdefault("Access-Control-Allow-Origin", "*")

    def resolve(
        self,
        journal_title: Optional[str] = None,
        issn: Optional[str] = None,
        eissn: Optional[str] = None,
    ) -> MJLJournalResolution:
        resolved_title = self._resolve_alias(journal_title) if journal_title else None
        match_keys = build_journal_match_keys(resolved_title or journal_title, issn=issn, eissn=eissn)
        search_cache: dict[str, list[MJLJournalCandidate]] = {}

        for match_method, match_value in match_keys.prioritized_items():
            search_value = self._build_search_value(match_method, match_keys)
            if not search_value:
                continue

            try:
                if search_value not in search_cache:
                    search_cache[search_value] = self.search_journals(search_value)
                candidates = search_cache[search_value]
            except Exception as exc:
                logger.warning(f"MJL search failed for {search_value}: {exc}")
                continue

            filtered = self._filter_candidates(candidates, match_method, match_value)
            if len(filtered) == 1:
                return MJLJournalResolution(
                    status="OK",
                    match_method=match_method,
                    search_value=search_value,
                    candidate=filtered[0],
                    candidates=tuple(filtered),
                )
            if len(filtered) > 1:
                return MJLJournalResolution(
                    status="MULTI_MATCH",
                    match_method=match_method,
                    search_value=search_value,
                    candidates=tuple(filtered),
                )

        return MJLJournalResolution(
            status="NO_MATCH",
            match_method=None,
            search_value=match_keys.issn or match_keys.eissn or match_keys.exact_title,
        )

    def _resolve_alias(self, journal_title: str) -> str:
        """解析期刊名称别名"""
        if not journal_title:
            return journal_title

        normalized = canonicalize_journal_title(journal_title)
        if not normalized:
            return journal_title

        if normalized in JOURNAL_ALIASES:
            resolved = JOURNAL_ALIASES[normalized]
            logger.info(f"Resolved alias '{journal_title}' -> '{resolved}'")
            return resolved

        for alias_key, canonical in JOURNAL_ALIASES.items():
            if alias_key in normalized or normalized in alias_key:
                logger.info(f"Resolved fuzzy alias '{journal_title}' -> '{canonical}'")
                return canonical

        return journal_title

    def search_journals(self, search_value: str) -> list[MJLJournalCandidate]:
        payload = self._build_search_payload(search_value)
        response = self.session.post(
            self.SEARCH_API_URL,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return self._parse_candidates(data, search_value=search_value)

    def _build_search_payload(self, search_value: str) -> dict:
        return {
            "searchValue": search_value,
            "pageNum": 1,
            "pageSize": 10,
            "sortOrder": [{"name": "RELEVANCE", "order": "DESC"}],
            "filters": [
                {
                    "filterName": "COVERED_LATEST_JEDI",
                    "matchType": "BOOLEAN_EXACT",
                    "caseSensitive": False,
                    "values": [{"type": "VALUE", "value": "true"}],
                },
                {
                    "filterName": "PRODUCT_CODE",
                    "matchType": "TEXT_EXACT",
                    "caseSensitive": False,
                    "values": [{"type": "VALUE", "value": code} for code in self.DEFAULT_PRODUCT_CODES],
                },
            ],
            "searchIdentifier": str(uuid.uuid4()),
        }

    def _parse_candidates(
        self,
        response_data: dict,
        *,
        search_value: str,
    ) -> list[MJLJournalCandidate]:
        candidates: list[MJLJournalCandidate] = []
        search_url = self._build_search_results_url(search_value)
        search_identifier = self._clean_optional_text(response_data.get("searchIdentifier"))

        for item in response_data.get("journalProfiles", []):
            journal_profile = item.get("journalProfile", {})
            candidates.append(
                MJLJournalCandidate(
                    publication_seq_no=str(journal_profile.get("publicationSeqNo") or "").strip(),
                    publication_title=str(journal_profile.get("publicationTitle") or "").strip(),
                    publication_title_iso=self._clean_optional_text(journal_profile.get("publicationTitleISO")),
                    issn=normalize_issn(journal_profile.get("issn")),
                    eissn=normalize_issn(journal_profile.get("eissn")),
                    publisher_name=self._clean_optional_text(journal_profile.get("publisherName")),
                    search_identifier=search_identifier,
                    search_url=search_url,
                    profile_url=self.JOURNAL_PROFILE_URL,
                )
            )

        return [candidate for candidate in candidates if candidate.publication_title]

    def _filter_candidates(
        self,
        candidates: list[MJLJournalCandidate],
        match_method: str,
        match_value: str,
    ) -> list[MJLJournalCandidate]:
        filtered: list[MJLJournalCandidate] = []
        for candidate in candidates:
            if match_method == "issn" and normalize_issn(candidate.issn) == match_value:
                filtered.append(candidate)
                continue
            if match_method == "eissn" and normalize_issn(candidate.eissn) == match_value:
                filtered.append(candidate)
                continue

            candidate_titles = {
                normalize_exact_journal_title(candidate.publication_title),
                normalize_exact_journal_title(candidate.publication_title_iso),
            }
            candidate_canonical_titles = {
                canonicalize_journal_title(candidate.publication_title),
                canonicalize_journal_title(candidate.publication_title_iso),
            }

            if match_method == "exact_title" and match_value in candidate_titles:
                filtered.append(candidate)
                continue
            if match_method == "canonical_title" and match_value in candidate_canonical_titles:
                filtered.append(candidate)

        return filtered

    def _build_search_value(self, match_method: str, match_keys) -> Optional[str]:
        if match_method in {"issn", "eissn"}:
            return match_keys.issn if match_method == "issn" else match_keys.eissn
        return match_keys.exact_title

    def _build_search_results_url(self, search_value: str) -> str:
        normalized_issn = normalize_issn(search_value)
        if normalized_issn:
            return f"{self.SEARCH_RESULTS_URL}?issn={quote(normalized_issn)}"
        return f"{self.SEARCH_RESULTS_URL}?search={quote(search_value)}"

    @staticmethod
    def _clean_optional_text(value: object) -> Optional[str]:
        if value in (None, ""):
            return None
        text = str(value).strip()
        return text or None
