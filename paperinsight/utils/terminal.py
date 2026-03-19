from __future__ import annotations

import sys
from typing import TextIO

from rich.console import Console


UNICODE_FALLBACKS = (
    ("?", "[OK]"),
    ("?", "[X]"),
    ("!", "[!]"),
    ("?", "->"),
    ("?", "-"),
)

UNICODE_PROBE = "".join(source for source, _ in UNICODE_FALLBACKS)


def _stream_encoding(stream: TextIO) -> str:
    return getattr(stream, "encoding", None) or "utf-8"


def supports_unicode_output(stream: TextIO | None = None) -> bool:
    target = stream or sys.stdout
    try:
        UNICODE_PROBE.encode(_stream_encoding(target))
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def normalize_output_text(text: str, stream: TextIO | None = None) -> str:
    if supports_unicode_output(stream):
        return text
    normalized = text
    for source, target in UNICODE_FALLBACKS:
        normalized = normalized.replace(source, target)
    return normalized


class SafeOutputStream:
    def __init__(self, wrapped: TextIO | None = None, *, stderr: bool = False):
        self._wrapped = wrapped
        self._stderr = stderr

    @property
    def wrapped(self) -> TextIO:
        if self._wrapped is not None:
            return self._wrapped
        return sys.stderr if self._stderr else sys.stdout

    @property
    def encoding(self):
        return getattr(self.wrapped, "encoding", None)

    def write(self, text: str) -> int:
        return self.wrapped.write(normalize_output_text(text, self.wrapped))

    def flush(self) -> None:
        self.wrapped.flush()

    def isatty(self) -> bool:
        isatty = getattr(self.wrapped, "isatty", None)
        return bool(isatty and isatty())

    def fileno(self) -> int:
        fileno = getattr(self.wrapped, "fileno", None)
        if fileno is None:
            raise OSError("Underlying stream does not expose fileno()")
        return fileno()

    def __getattr__(self, name: str):
        return getattr(self.wrapped, name)


def create_console(stderr: bool = False) -> Console:
    target = sys.stderr if stderr else sys.stdout
    unicode_enabled = supports_unicode_output(target)
    return Console(
        file=SafeOutputStream(stderr=stderr),
        safe_box=not unicode_enabled,
        legacy_windows=False,
    )
