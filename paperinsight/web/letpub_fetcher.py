from __future__ import annotations

import html
import re
from typing import Optional
from urllib.parse import urlencode, urljoin

import requests

from paperinsight.utils.journal_metadata import canonicalize_journal_title, normalize_issn
from paperinsight.web.http_client import create_retryable_session
from paperinsight.web.impact_factor_fetcher import ImpactFactorLookupResult


class LetPubImpactFactorFetcher:
    BASE_URL = "https://www.letpub.com.cn/"
    SEARCH_PATH = "index.php"

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
        self.session.headers.setdefault(
            "Accept",
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        )
        self.session.headers.setdefault("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")

    def lookup(
        self,
        *,
        journal_title: Optional[str],
        issn: Optional[str] = None,
        eissn: Optional[str] = None,
    ) -> ImpactFactorLookupResult:
        journal_title = (journal_title or "").strip()
        normalized_issn = normalize_issn(issn)
        normalized_eissn = normalize_issn(eissn)

        if not journal_title and not normalized_issn and not normalized_eissn:
            return ImpactFactorLookupResult(
                status="NO_QUERY",
                source_name="LETPUB",
                source_url=self.BASE_URL,
            )

        params = {
            "currentsearchpage": 1,
            "page": "journalapp",
            "view": "search",
        }
        if journal_title:
            params["searchname"] = journal_title
        if normalized_issn:
            params["searchissn"] = normalized_issn

        search_url = urljoin(self.BASE_URL, f"{self.SEARCH_PATH}?{urlencode(params)}")

        try:
            response = self.session.get(search_url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            return ImpactFactorLookupResult(
                status="ERROR",
                source_name="LETPUB",
                source_url=search_url,
                error_message=str(exc),
            )

        response.encoding = response.encoding or response.apparent_encoding or "utf-8"
        result = self._parse_search_results(
            response.text,
            search_url=search_url,
            journal_title=journal_title,
            issn=normalized_issn,
            eissn=normalized_eissn,
        )
        if result is not None:
            return result

        return ImpactFactorLookupResult(
            status="NOT_FOUND",
            source_name="LETPUB",
            source_url=search_url,
            error_message="No matching journal row was found on LetPub",
        )

    def _parse_search_results(
        self,
        payload: str,
        *,
        search_url: str,
        journal_title: str,
        issn: Optional[str],
        eissn: Optional[str],
    ) -> Optional[ImpactFactorLookupResult]:
        wanted_title = canonicalize_journal_title(journal_title)

        best_match: Optional[tuple[int, float, str]] = None
        for row_html in re.findall(r"<tr\b.*?</tr>", payload, flags=re.IGNORECASE | re.DOTALL):
            if "page=journalapp&view=detail" not in row_html:
                continue

            row_text = self._normalize_text(re.sub(r"<[^>]+>", " ", html.unescape(row_html)))
            if_value = self._extract_if_value(row_text)
            if if_value is None:
                continue

            title_match = re.search(
                r'<a[^>]+href="([^"]*page=journalapp&view=detail[^"]*)"[^>]*>(.*?)</a>',
                row_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            title_href = title_match.group(1) if title_match else None
            title_text = self._normalize_text(re.sub(r"<[^>]+>", " ", html.unescape(title_match.group(2)))) if title_match else ""
            if not title_text:
                continue

            canonical_title = canonicalize_journal_title(title_text)
            row_issn_matches = bool(issn and issn in row_text)
            row_eissn_matches = bool(eissn and eissn in row_text)
            score = 0

            if wanted_title and canonical_title == wanted_title:
                score += 10
            elif wanted_title and canonical_title and wanted_title in canonical_title:
                score += 7
            elif wanted_title and canonical_title and canonical_title in wanted_title:
                score += 5

            if row_issn_matches:
                score += 6
            if row_eissn_matches:
                score += 6
            if re.search(r"\bIF\s*:\s*[0-9]+(?:\.[0-9]+)?\b", row_text, re.IGNORECASE):
                score += 3

            if score <= 0:
                continue

            detail_url = search_url
            if title_href:
                detail_url = urljoin(self.BASE_URL, title_href)

            if best_match is None or score > best_match[0]:
                best_match = (score, if_value, detail_url)

        if best_match is None:
            return None

        _, impact_factor, detail_url = best_match
        return ImpactFactorLookupResult(
            status="OK",
            source_name="LETPUB",
            source_url=detail_url,
            impact_factor=impact_factor,
            year=None,
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    @staticmethod
    def _extract_if_value(text: str) -> Optional[float]:
        match = re.search(r"\bIF\s*:\s*([0-9]+(?:\.[0-9]+)?)\b", text, re.IGNORECASE)
        if not match:
            return None
        try:
            value = float(match.group(1))
        except ValueError:
            return None
        if not 0.1 <= value <= 200:
            return None
        return value
