from __future__ import annotations

from collections import deque

from paperinsight.web.impact_factor_fetcher import MJLImpactFactorFetcher
from paperinsight.web.journal_resolver import MJLJournalCandidate


class DummyResponse:
    def __init__(self, payload, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class DummySession:
    def __init__(self, responses: list[DummyResponse]):
        self.responses = deque(responses)
        self.calls: list[str] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: int):
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("No more prepared responses")
        return self.responses.popleft()


def _candidate() -> MJLJournalCandidate:
    return MJLJournalCandidate(
        publication_seq_no="70884J",
        publication_title="NATURE",
        publication_title_iso="Nature",
        issn="0028-0836",
        eissn="1476-4687",
        publisher_name="Nature Portfolio",
        search_identifier="search-id-1",
        search_url="https://mjl.clarivate.com/search-results?issn=1476-4687",
        profile_url="https://mjl.clarivate.com/journal-profile",
    )


def test_fetcher_returns_no_access_for_unauthorized_profile_call():
    session = DummySession([DummyResponse({"message": "Unauthorized"}, status_code=401)])
    fetcher = MJLImpactFactorFetcher(session=session)

    result = fetcher.lookup(_candidate())

    assert result.status == "NO_ACCESS"
    assert result.impact_factor is None
    assert "searchIdentifier=search-id-1" in session.calls[0]


def test_fetcher_parses_explicit_jif_value_from_profile_payload():
    session = DummySession(
        [
            DummyResponse(
                {
                    "journalProfile": {
                        "metrics": {
                            "jcr": {
                                "citationReportYear": 2024,
                                "jif": 50.5,
                            }
                        }
                    }
                }
            )
        ]
    )
    fetcher = MJLImpactFactorFetcher(session=session)

    result = fetcher.lookup(_candidate())

    assert result.status == "OK"
    assert result.year == 2024
    assert result.impact_factor == 50.5


def test_fetcher_parses_jif_key_with_embedded_year():
    session = DummySession(
        [
            DummyResponse(
                {
                    "journalProfile": {
                        "indicators": {
                            "jif2024": "49.9",
                            "jif2023": "47.1",
                        }
                    }
                }
            )
        ]
    )
    fetcher = MJLImpactFactorFetcher(session=session)

    result = fetcher.lookup(_candidate())

    assert result.status == "OK"
    assert result.year == 2024
    assert result.impact_factor == 49.9


def test_fetcher_prefers_latest_jif_year_over_older_higher_value():
    session = DummySession(
        [
            DummyResponse(
                {
                    "journalProfile": {
                        "indicators": {
                            "jif2024": "11.2",
                            "jif2023": "15.8",
                        }
                    }
                }
            )
        ]
    )
    fetcher = MJLImpactFactorFetcher(session=session)

    result = fetcher.lookup(_candidate())

    assert result.status == "OK"
    assert result.year == 2024
    assert result.impact_factor == 11.2


def test_fetcher_marks_not_visible_when_profile_has_no_jif_data():
    session = DummySession([DummyResponse({"journalProfile": {"title": "Nature"}})])
    fetcher = MJLImpactFactorFetcher(session=session)

    result = fetcher.lookup(_candidate())

    assert result.status == "NOT_VISIBLE"
    assert result.impact_factor is None
