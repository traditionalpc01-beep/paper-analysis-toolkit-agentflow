from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from paperinsight.utils.journal_metadata import canonicalize_journal_title
from paperinsight.web.http_client import create_retryable_session
from paperinsight.web.journal_resolver import MJLJournalCandidate


@dataclass(frozen=True)
class ImpactFactorLookupResult:
    status: str
    source_name: str
    source_url: str
    impact_factor: Optional[float] = None
    year: Optional[int] = None
    error_message: Optional[str] = None


class MJLImpactFactorFetcher:
    PROFILE_API_URL = "https://mjl.clarivate.com/api/mjl/jprof/restricted/seqno/{seqno}"
    JCR_DEEP_LINK_URL = "https://mjl.clarivate.com/api/censub/restricted/jcr-deep-link/{seqno}"

    # CURATED_FALLBACK 年份超过此阈值（年）则标记为 STALE
    STALE_YEAR_THRESHOLD = 2

    @staticmethod
    def _current_jcr_year() -> int:
        """当前 JCR 年份：当年 6 月前取上一年，6 月后取当年。"""
        now = datetime.now()
        return now.year - 1 if now.month < 6 else now.year

    def __init__(
        self,
        timeout: int = 30,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.session = session or create_retryable_session(timeout=timeout)
        self.session.headers.setdefault(
            "User-Agent",
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )
        self.session.headers.setdefault("Accept", "application/json, text/plain, */*")
        self.session.headers.setdefault("Referer", "https://mjl.clarivate.com/search-results")
        self.session.headers.setdefault("Authorization", "Bearer")
        self.session.headers.setdefault("x-1p-appid", "mjl")
        self.fallback_impact_factors: dict[str, tuple[float, int, str]] = {}
        self._register_fallback(
            ["Advanced Materials", "Adv. Mater.", "Adv Mater"],
            30.849,
            2023,
            "https://corporatesolutions.wiley.com/assets/media-kits/advanced-materials.pdf",
        )
        self._register_fallback(
            [
                "Advanced Functional Materials",
                "Adv. Funct. Mater.",
                "Adv Funct Mater",
            ],
            19.0,
            2025,
            "https://qa.store.wiley.com/en-ca/journals/Advanced%2BFunctional%2BMaterials-p-b16163028",
        )
        self._register_fallback(
            [
                "Journal of the American Chemical Society",
                "J. Am. Chem. Soc.",
                "J Am Chem Soc",
            ],
            15.7,
            2025,
            "https://pubs.acs.org/page/jacsat/about.html",
        )
        self._register_fallback(
            ["Nano Letters", "Nano Lett."],
            9.1,
            2025,
            "https://pubs.acs.org/page/nalefd/about.html",
        )
        self._register_fallback(
            ["Small"],
            13.3,
            2022,
            "https://www.wiley.com/content/dam/wiley-dotcom/en/b2b/research/corporate-solutions/pdf/infographics/science/semiconductor-en.pdf",
        )
        self._register_fallback(
            ["Chemical Engineering Journal", "Chem. Eng. J.", "Chem Eng J"],
            21.7,
            2024,
            "https://api.journals.elsevier.com/media/dxmf0zaq/cej-eceb-flyer.pdf",
        )
        self._register_fallback(
            [
                "Journal of Photochemistry and Photobiology C Photochemistry Reviews",
                "J. Photochem. Photobiol. C-Photochem. Rev.",
                "J Photochem Photobiol C Photochem Rev",
            ],
            13.6,
            2024,
            "https://www.sciencedirect.com/journal/journal-of-photochemistry-and-photobiology-c-photochemistry-reviews",
        )
        self._register_fallback(
            ["Laser and Photonics Reviews", "Laser Photonics Reviews", "Laser Photonics Rev."],
            11.0,
            2024,
            "https://onlinelibrary.wiley.com/page/journal/18638899/homepage/productinformation.html",
        )

    def lookup(self, candidate: MJLJournalCandidate) -> ImpactFactorLookupResult:
        profile_url = self._build_profile_api_url(candidate)
        response = self.session.get(profile_url, timeout=self.timeout)

        if response.status_code in {401, 403}:
            return self._fallback_lookup(
                candidate,
                status="NO_ACCESS",
                default_url=profile_url,
                error_message="Profile endpoint requires an authenticated MJL session.",
            )
        if response.status_code == 404:
            return self._fallback_lookup(candidate, status="NO_MATCH", default_url=profile_url)
        if response.status_code >= 400:
            return self._fallback_lookup(
                candidate,
                status="ERROR",
                default_url=profile_url,
                error_message=f"HTTP {response.status_code}",
            )

        data = response.json()
        parsed = self._extract_impact_factor(data)
        if parsed is not None:
            year, impact_factor = parsed
            return ImpactFactorLookupResult(
                status="OK",
                source_name="MJL_PROFILE_API",
                source_url=profile_url,
                impact_factor=impact_factor,
                year=year,
            )

        return self._fallback_lookup(candidate, status="NOT_VISIBLE", default_url=profile_url)

    def lookup_by_title(self, journal_title: Optional[str]) -> ImpactFactorLookupResult:
        canonical_title = canonicalize_journal_title(journal_title)
        if not canonical_title:
            return ImpactFactorLookupResult(
                status="NO_QUERY",
                source_name="CURATED_FALLBACK",
                source_url="",
            )

        fallback = self.fallback_impact_factors.get(canonical_title)
        if not fallback:
            return ImpactFactorLookupResult(
                status="NO_MATCH",
                source_name="CURATED_FALLBACK",
                source_url="",
            )

        impact_factor, year, source_url = fallback
        status = "OK"
        if year is not None and self._current_jcr_year() - year > self.STALE_YEAR_THRESHOLD:
            status = "OK_STALE"
        return ImpactFactorLookupResult(
            status=status,
            source_name="CURATED_FALLBACK",
            source_url=source_url,
            impact_factor=impact_factor,
            year=year,
        )

    def _register_fallback(
        self,
        titles: list[str],
        impact_factor: float,
        year: int,
        source_url: str,
    ) -> None:
        for title in titles:
            canonical = canonicalize_journal_title(title)
            if canonical:
                self.fallback_impact_factors[canonical] = (impact_factor, year, source_url)

    def _fallback_lookup(
        self,
        candidate: MJLJournalCandidate,
        *,
        status: str,
        default_url: str,
        error_message: Optional[str] = None,
    ) -> ImpactFactorLookupResult:
        fallback = None
        for title in (
            candidate.display_title,
            candidate.publication_title,
        ):
            canonical_title = canonicalize_journal_title(title)
            if not canonical_title:
                continue
            fallback = self.fallback_impact_factors.get(canonical_title)
            if fallback:
                break
        if not fallback:
            return ImpactFactorLookupResult(
                status=status,
                source_name="MJL_PROFILE_API",
                source_url=default_url,
                error_message=error_message,
            )

        impact_factor, year, source_url = fallback
        status = "OK"
        if year is not None and self._current_jcr_year() - year > self.STALE_YEAR_THRESHOLD:
            status = "OK_STALE"
        return ImpactFactorLookupResult(
            status=status,
            source_name="CURATED_FALLBACK",
            source_url=source_url,
            impact_factor=impact_factor,
            year=year,
            error_message=error_message,
        )

    def _build_profile_api_url(self, candidate: MJLJournalCandidate) -> str:
        base_url = self.PROFILE_API_URL.format(seqno=candidate.publication_seq_no)
        if not candidate.search_identifier:
            return base_url
        return f"{base_url}?{urlencode({'searchIdentifier': candidate.search_identifier})}"

    def _extract_impact_factor(self, payload: Any) -> Optional[tuple[Optional[int], float]]:
        matches = self._walk_for_impact_factor(payload)
        if not matches:
            return None
        matches.sort(key=lambda item: (item[0] or 0, item[1]), reverse=True)
        return matches[0]

    def _walk_for_impact_factor(self, payload: Any) -> list[tuple[Optional[int], float]]:
        matches: list[tuple[Optional[int], float]] = []
        if isinstance(payload, dict):
            matches.extend(self._extract_impact_factor_from_dict(payload))
            for value in payload.values():
                matches.extend(self._walk_for_impact_factor(value))
        elif isinstance(payload, list):
            for item in payload:
                matches.extend(self._walk_for_impact_factor(item))
        return matches

    def _extract_impact_factor_from_dict(self, item: dict[str, Any]) -> list[tuple[Optional[int], float]]:
        matches: list[tuple[Optional[int], float]] = []
        year = self._coerce_year(
            item.get("citationReportYear")
            or item.get("reportYear")
            or item.get("year")
            or item.get("jifYear")
        )

        for key, value in item.items():
            key_lower = key.lower()
            numeric_value = self._coerce_float(value)
            if numeric_value is None:
                continue
            if not 0.1 <= numeric_value <= 200:
                continue

            if key_lower in {"journalimpactfactor", "impactfactor", "jif", "jifvalue"}:
                matches.append((year, numeric_value))
                continue

            if key_lower.startswith("jif"):
                key_year = self._extract_year_from_key(key_lower)
                matches.append((key_year or year, numeric_value))
                continue

            if "impactfactor" in key_lower:
                key_year = self._extract_year_from_key(key_lower)
                matches.append((key_year or year, numeric_value))

        return matches

    @staticmethod
    def _extract_year_from_key(key: str) -> Optional[int]:
        match = re.search(r"(20\d{2})", key)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _coerce_year(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            year = int(str(value))
        except (TypeError, ValueError):
            return None
        return year if 2000 <= year <= 2100 else None

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if isinstance(value, (int, float)):
            return float(value)
        if value in (None, ""):
            return None
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(value))
        if not match:
            return None
        return float(match.group(1))
