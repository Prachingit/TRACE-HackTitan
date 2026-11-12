"""CSV parser — one chunk per data row."""

import csv
import io
from pathlib import Path
from typing import List, Tuple

# Common aliases for author/timestamp columns
AUTHOR_ALIASES = {"author", "user", "assignee", "owner", "reporter", "created_by", "who"}
TIMESTAMP_ALIASES = {"timestamp", "date", "updated", "created_at", "updated_at", "time", "datetime"}


def parse_csv(file_path: str) -> List[Tuple[int, str, str, str | None, str | None]]:
    """
    Return list of (ordinal, text, locator, author, timestamp) tuples.
    Warns in error_message if no usable text columns detected.
    Raises ValueError for malformed CSV.
    """
    text = Path(file_path).read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise ValueError("CSV has no header row or is empty.")

    fields = [f.strip().lower() for f in reader.fieldnames if f]
    if not fields:
        raise ValueError("CSV has an empty header row.")

    author_col = next((f for f in reader.fieldnames if f and f.strip().lower() in AUTHOR_ALIASES), None)
    ts_col = next((f for f in reader.fieldnames if f and f.strip().lower() in TIMESTAMP_ALIASES), None)

    chunks: List[Tuple[int, str, str, str | None, str | None]] = []
    ordinal = 0

    for row_num, row in enumerate(reader, start=2):
        # Build a human-readable text from all columns
        parts = [f"{k.strip()}: {v.strip()}" for k, v in row.items() if k and v and v.strip()]
        if not parts:
            continue
        text_out = " | ".join(parts)
        author = row.get(author_col, "").strip() if author_col else None
        timestamp = row.get(ts_col, "").strip() if ts_col else None
        ordinal += 1
        chunks.append((ordinal, text_out, f"row:{row_num}", author or None, timestamp or None))

    return chunks
