"""Phase 5 tests: Contradiction Radar rules, resolution workflow, clearance and isolation."""

from datetime import datetime, timezone

from app.engine.rules import (
    conflicting_ownership,
    conflicting_status,
    missing_test_evidence,
    stale_activity,
    status_without_evidence,
    unassigned_responsibility,
    undocumented_work,
    unresolved_dependency,
)
from app.engine.rules.base import RuleClaim
from app.engine.types import SourceInfo
from tests.conftest import join_as, make_project, make_user


def _claim(
    cid: str,
    claim_type: str,
    title: str = "Claim",
    text: str = "Claim text",
    module: str = "billing",
    owner: str | None = "Alice",
    verification_status: str = "verified",
    review_status: str = "unreviewed",
    clearance_level: str = "team",
    event_time: datetime | None = None,
    task_key: str | None = None,
    attrs: dict | None = None,
    source_ids: list[str] | None = None,
    source_types: set[str] | None = None,
) -> RuleClaim:
    return RuleClaim(
        id=cid,
        claim_type=claim_type,
        title=title,
        text=text,
        module=module,
        owner=owner,
        verification_status=verification_status,
        review_status=review_status,
        clearance_level=clearance_level,
        event_time=event_time,
        task_key=task_key,
        attrs=attrs or {},
        source_ids=source_ids or ["SRC-1"],
        source_types=source_types or {"csv"},
    )


def _upload(client, pid: str, filename: str, content: bytes, clearance: str = "team"):
    r = client.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": (filename, content)},
        data={"clearance_level": clearance},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── 1. Unit tests per rule (firing + non-firing fixtures) ────────────────────

def test_rule_status_without_evidence():
    sources = {
        "SRC-1": SourceInfo("SRC-1", "tasks.csv", "csv", "team"),
        "SRC-2": SourceInfo("SRC-2", "commits.json", "github_commits", "team"),
    }
    # Fires: completed task in 'billing' with no contribution or doc decision in 'billing'
    c_done = _claim(
        "CLM-1",
        "task_status",
        title="B-10: Invoice PDF export",
        module="billing",
        task_key="B-10",
        attrs={"status": "completed", "task_id": "B-10"},
    )
    findings = status_without_evidence.evaluate([c_done], sources)
    assert len(findings) == 1
    assert findings[0].rule_code == "STATUS_WITHOUT_EVIDENCE"
    assert "CLM-1" in findings[0].mark_conflicting_claim_ids

    # Does NOT fire when a contribution exists in the same module
    c_commit = _claim(
        "CLM-2",
        "contribution",
        title="Commit abc1234: Add invoice PDF generator",
        module="billing",
        task_key="B-10",
        source_ids=["SRC-2"],
        source_types={"github_commits"},
    )
    assert status_without_evidence.evaluate([c_done, c_commit], sources) == []


def test_rule_conflicting_status():
    sources = {
        "SRC-1": SourceInfo("SRC-1", "tasks.csv", "csv", "team"),
        "SRC-2": SourceInfo("SRC-2", "notes.md", "markdown", "team"),
    }
    # Fires: task completed in SRC-1 while testing is pending in SRC-2 for same module
    c_done = _claim(
        "CLM-1",
        "task_status",
        title="B-11: Tax calculation",
        module="billing",
        task_key="B-11",
        attrs={"status": "completed"},
        source_ids=["SRC-1"],
    )
    c_pending_test = _claim(
        "CLM-2",
        "testing",
        title="Pending testing in billing",
        text="Tax calculation validation is still pending",
        module="billing",
        attrs={"testing_status": "pending"},
        source_ids=["SRC-2"],
        source_types={"markdown"},
    )
    findings = conflicting_status.evaluate([c_done, c_pending_test], sources)
    assert len(findings) == 1
    assert findings[0].rule_code == "CONFLICTING_STATUS"
    assert set(findings[0].claim_ids) == {"CLM-1", "CLM-2"}

    # Does NOT fire when testing is present/complete and task is completed
    c_present_test = _claim(
        "CLM-3",
        "testing",
        title="Testing evidence in billing",
        text="Unit tests added and passing for tax calculation",
        module="billing",
        attrs={"testing_status": "present"},
        source_ids=["SRC-2"],
        source_types={"markdown"},
    )
    assert conflicting_status.evaluate([c_done, c_present_test], sources) == []


