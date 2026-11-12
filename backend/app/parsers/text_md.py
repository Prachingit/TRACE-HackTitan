"""Text / Markdown parser — splits on headings then paragraphs."""

from pathlib import Path
from typing import List, Tuple


def parse_text(file_path: str) -> List[Tuple[int, str, str]]:
    """
    Return list of (ordinal, text, locator) tuples.
    Locator is the 1-based line range: "L1-L5".
    """
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    chunks: List[Tuple[int, str, str]] = []
    ordinal = 0
    buffer: List[str] = []
    buffer_start = 1

    def flush(end_line: int) -> None:
        nonlocal ordinal
        content = "".join(buffer).strip()
        if content:
            ordinal += 1
            chunks.append((ordinal, content, f"L{buffer_start}-L{end_line}"))
        buffer.clear()

    for i, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        is_heading = stripped.startswith("#")
        if is_heading and buffer:
            flush(i - 1)
            buffer_start = i
        buffer.append(line)
        # Also split on blank-line paragraph boundaries
        if line.strip() == "" and buffer and not is_heading:
            flush(i)
            buffer_start = i + 1

    flush(len(lines))
    return chunks
