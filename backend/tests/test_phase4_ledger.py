"""Phase 4 tests: Evidence Ledger, citation validation, excerpt highlighting & tamper detection."""

from app.models import Claim, ClaimEvidence
from tests.conftest import TestingSession, join_as, make_project, make_user


def _upload(client, pid: str, filename: str, content: bytes, clearance: str = "team"):
    r = client.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": (filename, content)},
        data={"clearance_level": clearance},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_evidence_ledger_citations_and_drawer_highlight(client):
    admin = make_user("p4_admin@example.com", "Admin")
    _, pid = make_project(admin, "Ledger Project")

    _upload(
        admin,
        pid,
        "tasks.csv",
        b"id,title,assignee,status,module,updated,depends_on\n"
        b"LDG-1,Implement audit trail,Kiran Rao,Done,audit,2026-10-15,\n",
    )
    _upload(
        admin,
        pid,
        "notes.md",
        b"# Audit Sync\nDate: 2026-10-16\n"
        b"Context paragraph before the decision.\n"
        b"- We decided to retain audit logs for 365 days in the audit module.\n"
        b"Trailing paragraph after the decision.\n",
    )

    admin.post(f"/api/projects/{pid}/analyze")

    # 1. Validation endpoint confirms 0 invalid citations
    val = admin.get(f"/api/projects/{pid}/ledger/validation").json()
    assert val["invalid_citation_count"] == 0
    assert val["total_claims"] >= 2
    assert val["valid_citations"] == val["total_citations"]

    # 2. Every claim has CLM-xxx ID and clickable evidence with exact highlighted slice in chunk_text
    claims = admin.get(f"/api/projects/{pid}/claims").json()
    assert len(claims) >= 2
    for c in claims:
        assert c["id"].startswith("CLM-")
        assert c["origin_label"] == "rule-extracted"
        detail = admin.get(f"/api/claims/{c['id']}").json()
        assert len(detail["evidence"]) >= 1
        for ev in detail["evidence"]:
            assert ev["chunk_text"] is not None
            assert ev["excerpt"] in ev["chunk_text"]
            start = ev["highlight_start"]
            end = ev["highlight_end"]
            assert start is not None and end is not None
            assert ev["chunk_text"][start:end] == ev["excerpt"]

    # 3. Filter parameters work (type, module, status, owner, review_status, q)
    dec_only = admin.get(f"/api/projects/{pid}/claims?type=decision&module=audit&q=365").json()
    assert len(dec_only) == 1
    assert dec_only[0]["claim_type"] == "decision"

    owner_filtered = admin.get(f"/api/projects/{pid}/claims?owner=Kiran").json()
    assert len(owner_filtered) >= 1
    assert all("Kiran" in (c["owner_name"] or "") for c in owner_filtered)


def test_citation_validation_catches_tampered_excerpt_and_downgrades_verified(client):
    admin = make_user("p4_tamper@example.com", "Admin")
    _, pid = make_project(admin, "Tamper Check Project")

    _upload(
        admin,
        pid,
        "tasks.csv",
        b"id,title,assignee,status,module,updated,depends_on\n"
        b"TMP-1,Configure TLS certificates,Meera,Done,security,2026-10-10,\n",
    )
    admin.post(f"/api/projects/{pid}/analyze")

    claims = admin.get(f"/api/projects/{pid}/claims?type=task_status").json()
    assert len(claims) == 1
    cid = claims[0]["id"]
    assert claims[0]["verification_status"] == "verified"

    # Tamper with the stored evidence excerpt in the DB so it no longer matches the chunk text
    db = TestingSession()
    ev = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == cid).first()
    assert ev is not None
    ev.excerpt = "FABRICATED EXCERPT THAT DOES NOT APPEAR IN CHUNK"
    db.commit()
    db.close()

    val = admin.get(f"/api/projects/{pid}/ledger/validation").json()
    assert val["invalid_citation_count"] == 1
    assert val["invalid_citations"][0]["claim_id"] == cid
    assert cid in val["downgraded_claim_ids"]

    # Claim with no valid evidence is downgraded from 'verified' to 'missing'
    updated_claim = admin.get(f"/api/claims/{cid}").json()
    assert updated_claim["verification_status"] == "missing"


def test_ledger_validation_clearance_and_isolation(client):
    admin = make_user("p4_sec@example.com", "Admin")
    ws_id, pid = make_project(admin, "Ledger Clearance")
    incoming = join_as(admin, ws_id, "p4_inc@example.com", "incoming")
    outsider = make_user("p4_out@example.com", "Outsider")

    _upload(admin, pid, "team.md", b"# Team\nDate: 2026-10-01\n- We decided to use pytest.\n", clearance="team")
    _upload(admin, pid, "secret.md", b"# Secret\nDate: 2026-10-02\n- We decided to rotate root keys.\n", clearance="restricted")
    admin.post(f"/api/projects/{pid}/analyze")

    v_admin = admin.get(f"/api/projects/{pid}/ledger/validation").json()
    v_inc = incoming.get(f"/api/projects/{pid}/ledger/validation").json()
    assert v_admin["total_claims"] > v_inc["total_claims"]
    assert outsider.get(f"/api/projects/{pid}/ledger/validation").status_code == 404