def test_rule_conflicting_ownership():
    sources = {
        "SRC-1": SourceInfo("SRC-1", "tasks.csv", "csv", "team"),
        "SRC-2": SourceInfo("SRC-2", "arch.md", "markdown", "team"),
    }
    # Fires: explicit module owner in arch.md is Bob, while task owner in tasks.csv is Alice
    c_task = _claim(
        "CLM-1",
        "task_status",
        title="B-12: Stripe webhook",
        module="billing",
        owner="Alice",
        attrs={"status": "in_progress"},
        source_ids=["SRC-1"],
    )
    c_own = _claim(
        "CLM-2",
        "ownership",
        title="Ownership of billing: Bob",
        module="billing",
        owner="Bob",
        attrs={"scope": "module"},
        source_ids=["SRC-2"],
        source_types={"markdown"},
    )
    findings = conflicting_ownership.evaluate([c_task, c_own], sources)
    assert len(findings) == 1
    assert findings[0].rule_code == "CONFLICTING_OWNERSHIP"

    # Does NOT fire when both sources agree on Alice
    c_own_same = _claim(
        "CLM-3",
        "ownership",
        title="Ownership of billing: Alice",
        module="billing",
        owner="Alice",
        attrs={"scope": "module"},
        source_ids=["SRC-2"],
        source_types={"markdown"},
    )
    assert conflicting_ownership.evaluate([c_task, c_own_same], sources) == []


def test_rule_unresolved_dependency():
    sources = {"SRC-1": SourceInfo("SRC-1", "tasks.csv", "csv", "team")}
    # Fires: B-20 (completed) depends on B-19 (in_progress)
    c_prereq = _claim(
        "CLM-1",
        "task_status",
        title="B-19: Base schema",
        module="billing",
        task_key="B-19",
        attrs={"task_id": "B-19", "status": "in_progress"},
    )
    c_dep_task = _claim(
        "CLM-2",
        "task_status",
        title="B-20: API endpoint",
        module="billing",
        task_key="B-20",
        attrs={"task_id": "B-20", "status": "completed"},
    )
    c_dep = _claim(
        "CLM-3",
        "dependency",
        title="B-20 depends on B-19",
        module="billing",
        task_key="B-20",
        attrs={"from_task": "B-20", "depends_on": "B-19"},
    )
    findings = unresolved_dependency.evaluate([c_prereq, c_dep_task, c_dep], sources)
    assert len(findings) == 1
    assert findings[0].rule_code == "UNRESOLVED_DEPENDENCY"

    # Does NOT fire when B-19 is completed
    c_prereq_done = _claim(
        "CLM-1",
        "task_status",
        title="B-19: Base schema",
        module="billing",
        task_key="B-19",
        attrs={"task_id": "B-19", "status": "completed"},
    )
    assert unresolved_dependency.evaluate([c_prereq_done, c_dep_task, c_dep], sources) == []


def test_rule_stale_activity():
    sources = {"SRC-1": SourceInfo("SRC-1", "tasks.csv", "csv", "team")}
    t_old = datetime(2026, 9, 1, tzinfo=timezone.utc)
    t_recent = datetime(2026, 11, 1, tzinfo=timezone.utc)

    # Fires: in-progress task last updated 61 days before latest project event (threshold 28)
    c_stale = _claim(
        "CLM-1",
        "task_status",
        title="B-30: Legacy migration",
        module="billing",
        task_key="B-30",
        event_time=t_old,
        attrs={"status": "in_progress"},
    )
    c_recent = _claim(
        "CLM-2",
        "contribution",
        title="Recent commit",
        module="search",
        task_key="S-01",
        event_time=t_recent,
    )
    findings = stale_activity.evaluate([c_stale, c_recent], sources, stale_days=28)
    assert len(findings) == 1
    assert findings[0].rule_code == "STALE_ACTIVITY"

    # Does NOT fire when in-progress task has recent activity within threshold
    c_fresh = _claim(
        "CLM-3",
        "task_status",
        title="B-31: Active work",
        module="billing",
        task_key="B-31",
        event_time=datetime(2026, 10, 20, tzinfo=timezone.utc),
        attrs={"status": "in_progress"},
    )
    assert stale_activity.evaluate([c_fresh, c_recent], sources, stale_days=28) == []


