"""PDF parser using pypdf — per-page chunks."""

from pathlib import Path
from typing import List, Tuple


def parse_pdf(file_path: str) -> List[Tuple[int, str, str]]:
    """
    Return list of (ordinal, text, locator) tuples, one per PDF page.
    Raises ValueError if no extractable text is found (scanned PDF).
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf is not installed.")

    reader = PdfReader(file_path)
    chunks: List[Tuple[int, str, str]] = []
    ordinal = 0

    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            ordinal += 1
            chunks.append((ordinal, text, f"page:{page_num}"))

    if not chunks:
        raise ValueError(
            "No extractable text found in this PDF. "
            "It may be a scanned document. OCR is not supported yet."
        )
    return chunks
