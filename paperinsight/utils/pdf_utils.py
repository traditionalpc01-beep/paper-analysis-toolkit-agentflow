from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple, Union

import fitz


class PDFProcessor:
    def __init__(self, pdf_path: Union[str, Path]):
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")
        self._doc = None

    def _open(self):
        if self._doc is None:
            self._doc = fitz.open(self.pdf_path)
        return self._doc

    def close(self):
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def extract_text(
        self,
        max_pages: Optional[int] = None,
        min_text_ratio: float = 0.001,
    ) -> Tuple[str, str, dict]:
        doc = self._open()
        metadata = self._extract_metadata(doc)
        texts = []
        front_text = ""
        total_area = 0.0

        total_pages = len(doc)
        pages_to_read = total_pages if max_pages is None else min(max_pages, total_pages)
        for page_idx in range(pages_to_read):
            page = doc[page_idx]
            page_text = self._clean_text(page.get_text())
            if page_text:
                texts.append(page_text)
                if not front_text:
                    front_text = page_text
            rect = page.rect
            total_area += rect.width * rect.height

        full_text = "\n\n".join(texts)
        if not full_text:
            return "", "", metadata

        if total_area > 0:
            text_density = len(full_text) / max(total_area / 100, 1)
            if text_density < min_text_ratio:
                return "", "", metadata
        return full_text, front_text, metadata

    def _extract_metadata(self, doc) -> dict:
        metadata = doc.metadata or {}
        return {
            "title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "subject": metadata.get("subject", ""),
            "keywords": metadata.get("keywords", ""),
            "creator": metadata.get("creator", ""),
            "producer": metadata.get("producer", ""),
            "creation_date": metadata.get("creationDate", ""),
            "modification_date": metadata.get("modDate", ""),
        }

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
        return text

    def get_page_count(self) -> int:
        return len(self._open())

    def get_first_page_text(self) -> str:
        doc = self._open()
        if len(doc) == 0:
            return ""
        return self._clean_text(doc[0].get_text())


def extract_text_with_fallback(
    pdf_path: Union[str, Path],
    max_pages: Optional[int] = None,
    ocr_engine=None,
    min_text_ratio: float = 0.001,
) -> Tuple[str, str, dict]:
    processor = PDFProcessor(pdf_path)
    try:
        full_text, front_text, metadata = processor.extract_text(
            max_pages=max_pages,
            min_text_ratio=min_text_ratio,
        )
        metadata["_text_source"] = "native"
        if full_text and not _looks_garbled(full_text):
            return full_text, front_text, metadata

        if ocr_engine is not None and hasattr(ocr_engine, "extract_text_from_pdf"):
            ocr_text, ocr_front_text, ocr_metadata = ocr_engine.extract_text_from_pdf(pdf_path, max_pages)
            merged_metadata = metadata.copy()
            merged_metadata.update(ocr_metadata or {})
            merged_metadata["_text_source"] = "ocr"
            return ocr_text, ocr_front_text, merged_metadata

        return "", "", metadata
    finally:
        processor.close()


def _looks_garbled(text: str) -> bool:
    if not text:
        return True
    stripped = "".join(text.split())
    if len(stripped) < 80:
        return False
    if "\ufffd" in text:
        return True
    valid_chars = sum(
        1
        for ch in stripped
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff" or ch in ".,;:!?()[]/%+-_=<>"
    )
    return (valid_chars / len(stripped)) < 0.6