def test_rule_undocumented_work():
    sources = {"SRC-1": SourceInfo("SRC-1", "commits.json", "github_commits", "team")}
    # Fires: >= 2 contributions in 'search' with no docs or decision claims
    c1 = _claim(
        "CLM-1",
        "contribution",
        title="Commit 1 in search",
        module="search",
        source_types={"github_commits"},
    )
    c2 = _claim(
        "CLM-2",
        "contribution",
        title="Commit 2 in search",
        module="search",
        source_types={"github_commits"},
    )
    findings = undocumented_work.evaluate([c1, c2], sources)
    assert len(findings) == 1
    assert findings[0].rule_code == "UNDOCUMENTED_WORK"

    # Does NOT fire when a decision claim or markdown doc claim exists for 'search'
    c_doc = _claim(
        "CLM-3",
        "decision",
        title="Decision in search",
        text="We decided to use Postgres trigram indexes for search.",
        module="search",
        source_types={"markdown"},
    )
    assert undocumented_work.evaluate([c1, c2, c_doc], sources) == []


def test_rule_unassigned_responsibility():
    sources = {"SRC-1": SourceInfo("SRC-1", "tasks.csv", "csv", "team")}
    # Fires: task has owner=None
    c_unassigned = _claim(
        "CLM-1",
        "task_status",
        title="B-40: Backup verification",
        module="ops",
        owner=None,
        attrs={"status": "pending", "unassigned": True},
    )
    findings = unassigned_responsibility.evaluate([c_unassigned], sources)
    assert len(findings) >= 1
    assert findings[0].rule_code == "UNASSIGNED_RESPONSIBILITY"

    # Does NOT fire when task and module have a valid owner
    c_assigned = _claim(
        "CLM-2",
        "task_status",
        title="B-40: Backup verification",
        module="ops",
        owner="Dana",
        attrs={"status": "pending", "unassigned": False},
    )
    assert unassigned_responsibility.evaluate([c_assigned], sources) == []


def test_rule_missing_test_evidence():
    sources = {"SRC-1": SourceInfo("SRC-1", "commits.json", "github_commits", "team")}
    # Fires: implementation claim in 'billing' with no testing claim
    c_impl = _claim(
        "CLM-1",
        "contribution",
        title="Commit in billing",
        module="billing",
        source_types={"github_commits"},
    )
    findings = missing_test_evidence.evaluate([c_impl], sources)
    assert len(findings) == 1
    assert findings[0].rule_code == "MISSING_TEST_EVIDENCE"

    # Does NOT fire when positive testing evidence exists in 'billing'
    c_test_ok = _claim(
        "CLM-2",
        "testing",
        title="Tests passing in billing",
        module="billing",
        attrs={"testing_status": "present"},
        source_types={"github_commits"},
    )
    assert missing_test_evidence.evaluate([c_impl, c_test_ok], sources) == []


# ── 2. End-to-End Non-Atlas Project Contradiction Radar + Resolution ─────────

