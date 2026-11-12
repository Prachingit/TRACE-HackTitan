"""JSON parser — detects format and extracts chunks."""

import json
from pathlib import Path
from typing import List, Tuple

RECOGNIZED_FORMATS = ["atlas_commits", "slack_export", "generic_chat", "generic_array"]


def _is_atlas_commits(data) -> bool:
    return isinstance(data, list) and data and isinstance(data[0], dict) and "sha" in data[0]


def _is_slack_or_chat(data) -> bool:
    return isinstance(data, list) and data and isinstance(data[0], dict) and "text" in data[0]


def _is_generic_array(data) -> bool:
    return isinstance(data, list)


def parse_json(file_path: str) -> List[Tuple[int, str, str, str | None, str | None]]:
    """
    Return list of (ordinal, text, locator, author, timestamp) tuples.
    Raises ValueError with reason if format is unrecognized.
    """
    raw = Path(file_path).read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    chunks: List[Tuple[int, str, str, str | None, str | None]] = []
    ordinal = 0

    if _is_atlas_commits(data):
        # Atlas-style commits: [{sha, message, author, timestamp, ...}]
        for item in data:
            sha = item.get("sha", "")[:12]
            message = item.get("message") or item.get("commit", {}).get("message", "")
            author = item.get("author") or item.get("commit", {}).get("author", {}).get("name")
            ts = item.get("timestamp") or item.get("commit", {}).get("author", {}).get("date")
            if message:
                ordinal += 1
                chunks.append((ordinal, message.strip(), f"sha:{sha}", author, ts))
    elif _is_slack_or_chat(data):
        # Chat/Slack export: [{user, text, ts, ...}]
        for item in data:
            text = item.get("text") or item.get("message", "")
            author = item.get("user") or item.get("username") or item.get("author")
            ts = item.get("ts") or item.get("timestamp") or item.get("date")
            if text and text.strip():
                ordinal += 1
                chunks.append((ordinal, text.strip(), f"idx:{ordinal}", author, str(ts) if ts else None))
    elif _is_generic_array(data):
        for idx, item in enumerate(data, start=1):
            text = json.dumps(item, ensure_ascii=False)
            ordinal += 1
            chunks.append((ordinal, text, f"idx:{idx}", None, None))
    else:
        raise ValueError(
            "Unrecognized JSON format. "
            "Supported formats: Atlas commits array, Slack/chat export array, generic JSON array. "
            "Object/dict JSON is not supported — convert to an array first."
        )

    return chunks
