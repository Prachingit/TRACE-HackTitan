"""GitHub REST API import service."""

import httpx
from typing import Dict, List, Any
from app.config import settings


BASE = "https://api.github.com"


def _headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "TRACE-HackTitan/2.0"}
    if settings.GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    return h


def _handle_github_response(resp: httpx.Response, repo: str) -> Any:
    if resp.status_code == 404:
        raise ValueError(f"GitHub repository '{repo}' not found or is private.")
    if resp.status_code == 403:
        reset = resp.headers.get("X-RateLimit-Reset", "unknown")
        raise ValueError(f"GitHub API rate limit exceeded. Reset at: {reset}.")
    if resp.status_code == 429:
        raise ValueError("GitHub API rate limited (429). Try again later.")
    resp.raise_for_status()
    return resp.json()


def fetch_commits(owner: str, repo: str, max_items: int = 200) -> List[Dict]:
    """Fetch up to max_items commits from a public GitHub repo."""
    commits = []
    page = 1
    per_page = min(100, max_items)
    full_name = f"{owner}/{repo}"

    with httpx.Client(timeout=30) as client:
        while len(commits) < max_items:
            resp = client.get(
                f"{BASE}/repos/{full_name}/commits",
                headers=_headers(),
                params={"per_page": per_page, "page": page},
            )
            data = _handle_github_response(resp, full_name)
            if not data:
                break
            commits.extend(data)
            if len(data) < per_page:
                break
            page += 1

    return commits[:max_items]


def fetch_pull_requests(owner: str, repo: str, max_items: int = 100) -> List[Dict]:
    """Fetch open and closed PRs."""
    prs = []
    full_name = f"{owner}/{repo}"
    with httpx.Client(timeout=30) as client:
        for state in ("open", "closed"):
            resp = client.get(
                f"{BASE}/repos/{full_name}/pulls",
                headers=_headers(),
                params={"state": state, "per_page": min(100, max_items)},
            )
            data = _handle_github_response(resp, full_name)
            prs.extend(data)
    return prs[:max_items]


def fetch_issues(owner: str, repo: str, max_items: int = 100) -> List[Dict]:
    """Fetch open and closed issues (excludes PRs)."""
    issues = []
    full_name = f"{owner}/{repo}"
    with httpx.Client(timeout=30) as client:
        for state in ("open", "closed"):
            resp = client.get(
                f"{BASE}/repos/{full_name}/issues",
                headers=_headers(),
                params={"state": state, "per_page": min(100, max_items), "filter": "all"},
            )
            data = _handle_github_response(resp, full_name)
            # GitHub issues endpoint also returns PRs — filter them out
            pure_issues = [i for i in data if "pull_request" not in i]
            issues.extend(pure_issues)
    return issues[:max_items]


def github_items_to_chunks(
    commits: List[Dict],
    prs: List[Dict],
    issues: List[Dict],
) -> List[tuple]:
    """Convert GitHub API responses into (ordinal, text, locator, author, timestamp) tuples."""
    items = []
    ordinal = 0

    for c in commits:
        commit_data = c.get("commit", {})
        message = commit_data.get("message", "").strip()
        sha = c.get("sha", "")[:12]
        author = commit_data.get("author", {}).get("name") or c.get("author", {}).get("login")
        ts = commit_data.get("author", {}).get("date")
        if message:
            ordinal += 1
            items.append((ordinal, f"[commit] {message}", f"sha:{sha}", author, ts))

    for pr in prs:
        title = pr.get("title", "")
        body = pr.get("body", "") or ""
        number = pr.get("number")
        author = pr.get("user", {}).get("login")
        ts = pr.get("created_at")
        state = pr.get("state", "")
        merged = pr.get("merged_at")
        text = f"[PR #{number}] {title} ({state}{', merged' if merged else ''})\n{body}".strip()
        ordinal += 1
        items.append((ordinal, text[:4000], f"pr:{number}", author, ts))

    for issue in issues:
        title = issue.get("title", "")
        body = issue.get("body", "") or ""
        number = issue.get("number")
        author = issue.get("user", {}).get("login")
        ts = issue.get("created_at")
        state = issue.get("state", "")
        labels = ", ".join(l["name"] for l in issue.get("labels", []))
        text = f"[Issue #{number}] {title} ({state}{', ' + labels if labels else ''})\n{body}".strip()
        ordinal += 1
        items.append((ordinal, text[:4000], f"issue:{number}", author, ts))

    return items
