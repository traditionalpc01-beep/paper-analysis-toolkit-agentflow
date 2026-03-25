from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape
from typing import Optional
from urllib.parse import urlparse

import requests

from paperinsight.utils.journal_metadata import canonicalize_journal_title, normalize_issn
from paperinsight.web.http_client import create_retryable_session
from paperinsight.web.impact_factor_fetcher import ImpactFactorLookupResult


@dataclass(frozen=True)
class SearchCrawlerItem:
    title: str
    link: str
    description: str


class SearchCrawlerFetcher:
    SEARCH_URL = "https://www.bing.com/search"

    def __init__(
        self,
        timeout: int = 30,
        session: Optional[requests.Session] = None,
        market: str = "en-US",
    ) -> None:
        self.timeout = timeout
        self.market = market
        self.session = session or create_retryable_session(timeout=timeout)
        self.session.headers.setdefault(
            "User-Agent",
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )
        self.session.headers.setdefault("Accept", "application/xml,text/xml,text/html,*/*")
        self.trusted_domains = (
            "clarivate.com",
            "wiley.com",
            "onlinelibrary.wiley.com",
            "elsevier.com",
            "sciencedirect.com",
            "acs.org",
            "springer.com",
            "nature.com",
            "tandfonline.com",
        )

    def lookup(
        self,
        *,
        journal_title: Optional[str],
        issn: Optional[str] = None,
        eissn: Optional[str] = None,
    ) -> ImpactFactorLookupResult:
        journal_title = (journal_title or "").strip()
        if not journal_title and not issn and not eissn:
            return ImpactFactorLookupResult(
                status="NO_QUERY",
                source_name="SEARCH_CRAWLER",
                source_url=self.SEARCH_URL,
            )

        queries = self._build_queries(journal_title=journal_title, issn=issn, eissn=eissn)
        for query in queries:
            items = self._search(query)
            best_result = self._find_best_result(items, journal_title=journal_title, issn=issn, eissn=eissn)
            if best_result:
                return best_result

        return ImpactFactorLookupResult(
            status="NO_MATCH",
            source_name="SEARCH_CRAWLER",
            source_url=self.SEARCH_URL,
        )

    def _build_queries(
        self,
        *,
        journal_title: str,
        issn: Optional[str],
        eissn: Optional[str],
    ) -> list[str]:
        queries: list[str] = []
        normalized_issn = normalize_issn(issn)
        normalized_eissn = normalize_issn(eissn)
        if journal_title:
            queries.extend(
                [
                    f'"{journal_title}" "impact factor"',
                    f'"{journal_title}" "journal impact factor"',
                    f'"{journal_title}" "Journal Citation Reports"',
                ]
            )
        if normalized_issn:
            queries.append(f'"{normalized_issn}" "{journal_title}" "impact factor"')
        if normalized_eissn and normalized_eissn != normalized_issn:
            queries.append(f'"{normalized_eissn}" "{journal_title}" "impact factor"')
        return list(dict.fromkeys(query for query in queries if query.strip()))

    def _search(self, query: str) -> list[SearchCrawlerItem]:
        response = self.session.get(
            self.SEARCH_URL,
            params={
                "q": query,
                "format": "rss",
                "setlang": self.market,
                "cc": self.market.split("-")[-1],
                "mkt": self.market,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._parse_rss(response.text)

    def _parse_rss(self, payload: str) -> list[SearchCrawlerItem]:
        root = ET.fromstring(payload)
        items: list[SearchCrawlerItem] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            if title and link:
                items.append(
                    SearchCrawlerItem(
                        title=unescape(title),
                        link=link,
                        description=unescape(description),
                    )
                )
        return items

    def _find_best_result(
        self,
        items: list[SearchCrawlerItem],
        *,
        journal_title: str,
        issn: Optional[str],
        eissn: Optional[str],
    ) -> Optional[ImpactFactorLookupResult]:
        wanted_title = canonicalize_journal_title(journal_title)
        normalized_issn = normalize_issn(issn)
        normalized_eissn = normalize_issn(eissn)

        scored_items: list[tuple[int, SearchCrawlerItem]] = []
        for item in items:
            score = self._score_item(
                item,
                wanted_title=wanted_title,
                normalized_issn=normalized_issn,
                normalized_eissn=normalized_eissn,
            )
            if score > 0:
                scored_items.append((score, item))

        for _, item in sorted(scored_items, key=lambda x: x[0], reverse=True):
            if not self._is_trusted_domain(item.link):
                continue
            direct = self._extract_from_text(f"{item.title}\n{item.description}")
            if direct:
                year, impact_factor = direct
                return ImpactFactorLookupResult(
                    status="OK",
                    source_name="SEARCH_CRAWLER",
                    source_url=item.link,
                    impact_factor=impact_factor,
                    year=year,
                )

            page_result = self._fetch_page_and_extract(item.link, wanted_title=wanted_title)
            if page_result:
                year, impact_factor = page_result
                return ImpactFactorLookupResult(
                    status="OK",
                    source_name="SEARCH_CRAWLER",
                    source_url=item.link,
                    impact_factor=impact_factor,
                    year=year,
                )

        return None

    def _score_item(
        self,
        item: SearchCrawlerItem,
        *,
        wanted_title: Optional[str],
        normalized_issn: Optional[str],
        normalized_eissn: Optional[str],
    ) -> int:
        text = f"{item.title}\n{item.description}"
        score = 0
        hostname = (urlparse(item.link).hostname or "").lower()

        if self._is_trusted_domain(item.link):
            score += 5

        canonical_text = canonicalize_journal_title(text)
        if wanted_title and canonical_text and wanted_title in canonical_text:
            score += 5

        if normalized_issn and normalized_issn in text:
            score += 3
        if normalized_eissn and normalized_eissn in text:
            score += 3

        if re.search(r"impact\s+factor|journal\s+impact\s+factor", text, re.IGNORECASE):
            score += 4

        if self._extract_from_text(text):
            score += 4

        return score

    def _is_trusted_domain(self, url: str) -> bool:
        hostname = (urlparse(url).hostname or "").lower()
        return any(hostname.endswith(domain) for domain in self.trusted_domains)

    def _fetch_page_and_extract(
        self,
        url: str,
        *,
        wanted_title: Optional[str],
    ) -> Optional[tuple[Optional[int], float]]:
        try:
            response = self.session.get(url, timeout=self.timeout)
        except Exception:
            return None

        if not self._is_trusted_domain(url):
            return None
        if response.status_code != 200:
            return None

        text = re.sub(r"<[^>]+>", " ", response.text)
        text = unescape(re.sub(r"\s+", " ", text))
        canonical_text = canonicalize_journal_title(text)
        if wanted_title and canonical_text and wanted_title not in canonical_text:
            return None

        return self._extract_from_text(text)

    def _extract_from_text(self, text: str) -> Optional[tuple[Optional[int], float]]:
        patterns = [
            r"(20\d{2})[^0-9]{0,20}(?:journal\s+impact\s+factor|impact\s+factor)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
            r"(?:journal\s+impact\s+factor|impact\s+factor)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)[^0-9]{0,20}(20\d{2})",
            r"(?:journal\s+impact\s+factor|impact\s+factor)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue

            if len(match.groups()) == 2:
                first, second = match.groups()
                if first and len(first) == 4 and first.isdigit():
                    year = int(first)
                    value = float(second)
                elif second and len(second) == 4 and second.isdigit():
                    year = int(second)
                    value = float(first)
                else:
                    year = None
                    value = float(first)
            else:
                year = None
                value = float(match.group(1))

            if 0.1 <= value <= 200:
                return year, value
        return None
