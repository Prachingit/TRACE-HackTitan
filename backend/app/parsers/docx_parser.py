"""DOCX parser — headings, paragraphs, and table cells."""

from pathlib import Path
from typing import List, Tuple


def parse_docx(file_path: str) -> List[Tuple[int, str, str]]:
    """
    Return list of (ordinal, text, locator) tuples.
    Locator is the paragraph index (1-based).
    """
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError("python-docx is not installed.")

    doc = Document(file_path)
    chunks: List[Tuple[int, str, str]] = []
    ordinal = 0
    buffer: List[str] = []
    buffer_start = 1

    def flush(end_idx: int) -> None:
        nonlocal ordinal
        content = "\n".join(buffer).strip()
        if content:
            ordinal += 1
            chunks.append((ordinal, content, f"para:{buffer_start}-{end_idx}"))
        buffer.clear()

    for idx, para in enumerate(doc.paragraphs, start=1):
        text = para.text.strip()
        if not text:
            flush(idx - 1)
            buffer_start = idx + 1
            continue
        # Headings flush prior buffer and become their own chunk
        if para.style.name.startswith("Heading"):
            flush(idx - 1)
            buffer_start = idx
            buffer.append(text)
            flush(idx)
            buffer_start = idx + 1
        else:
            buffer.append(text)

    flush(len(doc.paragraphs))

    # Also extract table cells
    for t_idx, table in enumerate(doc.tables, start=1):
        for r_idx, row in enumerate(table.rows, start=1):
            cell_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cell_texts:
                ordinal += 1
                chunks.append((ordinal, " | ".join(cell_texts), f"table:{t_idx}:row:{r_idx}"))

    return chunks
