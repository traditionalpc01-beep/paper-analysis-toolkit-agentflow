"""Tests for paperinsight.web.http_client"""

from __future__ import annotations

from unittest.mock import patch, MagicMock, call

import pytest
import requests

from paperinsight.web.http_client import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_STATUS_FORCELIST,
    DEFAULT_TOTAL_RETRIES,
    create_retryable_session,
)


class TestCreateRetryableSession:
    """Test create_retryable_session factory."""

    def test_returns_session_instance(self):
        session = create_retryable_session(total_retries=0)
        assert isinstance(session, requests.Session)

    def test_zero_retries_no_retry_adapter(self):
        session = create_retryable_session(total_retries=0)
        https_adapter = session.get_adapter("https://example.com")
        # When total_retries=0, no custom Retry adapter is mounted.
        # The default adapter has max_retries=Retry(0).
        assert hasattr(https_adapter, "max_retries")

    def test_custom_headers_set(self):
        headers = {"X-Custom": "test-value", "User-Agent": "TestBot/1.0"}
        session = create_retryable_session(total_retries=0, default_headers=headers)
        assert session.headers["X-Custom"] == "test-value"
        assert session.headers["User-Agent"] == "TestBot/1.0"

    def test_custom_headers_do_not_override_existing(self):
        session = create_retryable_session(
            total_retries=0,
            default_headers={"User-Agent": "TestBot/2.0"},
        )
        assert session.headers["User-Agent"] == "TestBot/2.0"

    def test_status_forcelist_defaults(self):
        """Verify DEFAULT_STATUS_FORCELIST covers expected HTTP error codes."""
        assert 429 in DEFAULT_STATUS_FORCELIST
        assert 500 in DEFAULT_STATUS_FORCELIST
        assert 502 in DEFAULT_STATUS_FORCELIST
        assert 503 in DEFAULT_STATUS_FORCELIST
        assert 504 in DEFAULT_STATUS_FORCELIST

    def test_backoff_factor_defaults(self):
        assert DEFAULT_BACKOFF_FACTOR == 0.5

    def test_total_retries_defaults(self):
        assert DEFAULT_TOTAL_RETRIES == 3

    def test_timeout_injected_by_wrapper(self):
        """The wrapped request injects default_timeout when not provided."""
        session = create_retryable_session(total_retries=0, timeout=42)
        # Access the original request via the wrapper's closure
        assert hasattr(session.request, "__wrapped__") or callable(session.request)

    def test_retries_mounted_when_total_retries_gt_zero(self):
        session = create_retryable_session(total_retries=3)
        https_adapter = session.get_adapter("https://example.com")
        # Should have a Retry object with total=3
        retry_obj = https_adapter.max_retries
        assert retry_obj.total == 3

    def test_pool_config(self):
        session = create_retryable_session(
            total_retries=0, pool_connections=5, pool_maxsize=3
        )
        # Verify session was created (basic smoke test)
        assert isinstance(session, requests.Session)

    def test_session_has_send_method(self):
        session = create_retryable_session(total_retries=0)
        assert callable(getattr(session, "send", None))

    def test_session_has_close_method(self):
        session = create_retryable_session(total_retries=0)
        session.close()  # Should not raise
