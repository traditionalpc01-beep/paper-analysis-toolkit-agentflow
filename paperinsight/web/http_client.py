"""统一的 HTTP 客户端，提供指数退避重试和超时控制。

所有 web fetcher 应优先通过 ``create_retryable_session`` 创建 session，
而不是直接 ``requests.Session()``。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_TOTAL_RETRIES: int = 3
DEFAULT_BACKOFF_FACTOR: float = 0.5
DEFAULT_STATUS_FORCELIST: tuple[int, ...] = (429, 500, 502, 503, 504)
DEFAULT_TIMEOUT: int = 30


def create_retryable_session(
    total_retries: int = DEFAULT_TOTAL_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    status_forcelist: Optional[Sequence[int]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    default_headers: Optional[dict[str, str]] = None,
    pool_connections: int = 10,
    pool_maxsize: int = 10,
) -> requests.Session:
    """创建带自动重试的 requests.Session。

    Args:
        total_retries: 最大重试次数（0 表示不重试）。
        backoff_factor: 退避因子，实际等待时间为 ``backoff_factor * (2 ** (retry-1))`` 秒。
        status_forcelist: 遇到哪些 HTTP 状态码时自动重试。
        timeout: 默认请求超时秒数。
        default_headers: 设置到 session 上的默认请求头。
        pool_connections: 连接池大小。
        pool_maxsize: 单 host 最大连接数。

    Returns:
        配置好的 requests.Session 实例。
    """
    session = requests.Session()

    if total_retries > 0:
        retry = Retry(
            total=total_retries,
            backoff_factor=backoff_factor,
            status_forcelist=list(status_forcelist or DEFAULT_STATUS_FORCELIST),
            allowed_methods=["GET", "HEAD", "OPTIONS", "POST"],
            raise_on_status=False,  # 不抛异常，让调用方处理响应
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)

    # 默认 headers — 使用 update 强制覆盖 Session 自带的默认值
    if default_headers:
        session.headers.update(default_headers)

    session.request = _wrap_request_with_timeout(session.request, timeout)  # type: ignore[assignment]

    return session


def _wrap_request_with_timeout(
    original_request: Any,
    default_timeout: int,
) -> Any:
    """包装 session.request，在未显式传入 timeout 时使用默认超时。"""

    def wrapped_request(method: str, url: str, **kwargs: Any) -> requests.Response:
        if "timeout" not in kwargs:
            kwargs["timeout"] = default_timeout
        return original_request(method, url, **kwargs)

    return wrapped_request
