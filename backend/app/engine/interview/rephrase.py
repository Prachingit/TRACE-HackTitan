"""Optional LLM rephrasing. Clarity only: any fact change or failure falls back to the template text."""

import re
from typing import Callable, Iterable, Optional

import httpx

from app.config import settings

_NUM = re.compile(r"\d+(?:[.\-/]\d+)*")


def _default_caller(prompt: str) -> str:
    url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": settings.LLM_MODEL,
        "temperature": 0.0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Rewrite the question so it is clear and polite. Do not add, remove or change any fact, name, "
                    "identifier or number. Return only the rewritten question as one paragraph."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    with httpx.Client(timeout=20.0) as client:
        resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def llm_available(caller: Optional[Callable[[str], str]]) -> bool:
    return caller is not None or bool(settings.LLM_API_KEY)


def rephrase(template_text: str, required_values: Iterable[str], caller: Optional[Callable[[str], str]] = None) -> Optional[str]:
    """Return a validated rephrasing, or None to keep the template text."""
    if not llm_available(caller):
        return None
    try:
        out = (caller or _default_caller)(template_text)
    except Exception:
        return None
    if not isinstance(out, str):
        return None
    out = " ".join(out.split())
    if not out or len(out) > max(600, int(len(template_text) * 2)):
        return None
    for v in required_values:
        if v and v in template_text and v not in out:
            return None  # a real value was dropped or altered
    if set(_NUM.findall(out)) - set(_NUM.findall(template_text)):
        return None  # a number appeared that is not in the template
    return out