def test_non_atlas_contradiction_radar_and_manual_resolution(client):
    admin = make_user("radar-non-atlas@example.com", "Nora")
    ws_id, pid = make_project(admin, "Radar Project")

    # Upload custom non-Atlas CSV with:
    # - INV-1: marked Done in 'invoicing' (no commits -> STATUS_WITHOUT_EVIDENCE, depends on INV-2 which is In Progress -> UNRESOLVED_DEPENDENCY)
    # - INV-2: In Progress, updated 2026-08-01 (stale -> STALE_ACTIVITY), assigned to 'Liam'
    # - INV-3: Pending, unassigned ('None' -> UNASSIGNED_RESPONSIBILITY)
    csv_text = (
        b"task_id,title,module,status,assignee,depends_on,updated\n"
        b"INV-1,Generate PDF invoices,invoicing,Done,Liam,INV-2,2026-10-25\n"
        b"INV-2,Currency rounding rules,invoicing,In Progress,Liam,,2026-08-01\n"
        b"INV-3,Archive old receipts,archival,Todo,None,,2026-10-26\n"
    )
    # Upload markdown notes that conflict on invoicing owner (Maya vs Liam) and state invoicing tests are pending
    md_text = (
        b"# Invoicing Notes (2026-10-28)\n"
        b"Owner: Maya Lin will handle invoicing module architecture.\n"
        b"Pending testing for invoicing PDF export before production release.\n"
    )
    # Upload restricted note that introduces a restricted blocker on archival
    restricted_md = (
        b"# Confidential Archival Audit (2026-10-29)\n"
        b"Archival module is blocked by legal retention sign-off.\n"
    )

    _upload(admin, pid, "tracker.csv", csv_text, clearance="team")
    _upload(admin, pid, "notes.md", md_text, clearance="team")
    _upload(admin, pid, "restricted_audit.md", restricted_md, clearance="restricted")

    # Run analysis
    run_res = admin.post(f"/api/projects/{pid}/analyze")
    assert run_res.status_code == 202
    latest = admin.get(f"/api/projects/{pid}/runs/latest").json()
    assert latest["status"] == "completed"

    # List contradictions as admin
    ctrs = admin.get(f"/api/projects/{pid}/contradictions").json()
    rule_codes = {c["rule_code"] for c in ctrs}
    assert "STATUS_WITHOUT_EVIDENCE" in rule_codes
    assert "CONFLICTING_STATUS" in rule_codes
    assert "CONFLICTING_OWNERSHIP" in rule_codes
    assert "UNRESOLVED_DEPENDENCY" in rule_codes
    assert "STALE_ACTIVITY" in rule_codes
    assert "UNASSIGNED_RESPONSIBILITY" in rule_codes
    assert "MISSING_TEST_EVIDENCE" in rule_codes

    # Verify INV-1 claim is marked 'conflicting' and NOT 'verified'
    claims = admin.get(f"/api/projects/{pid}/claims").json()
    inv1_claims = [c for c in claims if c["task_key"] == "INV-1" and c["claim_type"] == "task_status"]
    assert len(inv1_claims) == 1
    assert inv1_claims[0]["verification_status"] == "conflicting"

    # Test manual resolution requires a non-empty note
    target_ctr = ctrs[0]
    bad_res = admin.post(f"/api/contradictions/{target_ctr['id']}/resolve", json={"note": "   "})
    assert bad_res.status_code == 400

    # Resolve with a real note
    good_res = admin.post(
        f"/api/contradictions/{target_ctr['id']}/resolve",
        json={"note": "Confirmed with Maya and Liam during handover sync."},
    )
    assert good_res.status_code == 200
    resolved_body = good_res.json()
    assert resolved_body["status"] == "resolved"
    assert resolved_body["resolved_by_name"] == "Nora"
    assert resolved_body["resolution_note"] == "Confirmed with Maya and Liam during handover sync."
    assert resolved_body["resolved_at"] is not None

    # Resolving a contradiction must NOT silently flip involved claims to 'verified'
    for clm in resolved_body["claims"]:
        assert clm["verification_status"] != "verified" or clm["review_status"] != "unreviewed"

    # Re-running analysis must NOT auto-resolve open contradictions and must preserve resolved ones
    rerun_res = admin.post(f"/api/projects/{pid}/analyze")
    assert rerun_res.status_code == 202
    after_rerun = admin.get(f"/api/contradictions/{target_ctr['id']}").json()
    assert after_rerun["status"] == "resolved"
    assert after_rerun["resolution_note"] == "Confirmed with Maya and Liam during handover sync."

    # Verify clearance enforcement: invite an 'incoming' member and confirm restricted contradictions are hidden
    incoming = join_as(admin, ws_id, "incoming-radar@example.com", "incoming")
    inc_ctrs = incoming.get(f"/api/projects/{pid}/contradictions").json()
    assert all(c["clearance_level"] != "restricted" for c in inc_ctrs)

    restricted_ctrs = [c for c in ctrs if c["clearance_level"] == "restricted"]
    assert len(restricted_ctrs) >= 1
    r_id = restricted_ctrs[0]["id"]
    assert incoming.get(f"/api/contradictions/{r_id}").status_code == 404
    assert incoming.post(f"/api/contradictions/{r_id}/resolve", json={"note": "Attempt"}).status_code == 404

    # Verify tenant isolation: another workspace user gets 404
    outsider = make_user("outsider-radar@example.com", "Outsider")
    assert outsider.get(f"/api/projects/{pid}/contradictions").status_code == 404
    assert outsider.get(f"/api/contradictions/{target_ctr['id']}").status_code == 404
    assert outsider.post(f"/api/contradictions/{target_ctr['id']}/resolve", json={"note": "Hack"}).status_code == 404


