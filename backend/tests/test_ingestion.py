"""Upload, parsing, states, deletion, clearance, sample and GitHub tests."""

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from tests.conftest import TestingSession, join_as, make_project, make_user
from app.models import Chunk, Source
from app.services import github as gh
from app.services.background import parse_source, reset_stuck_sources


def up(c, pid, name, data, clearance="team"):
    return c.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": (name, data)},
        data={"clearance_level": clearance},
    )


def setup_admin(email):
    c = make_user(email)
    ws, pid = make_project(c)
    return c, ws, pid


# ---- upload validation ----
def test_upload_markdown_parses(client):
    c, _, pid = setup_admin("up1@example.com")
    r = up(c, pid, "notes.md", b"# Title\n\nSome text here.\n\n## Next\n\nMore.\n")
    assert r.status_code == 201
    sid = r.json()["id"]
    d = c.get(f"/api/projects/{pid}/sources/{sid}").json()
    assert d["status"] == "parsed" and d["chunk_count"] >= 2
    chunks = c.get(f"/api/projects/{pid}/sources/{sid}/chunks").json()
    assert chunks[0]["locator"].startswith("L")


def test_upload_wrong_type(client):
    c, _, pid = setup_admin("up2@example.com")
    assert up(c, pid, "evil.exe", b"MZ....").status_code == 400


def test_upload_extension_spoof(client):
    c, _, pid = setup_admin("up3@example.com")
    assert up(c, pid, "fake.pdf", b"not a pdf at all").status_code == 400


def test_upload_empty(client):
    c, _, pid = setup_admin("up4@example.com")
    assert up(c, pid, "e.txt", b"").status_code == 400


def test_upload_too_large(client):
    c, _, pid = setup_admin("up5@example.com")
    assert up(c, pid, "big.txt", b"a" * (15 * 1024 * 1024 + 1)).status_code == 413


def test_upload_duplicate_hash(client):
    c, _, pid = setup_admin("up6@example.com")
    assert up(c, pid, "a.txt", b"same content").status_code == 201
    assert up(c, pid, "b.txt", b"same content").status_code == 409


def test_upload_path_traversal_name(client):
    c, _, pid = setup_admin("up7@example.com")
    r = up(c, pid, "../../etc/passwd.txt", b"hello world")
    assert r.status_code == 201
    assert "/" not in r.json()["filename"] and ".." not in r.json()["filename"]
    stored = Path(TestingSession().query(Source).filter_by(id=r.json()["id"]).one().file_path)
    assert "uploads" in stored.parts


def test_upload_requires_auth(client):
    assert client.post("/api/projects/x/sources/upload", files={"file": ("a.txt", b"x")}).status_code == 401


# ---- parsers ----
def test_csv_parser_rows(client):
    c, _, pid = setup_admin("pc1@example.com")
    sid = up(c, pid, "t.csv", b"task,assignee,date\nFix login,Asha,2026-01-02\nAdd tests,Ravi,2026-01-03\n").json()["id"]
    chunks = c.get(f"/api/projects/{pid}/sources/{sid}/chunks").json()
    assert len(chunks) == 2 and chunks[0]["author"] == "Asha"


def test_bad_json_fails_with_reason(client):
    c, _, pid = setup_admin("pj1@example.com")
    sid = up(c, pid, "bad.json", b"{not json").json()["id"]
    d = c.get(f"/api/projects/{pid}/sources/{sid}").json()
    assert d["status"] == "failed" and "Invalid JSON" in d["error_message"]


def test_unrecognized_json_object_fails(client):
    c, _, pid = setup_admin("pj2@example.com")
    sid = up(c, pid, "obj.json", b'{"a": 1}').json()["id"]
    assert c.get(f"/api/projects/{pid}/sources/{sid}").json()["status"] == "failed"


def test_chat_json_parses(client):
    c, _, pid = setup_admin("pj3@example.com")
    data = json.dumps([{"user": "asha", "text": "deploy done", "ts": "2026-01-01T10:00:00Z"}]).encode()
    sid = up(c, pid, "chat.json", data).json()["id"]
    ch = c.get(f"/api/projects/{pid}/sources/{sid}/chunks").json()
    assert ch[0]["author"] == "asha" and ch[0]["timestamp"] is not None


def test_scanned_pdf_fails_with_message(client):
    from pypdf import PdfWriter
    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    w.write(buf)
    c, _, pid = setup_admin("pp1@example.com")
    sid = up(c, pid, "scan.pdf", buf.getvalue()).json()["id"]
    d = c.get(f"/api/projects/{pid}/sources/{sid}").json()
    assert d["status"] == "failed" and "OCR is not supported" in d["error_message"]


def test_docx_parses(client):
    from docx import Document
    buf = io.BytesIO()
    doc = Document()
    doc.add_heading("Design", 1)
    doc.add_paragraph("We chose SQLite.")
    doc.save(buf)
    c, _, pid = setup_admin("pd1@example.com")
    sid = up(c, pid, "d.docx", buf.getvalue()).json()["id"]
    d = c.get(f"/api/projects/{pid}/sources/{sid}").json()
    assert d["status"] == "parsed" and d["chunk_count"] >= 1


