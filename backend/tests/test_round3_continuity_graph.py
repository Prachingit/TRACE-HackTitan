"""Round 3, Improvement C: Continuity Graph & Custody Checklist (No Secrets) tests."""

import pytest
from app.models import CustodyEvent
from tests.conftest import TestingSession, join_as, make_project, make_user


def _up(client, pid: str, filename: str, data: bytes, clearance: str = "team"):
    return client.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": (filename, data, "text/plain")},
        data={"clearance_level": clearance},
    )


def test_continuity_graph_risks_impact_clearance_and_handover_section(client):
    admin = make_user("cg_admin@example.com", "Lead Admin")
    ws_id, pid = make_project(admin, "Kestrel Gateway")
    inc = join_as(admin, ws_id, "cg_inc@example.com", "incoming")
    dep = join_as(admin, ws_id, "cg_dep@example.com", "departing")
    outsider = make_user("cg_out@example.com", "Outsider")

    # Empty graph state before any sources
    empty_g = admin.get(f"/api/projects/{pid}/graph")
    assert empty_g.status_code == 200
    assert empty_g.json()["nodes"] == []
    assert empty_g.json()["edges"] == []

    # Non-Atlas CSV with dependency cycle + sole owner + service mention + restricted note
    csv_bytes = (
        b"task_id,title,module,status,assignee,depends_on,updated\n"
        b"KG-1,Edge router config,routing,In Progress,Meera Patel,KG-2,2026-11-01\n"
        b"KG-2,TLS terminator,routing,In Progress,Meera Patel,KG-1,2026-11-01\n"
        b"KG-3,Rate limiter Redis store,ratelimit,Pending,None,KG-1,2026-11-01\n"
    )
    md_bytes = (
        b"# Kestrel Gateway Notes\n\n"
        b"Owner: Meera Patel will handle routing and Render deployment.\n"
    )
    res_bytes = (
        b"# Restricted KMS\n\n"
        b"Owner: Security Bot handles vault_keys via AWS KMS.\n"
    )
    assert _up(admin, pid, "tasks.csv", csv_bytes, "team").status_code == 201
    assert _up(admin, pid, "gateway.md", md_bytes, "team").status_code == 201
    assert _up(admin, pid, "vault.md", res_bytes, "restricted").status_code == 201

    assert admin.post(f"/api/projects/{pid}/analyze").status_code == 202

    # Idempotent rebuild
    rb1 = admin.post(f"/api/projects/{pid}/graph/rebuild")
    assert rb1.status_code == 200
    rb2 = admin.post(f"/api/projects/{pid}/graph/rebuild")
    assert rb2.status_code == 200
    assert rb1.json() == rb2.json()

    # Every edge has claim_ids and evidence_refs
    g_adm = admin.get(f"/api/projects/{pid}/graph").json()
    assert len(g_adm["nodes"]) > 0
    assert len(g_adm["edges"]) > 0
    for e in g_adm["edges"]:
        assert len(e["claim_ids"]) >= 1
        assert len(e["evidence_refs"]) >= 1

    # Risks: single point of failure (Meera Patel on routing), cycle (KG-1 <-> KG-2), unowned (ratelimit)
    risks = admin.get(f"/api/projects/{pid}/graph/risks").json()
    assert any(s["module"] == "routing" and s["sole_owner"] == "Meera Patel" for s in risks["single_points_of_failure"])
    assert len(risks["circular_dependencies"]) >= 1
    assert any(m["module"] == "ratelimit" for m in risks["unowned_modules"])

    # What breaks if Meera Patel leaves: ranked by downstream dependents
    imp = admin.get(f"/api/projects/{pid}/graph/impact?person_id=Meera%20Patel").json()
    assert imp["person"]["label"] == "Meera Patel"
    assert len(imp["impacted"]) >= 1
    counts = [x["downstream_dependents"] for x in imp["impacted"]]
    assert counts == sorted(counts, reverse=True)

    # Incoming sees NO edges/nodes before approval
    g_inc_before = inc.get(f"/api/projects/{pid}/graph").json()
    assert g_inc_before["edges"] == []

    # Approve ONLY non-restricted claims
    claims = admin.get(f"/api/projects/{pid}/claims").json()
    for c in claims:
        if c["clearance_level"] != "restricted":
            admin.post(
                f"/api/claims/{c['id']}/review",
                json={"action": "accept", "resolve_contradictions": True, "note": "Approved."},
            )

    # Incoming now sees approved non-restricted edges, NEVER restricted nodes/edges
    g_inc_after = inc.get(f"/api/projects/{pid}/graph").json()
    assert len(g_inc_after["edges"]) >= 1
    assert all(e["clearance_level"] != "restricted" for e in g_inc_after["edges"])
    assert all(n["clearance_level"] != "restricted" for n in g_inc_after["nodes"])
    assert dep.get(f"/api/projects/{pid}/graph").status_code == 200
    assert all(n["clearance_level"] != "restricted" for n in dep.get(f"/api/projects/{pid}/graph").json()["nodes"])

    # Handover includes 11. Continuity and custody section
    h = admin.post(f"/api/projects/{pid}/handovers", json={"title": "Kestrel Handover"}).json()
    sec_keys = [s["section_key"] for s in h["sections"]]
    assert "continuity_custody" in sec_keys

    # Workspace isolation
    assert outsider.get(f"/api/projects/{pid}/graph").status_code == 404
    assert outsider.post(f"/api/projects/{pid}/graph/rebuild").status_code == 404
    assert outsider.get(f"/api/projects/{pid}/custody").status_code == 404