# ── 3. End-to-End Atlas Sample Contradiction Verification ───────────────────

def test_atlas_sample_planted_contradictions(client):
    admin = make_user("atlas-radar@example.com", "Atlas Admin")
    _, pid = make_project(admin, "Atlas Sample Project")

    # Load Atlas sample into project
    sample_res = admin.post(f"/api/projects/{pid}/sample")
    assert sample_res.status_code == 201

    # Run analysis
    run_res = admin.post(f"/api/projects/{pid}/analyze")
    assert run_res.status_code == 202
    latest = admin.get(f"/api/projects/{pid}/runs/latest").json()
    assert latest["status"] == "completed"
    assert latest["summary"]["invalid_citation_count"] == 0

    ctrs = admin.get(f"/api/projects/{pid}/contradictions").json()
    by_rule = {}
    for c in ctrs:
        by_rule.setdefault(c["rule_code"], []).append(c)

    # Planted case 1: TSK-008 Payment gateway integration marked Done with zero commits in payments
    assert "STATUS_WITHOUT_EVIDENCE" in by_rule
    assert any("TSK-008" in c["reason"] or "payments" in c["reason"] for c in by_rule["STATUS_WITHOUT_EVIDENCE"])

    # Planted case 2: Conflicting ownership on payments (Rahul Verma in tasks.csv vs Ankit Rao in notes/docs)
    assert "CONFLICTING_OWNERSHIP" in by_rule
    assert any("payments" in c["reason"] for c in by_rule["CONFLICTING_OWNERSHIP"])

    # Planted case 3: Conflicting status on auth (Done in CSV vs testing pending in notes/chat) & caching (LRU vs Redis)
    assert "CONFLICTING_STATUS" in by_rule
    reasons_cs = " | ".join(c["reason"] for c in by_rule["CONFLICTING_STATUS"])
    assert "auth" in reasons_cs
    assert "caching" in reasons_cs or "redis" in reasons_cs

    # Planted case 4: Unresolved dependencies (TSK-008 -> TSK-007, TSK-018 -> TSK-015, auth blocker)
    assert "UNRESOLVED_DEPENDENCY" in by_rule

    # Planted case 5: Stale activity on TSK-005 (updated 2026-09-28 vs Nov 2026 latest event)
    assert "STALE_ACTIVITY" in by_rule
    assert any("TSK-005" in c["reason"] for c in by_rule["STALE_ACTIVITY"])

    # Planted case 6: Unassigned responsibility on TSK-010 Database backup
    assert "UNASSIGNED_RESPONSIBILITY" in by_rule
    assert any("TSK-010" in c["reason"] or "Database backup" in c["reason"] for c in by_rule["UNASSIGNED_RESPONSIBILITY"])

    # Planted case 7: Missing test evidence
    assert "MISSING_TEST_EVIDENCE" in by_rule
