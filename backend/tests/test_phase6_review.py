"""Phase 6 tests: exit interview, answers as evidence, review workbench, roles, history, isolation."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.interview.gaps import Gap
from app.engine.interview.rephrase import rephrase
from app.engine.interview.templates import render
from app.models import (
    Chunk,
    Claim,
    ClaimEvidence,
    Contradiction,
    InterviewQuestion,
    ReviewEvent,
)
from tests.conftest import TestingSession, join_as, make_project, make_user

TRACKER = (
    b"task_id,title,module,status,assignee,depends_on,updated\n"
    b"INV-1,Generate PDF invoices,invoicing,Done,Liam Ortiz,INV-2,2026-10-25\n"
    b"INV-2,Currency rounding rules,invoicing,In Progress,Liam Ortiz,,2026-08-01\n"
    b"INV-3,Archive old receipts,archival,Todo,None,,2026-10-26\n"
)
NOTES = (
    b"# Invoicing Notes (2026-10-28)\n"
    b"Owner: Maya Lin will handle invoicing module architecture.\n"
    b"Pending testing for invoicing PDF export before production release.\n"
    b"- We decided to retain invoices for seven years in the invoicing module.\n"
)
RESTRICTED = (
    b"# Confidential Audit (2026-10-29)\n"
    b"Compliance module is blocked by legal retention sign-off.\n"
    b"- We decided to encrypt compliance exports in the compliance module.\n"
)


def _upload(client, pid, filename, content, clearance="team"):
    r = client.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": (filename, content)},
        data={"clearance_level": clearance},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _project(email=None, name="Nora", restricted=False):
    email = email or f"p6_admin_{os.urandom(4).hex()}@example.com"
    admin = make_user(email, name)
    admin.email_addr = email
    ws_id, pid = make_project(admin, "Ledger Co")
    _upload(admin, pid, "tracker.csv", TRACKER)
    _upload(admin, pid, "notes.md", NOTES)
    if restricted:
        _upload(admin, pid, "audit.md", RESTRICTED, clearance="restricted")
    assert admin.post(f"/api/projects/{pid}/analyze").status_code == 202
    return admin, ws_id, pid


def _claims(c, pid):
    return c.get(f"/api/projects/{pid}/claims").json()


def _questions(c, pid, **params):
    r = c.get(f"/api/projects/{pid}/interview", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _make_supported_claim(pid, text="Supported claim for review.", verification="inferred", module="invoicing"):
    """Insert a claim backed by a real chunk excerpt (no contradictions)."""
    db = TestingSession()
    try:
        from app.models import Source
        src = db.query(Source).filter(Source.project_id == pid).first()
        ch = db.query(Chunk).filter(Chunk.source_id == src.id).first()
        c = Claim(
            id=f"CLM-T{os.urandom(3).hex().upper()}",
            project_id=pid, claim_type="decision", title="Supported", text=text, module=module,
            verification_status=verification, review_status="unreviewed", clearance_level="team", extractor="rule",
        )
        db.add(c)
        db.flush()
        db.add(ClaimEvidence(claim_id=c.id, source_id=src.id, chunk_id=ch.id, excerpt=ch.text[:20]))
        db.commit()
        return c.id
    finally:
        db.close()


def _make_unsupported_claim(pid):
    db = TestingSession()
    try:
        c = Claim(
            id=f"CLM-N{os.urandom(3).hex().upper()}",
            project_id=pid, claim_type="decision", title="Unsupported", text="No evidence here.", module="invoicing",
            verification_status="inferred", review_status="unreviewed", clearance_level="team", extractor="rule",
        )
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


# â”€â”€ 1. Question generation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_templates_fire_with_real_values_only():
    cases = [
        (Gap("conflicting_ownership", "billing", "high", "a", {
            "module": "billing", "contradiction_id": "CTR-1", "rule_code": "CONFLICTING_OWNERSHIP", "reason": "r",
            "owners": [{"owner": "Ann Lee", "source": "tasks.csv"}, {"owner": "Bo Chan", "source": "notes.md"}],
        }, contradiction_id="CTR-1"), ["billing", "Ann Lee", "tasks.csv", "Bo Chan", "notes.md"]),
        (Gap("status_without_evidence", "api", "high", "b", {
            "module": "api", "title": "T-9: Ship API", "raw_status": "Done", "contradiction_id": "CTR-2",
            "rule_code": "STATUS_WITHOUT_EVIDENCE", "reason": "r",
        }, contradiction_id="CTR-2"), ["T-9: Ship API", "Done", "api"]),
        (Gap("conflicting_status", "core", "high", "c", {
            "module": "core", "contradiction_id": "CTR-3", "rule_code": "CONFLICTING_STATUS", "reason": "r",
            "topic": "caching", "choices": [{"choice": "redis", "source": "a.md"}, {"choice": "lru", "source": "b.md"}],
        }, contradiction_id="CTR-3"), ["caching", "redis", "lru", "a.md", "b.md"]),
        (Gap("unresolved_dependency", "core", "high", "d", {
            "module": "core", "contradiction_id": "CTR-4", "rule_code": "UNRESOLVED_DEPENDENCY", "reason": "r",
            "depends_on": "X-1", "from_task": "X-2",
        }, contradiction_id="CTR-4"), ["X-1", "X-2", "core"]),
        (Gap("stale_activity", "core", "medium", "e", {
            "module": "core", "contradiction_id": "CTR-5", "rule_code": "STALE_ACTIVITY", "reason": "r",
            "title": "Slow task", "last_activity": "2026-08-01",
        }, contradiction_id="CTR-5"), ["Slow task", "2026-08-01"]),
        (Gap("unassigned_responsibility", "ops", "medium", "f", {
            "module": "ops", "contradiction_id": "CTR-6", "rule_code": "UNASSIGNED_RESPONSIBILITY", "reason": "r",
            "title": "Backups",
        }, contradiction_id="CTR-6"), ["Backups", "ops"]),
        (Gap("undocumented_work", "ops", "medium", "g", {
            "module": "ops", "contradiction_id": "CTR-7", "rule_code": "UNDOCUMENTED_WORK", "reason": "r",
            "activity_count": 4,
        }, contradiction_id="CTR-7"), ["ops", "4"]),
        (Gap("missing_test_evidence", "ops", "high", "h", {
            "module": "ops", "contradiction_id": "CTR-8", "rule_code": "MISSING_TEST_EVIDENCE", "reason": "r",
            "pending": True,
        }, contradiction_id="CTR-8"), ["ops", "pending"]),
        (Gap("decision_rationale", "db", "medium", "i", {
            "module": "db", "title": "t", "source": "adr.md", "text": "We decided to use Postgres.",
        }), ["We decided to use Postgres.", "adr.md"]),
        (Gap("module_doc", "db", "medium", "j", {"module": "db"}), ["db"]),
        (Gap("unassigned_task", "db", "medium", "k", {"module": "db", "title": "Seed data", "source": "t.csv", "text": "x"}),
         ["Seed data", "db", "t.csv"]),
        (Gap("pending_test", "db", "medium", "l", {"module": "db", "title": "t", "source": "n.md", "text": "x"}), ["db", "n.md"]),
        (Gap("blocker_open", "db", "medium", "m", {"module": "db", "title": "t", "source": "n.md", "text": "waiting on DBA"}),
         ["db", "waiting on DBA"]),
        (Gap("dependency_open", "db", "medium", "n", {"module": "db", "title": "t", "source": "n.md", "text": "depends on auth"}),
         ["db", "depends on auth"]),
        (Gap("missing_claim", "db", "medium", "o", {"module": "db", "title": "Unknown task", "source": "t.csv", "text": "x"}),
         ["Unknown task", "db", "t.csv"]),
        (Gap("inferred_claim", "db", "low", "p", {"module": "db", "title": "Maybe done", "source": "n.md", "text": "x"}),
         ["Maybe done", "db", "n.md"]),
        (Gap("conflicting_claim", "db", "high", "q", {"module": "db", "title": "Odd claim", "source": "n.md", "text": "x"}),
         ["Odd claim", "db", "n.md"]),
    ]
    for gap, expected in cases:
        text = render(gap)
        assert "{" not in text and "}" not in text, text
        for value in expected:
            assert value in text, (gap.gap_type, value, text)


def test_generation_grouping_dedup_and_answered_survive(client):
    admin, ws_id, pid = _project()
    gen = admin.post(f"/api/projects/{pid}/interview/generate")
    assert gen.status_code == 200, gen.text
    first = gen.json()
    assert first["created"] > 0 and first["created"] == first["total"]

    data = _questions(admin, pid)
    qs = data["questions"]
    assert len(qs) == first["total"]
    # Grouped by module and by target person, with real counts
    assert {g["name"] for g in data["by_module"]} >= {"invoicing", "archival"}
    assert any(g["name"] == "unassigned" for g in data["by_person"])
    assert sum(g["total"] for g in data["by_module"]) == len(qs)
    assert data["progress"] == {"total": len(qs), "answered": 0, "skipped": 0, "open": len(qs)}

    claim_modules = {c["module"] for c in _claims(admin, pid)}
    assert {q["module"] for q in qs} <= claim_modules

    by_type = {}
    for q in qs:
        by_type.setdefault(q["gap_type"], []).append(q)

    # No invented facts: values in the question text come from the uploaded data
    own = by_type["conflicting_ownership"][0]["question"]
    assert "Liam Ortiz" in own and "Maya Lin" in own and "tracker.csv" in own and "notes.md" in own
    assert "Generate PDF invoices" in by_type["status_without_evidence"][0]["question"]
    assert "Done" in by_type["status_without_evidence"][0]["question"]
    assert "2026-08-01" in by_type["stale_activity"][0]["question"]
    assert "Archive old receipts" in by_type["unassigned_responsibility"][0]["question"]
    assert "archival" in by_type["module_doc"][0]["question"]
    for q in qs:
        assert q["text_source"] == "template"
        assert q["priority"] in ("high", "medium", "low")
        assert q["context"] or q["gap_type"] == "module_doc"  # source excerpts shown for context

    # Idempotent regenerate: no duplicates
    ids = {q["id"] for q in qs}
    again = admin.post(f"/api/projects/{pid}/interview/generate").json()
    assert again["created"] == 0 and again["total"] == first["total"]
    assert {q["id"] for q in _questions(admin, pid)["questions"]} == ids

    # Answered questions survive a regenerate
    target = by_type["conflicting_ownership"][0]
    r = admin.post(f"/api/interview/questions/{target['id']}/answer", json={"answer": "Liam Ortiz owns it."})
    assert r.status_code == 200
    admin.post(f"/api/projects/{pid}/interview/generate")
    survived = [q for q in _questions(admin, pid)["questions"] if q["id"] == target["id"]]
    assert survived and survived[0]["status"] == "answered" and survived[0]["answer"] == "Liam Ortiz owns it."

    # Filters
    assert all(q["module"] == "archival" for q in _questions(admin, pid, module="archival")["questions"])
    assert all(q["status"] == "answered" for q in _questions(admin, pid, status="answered")["questions"])
    assert all(q["status"] != "answered" for q in _questions(admin, pid, status="unanswered")["questions"])
    assert all(q["target_label"] == "unassigned" for q in _questions(admin, pid, person="unassigned")["questions"])


def test_regenerate_after_reanalysis_does_not_duplicate(client):
    admin, ws_id, pid = _project()
    first = admin.post(f"/api/projects/{pid}/interview/generate").json()
    admin.post(f"/api/projects/{pid}/analyze")
    second = admin.post(f"/api/projects/{pid}/interview/generate").json()
    assert second["total"] == first["total"]


def test_skip_requires_reason_and_survives_regenerate(client):
    admin, ws_id, pid = _project()
    admin.post(f"/api/projects/{pid}/interview/generate")
    q = _questions(admin, pid)["questions"][0]
    assert admin.post(f"/api/interview/questions/{q['id']}/skip", json={"reason": "  "}).status_code == 400
    r = admin.post(f"/api/interview/questions/{q['id']}/skip", json={"reason": "Not relevant to handover"})
    assert r.status_code == 200 and r.json()["status"] == "skipped"
    admin.post(f"/api/projects/{pid}/interview/generate")
    after = {x["id"]: x for x in _questions(admin, pid)["questions"]}
    assert after[q["id"]]["status"] == "skipped" and after[q["id"]]["skip_reason"] == "Not relevant to handover"


# â”€â”€ 2. Answers become evidence â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_answer_is_new_attributed_evidence_and_never_verifies(client):
    admin, ws_id, pid = _project()
    admin.post(f"/api/projects/{pid}/interview/generate")
    q = next(x for x in _questions(admin, pid)["questions"] if x["gap_type"] == "conflicting_ownership")
    cid = q["claim_id"]
    before = admin.get(f"/api/claims/{cid}").json()
    before_doc = [(e["id"], e["excerpt"]) for e in before["evidence"]]
    assert before["verification_status"] != "verified"

    assert admin.post(f"/api/interview/questions/{q['id']}/answer", json={"answer": "   "}).status_code == 400
    r = admin.post(
        f"/api/interview/questions/{q['id']}/answer",
        json={"answer": "Liam handed this to Maya on 2026-10-01.", "answered_by": "someone else"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "answered" and r.json()["answered_by_name"] == "Nora"
    assert admin.post(f"/api/interview/questions/{q['id']}/answer", json={"answer": "Again"}).status_code == 409

    after = admin.get(f"/api/claims/{cid}").json()
    answers = [e for e in after["evidence"] if e["evidence_type"] == "interview_answer"]
    assert len(answers) == 1
    a = answers[0]
    assert a["excerpt"] == "Liam handed this to Maya on 2026-10-01."
    assert a["author"] == "Nora" and a["timestamp"] is not None and a["source_id"] is None
    assert a["label"].startswith("Interview answer, by Nora, ")
    # Original document evidence is untouched
    assert [(e["id"], e["excerpt"]) for e in after["evidence"] if e["evidence_type"] != "interview_answer"] == before_doc
    # Goes to needs review, never verified
    assert after["review_status"] == "needs_review"
    assert after["verification_status"] == before["verification_status"] != "verified"
    assert after["interview_answer_count"] == 1

    # Evidence validation stays clean and the claim survives re-analysis with its answer
    assert admin.get(f"/api/projects/{pid}/ledger/validation").json()["invalid_citation_count"] == 0
    admin.post(f"/api/projects/{pid}/analyze")
    survived = admin.get(f"/api/claims/{cid}").json()
    assert survived["interview_answer_count"] == 1


def test_answer_for_gap_without_claim_creates_human_claim(client):
    admin, ws_id, pid = _project()
    admin.post(f"/api/projects/{pid}/interview/generate")
    q = next(x for x in _questions(admin, pid)["questions"] if x["gap_type"] == "module_doc" and x["module"] == "archival")
    assert q["claim_id"] is None
    r = admin.post(f"/api/interview/questions/{q['id']}/answer", json={"answer": "Archival moves receipts to cold storage nightly."})
    assert r.status_code == 200
    cid = r.json()["claim_id"]
    assert cid
    claim = admin.get(f"/api/claims/{cid}").json()
    assert claim["extractor"] == "human" and claim["origin_label"] == "human-authored"
    assert claim["verification_status"] == "inferred" and claim["review_status"] == "unreviewed"
    assert claim["module"] == "archival"
    assert [e["evidence_type"] for e in claim["evidence"]] == ["interview_answer"]
    # Human claims survive re-analysis and are not asked about again
    admin.post(f"/api/projects/{pid}/analyze")
    assert admin.get(f"/api/claims/{cid}").status_code == 200
    admin.post(f"/api/projects/{pid}/interview/generate")
    assert not [x for x in _questions(admin, pid)["questions"] if x["gap_type"] == "module_doc" and x["module"] == "archival" and x["status"] == "open"]


def test_team_member_answers_only_own_items(client):
    admin, ws_id, pid = _project()
    member_email = f"p6_member_{os.urandom(3).hex()}@example.com"
    member = join_as(admin, ws_id, member_email, "team_member")
    admin.post(f"/api/projects/{pid}/interview/generate")
    q = _questions(member, pid)["questions"][0]
    assert q["can_answer"] is False
    assert member.post(f"/api/interview/questions/{q['id']}/answer", json={"answer": "Not mine"}).status_code == 403
    assert member.post(f"/api/interview/questions/{q['id']}/skip", json={"reason": "x"}).status_code == 403

    db = TestingSession()
    try:
        from app.models import User
        uid = db.query(User).filter(User.email == member_email).first().id
        row = db.get(InterviewQuestion, q["id"])
        row.target_person_id = uid
        row.target_label = "p6_member"
        db.commit()
    finally:
        db.close()
    r = member.post(f"/api/interview/questions/{q['id']}/answer", json={"answer": "This one is mine."})
    assert r.status_code == 200


# â”€â”€ 3. Review workbench â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_accept_blocked_by_open_contradiction_then_resolved_in_same_action(client):
    admin, ws_id, pid = _project()
    claims = _claims(admin, pid)
    inv1 = next(c for c in claims if c["task_key"] == "INV-1" and c["claim_type"] == "task_status")
    assert inv1["verification_status"] != "verified"  # conflicting claims never start Verified
    ctrs = admin.get(f"/api/projects/{pid}/contradictions").json()
    linked = [c for c in ctrs if inv1["id"] in c["claim_ids"] and c["status"] == "open"]
    assert linked

    r = admin.post(f"/api/claims/{inv1['id']}/review", json={"action": "accept"})
    assert r.status_code == 409
    assert "Resolve contradiction first" in r.json()["detail"] and linked[0]["id"] in r.json()["detail"]
    assert admin.get(f"/api/claims/{inv1['id']}").json()["verification_status"] != "verified"

    # Resolve in the same action: note required
    assert admin.post(
        f"/api/claims/{inv1['id']}/review", json={"action": "accept", "resolve_contradictions": True}
    ).status_code == 400
    ok = admin.post(
        f"/api/claims/{inv1['id']}/review",
        json={"action": "accept", "resolve_contradictions": True, "note": "Confirmed with Liam; invoices ship in v2."},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["review_status"] == "approved" and body["verification_status"] == "verified"
    assert body["reviewed_by_name"] == "Nora" and body["reviewed_at"] is not None
    assert set(body["resolved_contradiction_ids"]) >= {c["id"] for c in linked}
    ctr = admin.get(f"/api/contradictions/{linked[0]['id']}").json()
    assert ctr["status"] == "resolved" and ctr["resolved_by_name"] == "Nora"
    assert ctr["resolution_note"] == "Confirmed with Liam; invoices ship in v2."


def test_accept_requires_valid_evidence_and_verifies_only_after_human_accept(client):
    admin, ws_id, pid = _project()
    # No evidence at all
    bare = _make_unsupported_claim(pid)
    r = admin.post(f"/api/claims/{bare}/review", json={"action": "accept"})
    assert r.status_code == 409 and "No valid evidence" in r.json()["detail"]
    # Evidence whose excerpt no longer matches its chunk is not valid
    tampered = _make_supported_claim(pid, text="Tampered")
    db = TestingSession()
    try:
        ev = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == tampered).first()
        ev.excerpt = "THIS TEXT IS NOT IN THE CHUNK"
        db.commit()
    finally:
        db.close()
    assert admin.post(f"/api/claims/{tampered}/review", json={"action": "accept"}).status_code == 409

    good = _make_supported_claim(pid, text="Good claim")
    assert admin.get(f"/api/claims/{good}").json()["verification_status"] == "inferred"
    r = admin.post(f"/api/claims/{good}/review", json={"action": "accept", "note": "Checked against notes."})
    assert r.status_code == 200
    assert r.json()["verification_status"] == "verified" and r.json()["review_status"] == "approved"

    # An interview answer counts as valid evidence once a human accepts
    only_answer = _make_unsupported_claim(pid)
    db = TestingSession()
    try:
        from app.models import User
        u = db.query(User).filter(User.email == admin.email_addr).first()
        db.add(ClaimEvidence(
            claim_id=only_answer, source_id=None, excerpt="Told to me directly.", author=u.name, author_id=u.id,
            evidence_type="interview_answer",
        ))
        db.commit()
    finally:
        db.close()
    assert admin.post(f"/api/claims/{only_answer}/review", json={"action": "accept"}).status_code == 200


def test_edit_reject_flag_and_versioned_history(client):
    admin, ws_id, pid = _project()
    cid = _make_supported_claim(pid, text="The retention period is five years.", verification="verified")

    assert admin.post(f"/api/claims/{cid}/review", json={"action": "edit", "text": "  "}).status_code == 400
    assert admin.post(f"/api/claims/{cid}/review", json={"action": "edit", "text": "The retention period is five years."}).status_code == 400
    e1 = admin.post(f"/api/claims/{cid}/review", json={"action": "edit", "text": "The retention period is seven years.", "note": "Fixed from notes"})
    assert e1.status_code == 200
    b = e1.json()
    assert b["review_status"] == "edited" and b["text"] == "The retention period is seven years."
    assert b["original_text"] == "The retention period is five years."
    assert b["verification_status"] == "inferred"  # edited wording must be accepted again to verify
    e2 = admin.post(f"/api/claims/{cid}/review", json={"action": "edit", "text": "The retention period is seven years for invoices."})
    assert e2.json()["original_text"] == "The retention period is five years."

    assert admin.post(f"/api/claims/{cid}/review", json={"action": "flag"}).status_code == 400
    f = admin.post(f"/api/claims/{cid}/review", json={"action": "flag", "note": "Needs legal sign-off"})
    assert f.status_code == 200 and f.json()["review_status"] == "needs_review"

    assert admin.post(f"/api/claims/{cid}/review", json={"action": "reject"}).status_code == 400
    rj = admin.post(f"/api/claims/{cid}/review", json={"action": "reject", "note": "Superseded by policy"})
    assert rj.status_code == 200 and rj.json()["review_status"] == "rejected"
    still = admin.get(f"/api/claims/{cid}")
    assert still.status_code == 200  # never deleted
    assert admin.post(f"/api/claims/{cid}/review", json={"action": "bogus"}).status_code == 400

    hist = admin.get(f"/api/claims/{cid}/history").json()
    assert [h["version"] for h in hist] == [1, 2, 3, 4]
    assert [h["action"] for h in hist] == ["edit", "edit", "flag", "reject"]
    assert all(h["reviewer_name"] == "Nora" and h["timestamp"] for h in hist)
    first = hist[0]
    assert first["old_text"] == "The retention period is five years." and first["new_text"].endswith("seven years.")
    ops = {d["op"] for d in first["diff"]}
    assert {"insert", "delete"} <= ops
    assert "".join(d["text"] for d in first["diff"] if d["op"] != "insert") == first["old_text"]
    assert "".join(d["text"] for d in first["diff"] if d["op"] != "delete") == first["new_text"]
    assert hist[3]["note"] == "Superseded by policy"


def test_review_history_is_append_only(client):
    admin, ws_id, pid = _project()
    cid = _make_supported_claim(pid)
    admin.post(f"/api/claims/{cid}/review", json={"action": "flag", "note": "check"})
    hist = admin.get(f"/api/claims/{cid}/history").json()
    eid = hist[0]["id"]
    for method in ("put", "patch", "delete", "post"):
        r = getattr(admin, method)(f"/api/claims/{cid}/history")
        assert r.status_code in (404, 405), (method, r.status_code)
    for method in ("put", "patch", "delete"):
        r = getattr(admin, method)(f"/api/claims/{cid}/history/{eid}")
        assert r.status_code in (404, 405), (method, r.status_code)
    assert admin.get(f"/api/claims/{cid}/history").json()[0]["id"] == eid

    db = TestingSession()
    try:
        row = db.get(ReviewEvent, eid)
        row.new_text = "tampered"
        with pytest.raises(ValueError):
            db.flush()
        db.rollback()
    finally:
        db.close()
    assert admin.get(f"/api/claims/{cid}/history").json()[0]["new_text"] != "tampered"


def test_roles_are_enforced_by_the_backend(client):
    admin, ws_id, pid = _project()
    cid = _make_supported_claim(pid)
    member = join_as(admin, ws_id, f"p6_tm_{os.urandom(3).hex()}@example.com", "team_member")
    incoming = join_as(admin, ws_id, f"p6_in_{os.urandom(3).hex()}@example.com", "incoming")
    departing = join_as(admin, ws_id, f"p6_dep_{os.urandom(3).hex()}@example.com", "departing")
    ctr = admin.get(f"/api/projects/{pid}/contradictions").json()[0]["id"]

    for who in (member, incoming, departing):
        for action, extra in (("accept", {}), ("edit", {"text": "New wording"}), ("reject", {"note": "no"})):
            r = who.post(f"/api/claims/{cid}/review", json={"action": action, **extra})
            assert r.status_code == 403, (action, r.status_code)
        assert who.post(f"/api/projects/{pid}/review/bulk", json={"claim_ids": [cid]}).status_code == 403
        assert who.post(f"/api/projects/{pid}/interview/generate").status_code == 403
        assert who.post(f"/api/contradictions/{ctr}/resolve", json={"note": "n"}).status_code == 403
    assert incoming.post(f"/api/claims/{cid}/review", json={"action": "flag", "note": "x"}).status_code == 403
    assert departing.post(f"/api/claims/{cid}/review", json={"action": "flag", "note": "x"}).status_code == 403
    assert incoming.get(f"/api/projects/{pid}/review/queue").status_code == 403
    assert departing.get(f"/api/projects/{pid}/review/queue").status_code == 403
    assert incoming.get(f"/api/projects/{pid}/interview").status_code == 403

    # Team members may flag and see the queue; nothing was changed by the denied calls
    assert member.get(f"/api/projects/{pid}/review/queue").status_code == 200
    assert member.post(f"/api/claims/{cid}/review", json={"action": "flag", "note": "Please re-check"}).status_code == 200
    assert admin.get(f"/api/claims/{cid}").json()["review_status"] == "needs_review"
    assert [h["action"] for h in admin.get(f"/api/claims/{cid}/history").json()] == ["flag"]

    assert admin.post(f"/api/claims/{cid}/review", json={"action": "accept"}).status_code == 200
    assert admin.post(f"/api/contradictions/{ctr}/resolve", json={"note": "Reviewed"}).status_code == 200


def test_queue_priority_and_bulk_accept_reports_skipped(client):
    admin, ws_id, pid = _project()
    queue = admin.get(f"/api/projects/{pid}/review/queue").json()
    order = [i["verification_status"] for i in queue["items"]]
    rank = {"conflicting": 0, "missing": 1, "inferred": 2, "verified": 3}
    assert [rank[o] for o in order] == sorted(rank[o] for o in order)
    assert queue["total"] == len(queue["items"]) and queue["counts_by_verification"]
    blocked = next(i for i in queue["items"] if i["open_contradiction_ids"])
    assert blocked["can_accept"] is False and any("Resolve contradiction first" in r for r in blocked["accept_blockers"])

    good = _make_supported_claim(pid, text="Bulk good")
    bare = _make_unsupported_claim(pid)
    r = admin.post(
        f"/api/projects/{pid}/review/bulk",
        json={"claim_ids": [good, bare, blocked["id"], "CLM-DOESNOTEXIST"], "note": "Bulk review"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == [good]
    reasons = {s["claim_id"]: s["reason"] for s in body["skipped"]}
    assert "No valid evidence" in reasons[bare]
    assert "Resolve contradiction first" in reasons[blocked["id"]]
    assert "not found" in reasons["CLM-DOESNOTEXIST"].lower()
    assert admin.get(f"/api/claims/{good}").json()["verification_status"] == "verified"
    assert admin.get(f"/api/claims/{blocked['id']}").json()["verification_status"] != "verified"
    again = admin.post(f"/api/projects/{pid}/review/bulk", json={"claim_ids": [good]}).json()
    assert again["accepted"] == [] and "Already accepted" in again["skipped"][0]["reason"]


# â”€â”€ Isolation and clearance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_other_workspace_gets_404_everywhere(client):
    admin, ws_id, pid = _project()
    admin.post(f"/api/projects/{pid}/interview/generate")
    qid = _questions(admin, pid)["questions"][0]["id"]
    cid = _claims(admin, pid)[0]["id"]
    outsider = make_user(f"p6_out_{os.urandom(3).hex()}@example.com", "Outsider")
    checks = [
        outsider.get(f"/api/projects/{pid}/interview"),
        outsider.post(f"/api/projects/{pid}/interview/generate"),
        outsider.post(f"/api/interview/questions/{qid}/answer", json={"answer": "x"}),
        outsider.post(f"/api/interview/questions/{qid}/skip", json={"reason": "x"}),
        outsider.get(f"/api/claims/{cid}/history"),
        outsider.post(f"/api/claims/{cid}/review", json={"action": "accept"}),
        outsider.get(f"/api/projects/{pid}/review/queue"),
        outsider.post(f"/api/projects/{pid}/review/bulk", json={"claim_ids": [cid]}),
    ]
    assert [r.status_code for r in checks] == [404] * len(checks)


def test_restricted_claims_and_questions_hidden_from_non_admin(client):
    admin, ws_id, pid = _project(restricted=True)
    admin.post(f"/api/projects/{pid}/interview/generate")
    member = join_as(admin, ws_id, f"p6_tm2_{os.urandom(3).hex()}@example.com", "team_member")
    departing = join_as(admin, ws_id, f"p6_dep2_{os.urandom(3).hex()}@example.com", "departing")

    all_claims = _claims(admin, pid)
    restricted_ids = {c["id"] for c in all_claims if c["clearance_level"] == "restricted"}
    assert restricted_ids
    admin_queue_ids = {i["id"] for i in admin.get(f"/api/projects/{pid}/review/queue?scope=all").json()["items"]}
    assert restricted_ids <= admin_queue_ids
    member_queue_ids = {i["id"] for i in member.get(f"/api/projects/{pid}/review/queue?scope=all").json()["items"]}
    assert not (restricted_ids & member_queue_ids)
    rid = next(iter(restricted_ids))
    assert member.post(f"/api/claims/{rid}/review", json={"action": "flag", "note": "x"}).status_code == 404

    admin_qs = _questions(admin, pid)["questions"]
    restricted_qs = [q for q in admin_qs if q["clearance_level"] == "restricted"]
    assert restricted_qs
    for who in (member, departing):
        visible = {q["id"] for q in _questions(who, pid)["questions"]}
        assert not (visible & {q["id"] for q in restricted_qs})
        assert who.post(f"/api/interview/questions/{restricted_qs[0]['id']}/answer", json={"answer": "x"}).status_code == 404


# â”€â”€ Overview counts, LLM guard, Atlas, migrations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_summary_counts_come_from_the_database(client):
    admin, ws_id, pid = _project()
    s0 = admin.get(f"/api/projects/{pid}/summary").json()
    assert s0["total_question_count"] == 0 and s0["reviewed_claim_count"] == 0
    admin.post(f"/api/projects/{pid}/interview/generate")
    qs = _questions(admin, pid)["questions"]
    admin.post(f"/api/interview/questions/{qs[0]['id']}/answer", json={"answer": "An answer."})
    cid = _make_supported_claim(pid)
    admin.post(f"/api/claims/{cid}/review", json={"action": "accept"})
    s = admin.get(f"/api/projects/{pid}/summary").json()
    assert s["total_question_count"] == len(qs)
    assert s["answered_question_count"] == 1
    assert s["open_question_count"] == len(qs) - 1
    assert s["reviewed_claim_count"] == 1
    db = TestingSession()
    try:
        assert db.query(Claim).filter(Claim.project_id == pid).count() == s["claim_count"]
        assert db.query(Contradiction).filter(Contradiction.project_id == pid, Contradiction.status == "open").count() == s["open_contradiction_count"]
    finally:
        db.close()


def test_llm_rephrase_cannot_add_facts(client):
    template = "Who owns billing? tasks.csv names Ann Lee, notes.md names Bo Chan."
    values = ["billing", "Ann Lee", "Bo Chan", "tasks.csv", "notes.md"]
    good = rephrase(template, values, caller=lambda p: "Could you tell us who owns billing? tasks.csv names Ann Lee and notes.md names Bo Chan.")
    assert good and "Ann Lee" in good
    assert rephrase(template, values, caller=lambda p: "Who owns billing? tasks.csv names Ann Lee.") is None  # dropped a fact
    assert rephrase(template, values, caller=lambda p: "Who owns billing? Ann Lee since 2019, Bo Chan.") is None  # new number
    def boom(prompt):
        raise RuntimeError("network down")
    assert rephrase(template, values, caller=boom) is None

    admin, ws_id, pid = _project()
    from app.engine.interview.service import generate_questions
    from app.models import Project
    db = TestingSession()
    try:
        generate_questions(db, db.get(Project, pid), llm_caller=boom)
        assert {q.text_source for q in db.query(InterviewQuestion).filter(InterviewQuestion.project_id == pid)} == {"template"}
    finally:
        db.close()


def test_atlas_sample_generates_questions_too(client):
    admin = make_user(f"p6_atlas_{os.urandom(3).hex()}@example.com", "Atlas Lead")
    _, pid = make_project(admin, "Atlas Sample")
    assert admin.post(f"/api/projects/{pid}/sample").status_code == 201
    admin.post(f"/api/projects/{pid}/analyze")
    g = admin.post(f"/api/projects/{pid}/interview/generate").json()
    assert g["created"] > 0
    qs = _questions(admin, pid)["questions"]
    assert any(q["gap_type"] == "conflicting_ownership" for q in qs)
    import re
    assert all(not re.search(r"\{[a-z_]+\}", q["question"]) for q in qs)


def test_alembic_upgrades_fresh_database_and_round_trips(tmp_path):
    backend = Path(__file__).resolve().parent.parent
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"}

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=backend, env=env, capture_output=True, text=True
        )

    assert run("upgrade", "head").returncode == 0
    cur = run("current")
    assert "(head)" in cur.stdout + cur.stderr
    assert run("downgrade", "-1").returncode == 0
    assert run("upgrade", "head").returncode == 0
    import sqlite3
    con = sqlite3.connect(tmp_path / "fresh.db")
    cols = {r[1] for r in con.execute("pragma table_info(interview_questions)")}
    assert {"fingerprint", "status", "gap_type", "contradiction_id"} <= cols
    ev_cols = {r[1]: r[3] for r in con.execute("pragma table_info(claim_evidence)")}
    assert ev_cols["source_id"] == 0 and "evidence_type" in ev_cols  # source_id nullable
    con.close()