def test_custody_secret_validator_and_append_only_audit(client):
    admin = make_user("sec_admin@example.com", "Admin")
    ws_id, pid = make_project(admin, "Vault Check")
    inc = join_as(admin, ws_id, "sec_inc@example.com", "incoming")

    # Every secret pattern must be rejected with 400 and clear message
    bad_payloads = [
        {"kind": "cloud account", "name": "Prod AWS", "notes": "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."},
        {"kind": "cloud account", "name": "Prod AWS", "where_to_request_access": "Use AKIAIOSFODNN7EXAMPLE12"},
        {"kind": "repository", "name": "GitHub", "notes": "token ghp_abcdefghijklmnopqrstuvwxyz123456"},
        {"kind": "third-party API", "name": "OpenAI", "notes": "key sk-proj-abcdefghijklmnopqrstuvwxyz1234"},
        {"kind": "database", "name": "Postgres", "where_to_request_access": "password=mySuperSecretValue123"},
        {"kind": "database", "name": "Neon", "notes": "postgres://appuser:s3cr3tpass@db.example.com/prod"},
        {"kind": "other", "name": "Webhook", "notes": "aB9$kL2mP8qR5tV1wX4zY7cN0jF3hG6d"},
    ]
    for payload in bad_payloads:
        res = admin.post(f"/api/projects/{pid}/custody", json=payload)
        assert res.status_code == 400, f"Expected 400 for {payload}, got {res.status_code}"
        assert "do not store credentials" in res.json()["detail"].lower()

    # Normal plain-text instructions succeed
    ok = admin.post(
        f"/api/projects/{pid}/custody",
        json={
            "kind": "hosting",
            "name": "Render Web Service",
            "owner_person": "Meera Patel",
            "backup_owner": "Alex Chen",
            "where_to_request_access": "Ask Meera Patel to add your email as workspace member in Render.",
            "notes": "Two-factor auth required.",
        },
    )
    assert ok.status_code == 201, ok.text
    cid = ok.json()["id"]
    assert ok.json()["status"] == "unconfirmed"

    # Incoming does NOT see unconfirmed custody item
    assert inc.get(f"/api/projects/{pid}/custody").json() == []

    # Secret check also enforced on PATCH
    bad_patch = admin.patch(f"/api/custody/{cid}", json={"notes": "sk-1234567890abcdef1234567890abcdef"})
    assert bad_patch.status_code == 400

    # Confirm and mark transferred -> writes append-only CustodyEvents; incoming now sees it
    assert admin.post(f"/api/custody/{cid}/confirm", json={"status": "confirmed"}).status_code == 200
    assert admin.post(f"/api/custody/{cid}/confirm", json={"status": "transferred", "note": "Added incoming admin."}).status_code == 200
    assert len(inc.get(f"/api/projects/{pid}/custody").json()) == 1

    hist = admin.get(f"/api/custody/{cid}/history").json()
    assert len(hist) == 3
    assert {e["action"] for e in hist} == {"created", "confirmed", "transferred"}

    # Append-only ORM guard blocks modifying CustodyEvent rows
    db = TestingSession()
    try:
        ev = db.query(CustodyEvent).filter(CustodyEvent.custody_item_id == cid).first()
        ev.action = "tampered"
        with pytest.raises(ValueError, match="append-only"):
            db.commit()
        db.rollback()
    finally:
        db.close()