# ---- states ----
def test_stuck_parsing_reset_to_queued(client):
    c, _, pid = setup_admin("st1@example.com")
    sid = up(c, pid, "s.txt", b"hello there").json()["id"]
    db = TestingSession()
    s = db.get(Source, sid)
    s.status = "parsing"
    db.commit()
    assert reset_stuck_sources(db) >= 1
    assert db.get(Source, sid).status == "queued"
    parse_source(sid, db)
    assert db.get(Source, sid).status == "parsed"
    db.close()


def test_failed_source_retry(client):
    c, _, pid = setup_admin("st2@example.com")
    sid = up(c, pid, "bad.json", b"{x").json()["id"]
    r = c.post(f"/api/projects/{pid}/sources/{sid}/retry")
    assert r.status_code == 200


# ---- deletion ----
def test_delete_source_removes_chunks_and_file(client):
    c, _, pid = setup_admin("del1@example.com")
    sid = up(c, pid, "d.txt", b"delete me please").json()["id"]
    db = TestingSession()
    path = Path(db.get(Source, sid).file_path)
    assert path.exists()
    assert c.delete(f"/api/projects/{pid}/sources/{sid}").status_code == 204
    db.expire_all()
    assert not path.exists()
    assert db.query(Chunk).filter_by(source_id=sid).count() == 0
    db.close()


def test_delete_project_admin_only(client):
    admin, ws, pid = setup_admin("del2@example.com")
    member = join_as(admin, ws, "del2m@example.com", "team_member")
    assert member.delete(f"/api/projects/{pid}").status_code == 403
    assert admin.delete(f"/api/projects/{pid}").status_code == 204


# ---- clearance ----
def test_restricted_hidden_from_incoming(client):
    admin, ws, pid = setup_admin("cl1@example.com")
    sid = up(admin, pid, "secret.txt", b"restricted stuff", clearance="restricted").json()["id"]
    inc = join_as(admin, ws, "cl1i@example.com", "incoming")
    assert sid not in [s["id"] for s in inc.get(f"/api/projects/{pid}/sources").json()]
    assert inc.get(f"/api/projects/{pid}/sources/{sid}").status_code == 404
    assert inc.get(f"/api/projects/{pid}/sources/{sid}/chunks").status_code == 404
    assert sid in [s["id"] for s in admin.get(f"/api/projects/{pid}/sources").json()]


def test_non_admin_cannot_mark_restricted(client):
    admin, ws, pid = setup_admin("cl2@example.com")
    tm = join_as(admin, ws, "cl2m@example.com", "team_member")
    assert up(tm, pid, "x.txt", b"abc def", clearance="restricted").status_code == 403


# ---- sample ----
def test_sample_only_in_callers_project(client):
    a, _, pa = setup_admin("sm1@example.com")
    b, _, pb = setup_admin("sm2@example.com")
    r = a.post(f"/api/projects/{pa}/sample")
    assert r.status_code == 201 and r.json()["sources_added"] >= 5
    assert len(b.get(f"/api/projects/{pb}/sources").json()) == 0
    assert b.post(f"/api/projects/{pa}/sample").status_code == 404
    assert a.get(f"/api/projects/{pa}").json()["is_synthetic"] is True
    again = a.post(f"/api/projects/{pa}/sample").json()
    assert again["sources_added"] == 0


# ---- github (mocked) ----
def test_github_import_success(client, monkeypatch):
    import app.routers.sources as srcmod
    monkeypatch.setattr(srcmod, "fetch_commits", lambda o, r: [{"sha": "a" * 40, "commit": {"message": "init", "author": {"name": "Asha", "date": "2026-01-01T00:00:00Z"}}}])
    monkeypatch.setattr(srcmod, "fetch_pull_requests", lambda o, r: [])
    monkeypatch.setattr(srcmod, "fetch_issues", lambda o, r: [])
    c, _, pid = setup_admin("gh1@example.com")
    r = c.post(f"/api/projects/{pid}/sources/github", json={"repo_url": "https://github.com/octo/demo"})
    assert r.status_code == 201
    d = c.get(f"/api/projects/{pid}/sources/{r.json()['id']}").json()
    assert d["status"] == "parsed" and d["chunk_count"] == 1


def test_github_import_empty_repo_fails(client, monkeypatch):
    import app.routers.sources as srcmod
    for n in ("fetch_commits", "fetch_pull_requests", "fetch_issues"):
        monkeypatch.setattr(srcmod, n, lambda o, r: [])
    c, _, pid = setup_admin("gh2@example.com")
    r = c.post(f"/api/projects/{pid}/sources/github", json={"repo_url": "https://github.com/octo/empty"})
    assert c.get(f"/api/projects/{pid}/sources/{r.json()['id']}").json()["status"] == "failed"


def test_github_bad_url(client):
    c, _, pid = setup_admin("gh3@example.com")
    assert c.post(f"/api/projects/{pid}/sources/github", json={"repo_url": "https://example.com/x"}).status_code == 400


def test_github_404_and_rate_limit_messages():
    with pytest.raises(ValueError, match="not found"):
        gh._handle_github_response(httpx.Response(404), "o/r")
    with pytest.raises(ValueError, match="rate limit"):
        gh._handle_github_response(httpx.Response(403, headers={"X-RateLimit-Reset": "123"}), "o/r")
