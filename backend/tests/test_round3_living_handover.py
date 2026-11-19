"""Round 3, Improvement A: Living Handover tests (non-Atlas fixture)."""

from tests.conftest import join_as, make_project, make_user


def _up(client, pid: str, filename: str, data: bytes, clearance: str = "team"):
    return client.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": (filename, data, "text/plain")},
        data={"clearance_level": clearance},
    )


def test_living_handover_full_flow_non_atlas_and_clearance(client):
    admin = make_user("lh_admin@example.com", "Lead Admin")
    ws_id, pid = make_project(admin, "Zephyr Billing")
    inc = join_as(admin, ws_id, "lh_inc@example.com", "incoming")
    dep = join_as(admin, ws_id, "lh_dep@example.com", "departing")
    outsider = make_user("lh_out@example.com", "Outsider")

    # 1. Upload initial non-Atlas sources (team + restricted)
    v1_md = (
        "# Zephyr Billing Notes\n\n"
        "We decided to use Stripe webhooks for invoice reconciliation because it avoids polling.\n\n"
        "Billing worker is assigned to Priya Nair.\n\n"
        "Legacy CSV export is deprecated and will be removed next sprint.\n"
    ).encode()
    r1 = _up(admin, pid, "billing_notes.md", v1_md, "team")
    assert r1.status_code == 201, r1.text
    src_id = r1.json()["id"]
    assert r1.json()["version_number"] == 1

    r_res = _up(
        admin,
        pid,
        "secret_keys.md",
        b"# Restricted\n\nWe decided to rotate KMS master keys quarterly because of audit policy.\n",
        "restricted",
    )
    assert r_res.status_code == 201
    res_src_id = r_res.json()["id"]

    # Identical re-upload creates NO new version and returns 409
    r_dup = _up(admin, pid, "billing_notes.md", v1_md, "team")
    assert r_dup.status_code == 409
    assert "identical" in r_dup.json()["detail"].lower()

    # Run analysis and approve initial claims
    an1 = admin.post(f"/api/projects/{pid}/analyze")
    assert an1.status_code == 202, an1.text

    claims_v1 = admin.get(f"/api/projects/{pid}/claims").json()
    assert len(claims_v1) >= 2
    for clm in claims_v1:
        rev = admin.post(f"/api/claims/{clm['id']}/review", json={"action": "accept"})
        assert rev.status_code == 200, rev.text

    # Generate, approve, and share Handover v1
    h1 = admin.post(f"/api/projects/{pid}/handovers", json={"title": "Zephyr Handover", "period_label": "Nov 2026"}).json()
    assert h1["version_number"] == 1
    for sec in h1["sections"]:
        p = admin.patch(f"/api/handovers/{h1['id']}/sections/{sec['section_key']}", json={"review_status": "approved"})
        assert p.status_code == 200, p.text
    assert admin.post(f"/api/handovers/{h1['id']}/approve").status_code == 200

    inc_uid = next(m["user_id"] for m in admin.get(f"/api/workspaces/{ws_id}/members").json() if m["role"] == "incoming")
    assert admin.post(f"/api/handovers/{h1['id']}/share", json={"target_user_id": inc_uid}).status_code == 200

    # Approved handover is immutable
    assert admin.patch(
        f"/api/handovers/{h1['id']}/sections/overview",
        json={"content_md": "tamper"},
    ).status_code == 409
    assert admin.post(f"/api/handovers/{h1['id']}/approve").status_code == 409

    # 2. Re-upload modified billing_notes.md (1 modified, 1 removed, 1 added) -> same source_id, v2
    v2_md = (
        "# Zephyr Billing Notes\n\n"
        "We decided to use Adyen webhooks for invoice reconciliation because multi-currency settlement is required.\n\n"
        "Billing worker is assigned to Priya Nair.\n\n"
        "Tax engine integration is blocked by missing VAT configuration.\n"
    ).encode()
    r2 = _up(admin, pid, "billing_notes.md", v2_md, "team")
    assert r2.status_code == 201, r2.text
    assert r2.json()["id"] == src_id
    assert r2.json()["is_new_version"] is True

    # Also update restricted source to test clearance filtering on changes/diffs
    r_res2 = _up(
        admin,
        pid,
        "secret_keys.md",
        b"# Restricted\n\nWe decided to rotate KMS master keys monthly because of stricter audit policy.\n",
        "restricted",
    )
    assert r_res2.status_code == 201

    # Source versions endpoint keeps v1 snapshot chunks readable
    vers = admin.get(f"/api/sources/{src_id}/versions").json()
    assert [v["version_number"] for v in vers["versions"]] == [2, 1]
    v1_texts = [c["text"] for c in vers["versions"][1]["chunks"]]
    assert any("Stripe webhooks" in t for t in v1_texts)

    # Project changes endpoint shows added/removed/modified
    chg = admin.get(f"/api/projects/{pid}/changes").json()
    ctypes = {c["change_type"] for c in chg["changes"] if c["source_id"] == src_id}
    assert {"modified", "removed", "added"}.issubset(ctypes)

    # 3. Stale-claim identification & query filter
    stale_claims = admin.get(f"/api/claims?project_id={pid}&stale=true").json()
    assert len(stale_claims) >= 1
    assert any("Stripe" in c["text"] for c in stale_claims)
    # Unchanged claim ("Priya Nair") must NOT be stale
    priya_claims = [c for c in admin.get(f"/api/projects/{pid}/claims").json() if "Priya Nair" in c["text"]]
    assert priya_claims and all(not c["is_stale"] for c in priya_claims)

    # Review queue puts stale claims FIRST with old vs new excerpt
    rq = admin.get(f"/api/projects/{pid}/review/queue").json()
    assert rq["items"][0]["is_stale"] is True
    assert len(rq["items"][0]["stale_changes"]) >= 1

    # 4. Handover v1 shows out-of-date banner for admin
    h1_now = admin.get(f"/api/handovers/{h1['id']}").json()
    assert h1_now["freshness"]["out_of_date"] is True
    assert len(h1_now["freshness"]["stale_claim_ids"]) >= 1

    # Incoming user NEVER sees stale claims, restricted changes, or out_of_date admin internals
    inc_chg = inc.get(f"/api/projects/{pid}/changes").json()
    assert all(c["source_id"] != res_src_id for c in inc_chg["changes"])
    assert inc.get(f"/api/sources/{res_src_id}/versions").status_code == 404
    assert dep.get(f"/api/sources/{res_src_id}/versions").status_code == 404
    h1_inc = inc.get(f"/api/handovers/{h1['id']}").json()
    assert "freshness" not in h1_inc

    # 5. Re-analysis proposes updated claim as unreviewed while preserving reviewed claims
    an2 = admin.post(f"/api/projects/{pid}/analyze")
    assert an2.status_code == 202
    claims_after = admin.get(f"/api/projects/{pid}/claims").json()
    assert any("Adyen" in c["text"] and c["review_status"] == "unreviewed" for c in claims_after)
    assert any("Priya Nair" in c["text"] and c["review_status"] == "approved" for c in claims_after)

    # Reject the stale Stripe claim & approve the new Adyen claim
    stale_stripe = next(c for c in claims_after if "Stripe" in c["text"] and c["is_stale"])
    assert admin.post(
        f"/api/claims/{stale_stripe['id']}/review",
        json={"action": "reject", "note": "Replaced by Adyen webhooks in v2."},
    ).status_code == 200
    new_adyen = next(c for c in claims_after if "Adyen" in c["text"])
    assert admin.post(f"/api/claims/{new_adyen['id']}/review", json={"action": "accept"}).status_code == 200

    # 6. Create Handover v2 (v1 remains intact) + idempotent repeat call returns same draft v2
    h2 = admin.post(f"/api/handovers/{h1['id']}/new-version", json={}).json()
    assert h2["version_number"] == 2
    assert h2["parent_handover_id"] == h1["id"]
    h2_idem = admin.post(f"/api/handovers/{h1['id']}/new-version", json={}).json()
    assert h2_idem["id"] == h2["id"]

    # Incoming still sees ONLY v1 until v2 is approved & shared
    inc_vers_before = inc.get(f"/api/handovers/{h1['id']}/versions").json()
    assert [v["version_number"] for v in inc_vers_before] == [1]

    # Approve and share v2
    for sec in h2["sections"]:
        assert admin.patch(f"/api/handovers/{h2['id']}/sections/{sec['section_key']}", json={"review_status": "approved"}).status_code == 200
    assert admin.post(f"/api/handovers/{h2['id']}/approve").status_code == 200
    assert admin.post(f"/api/handovers/{h2['id']}/share", json={"target_user_id": inc_uid}).status_code == 200

    # Incoming now sees notice on v1 that v2 is available, and both approved versions in /versions
    h1_inc_after = inc.get(f"/api/handovers/{h1['id']}").json()
    assert h1_inc_after["newer_approved_version"]["version_number"] == 2
    inc_vers_after = inc.get(f"/api/handovers/{h1['id']}/versions").json()
    assert [v["version_number"] for v in inc_vers_after] == [1, 2]

    # Diff v1 -> v2 (admin sees full diff; incoming diff omits restricted claims)
    diff_adm = admin.get(f"/api/handovers/{h1['id']}/diff?from={h1['id']}&to={h2['id']}").json()
    assert diff_adm["counts"]["changed"] >= 1 or diff_adm["counts"]["added"] >= 1
    diff_inc = inc.get(f"/api/handovers/{h1['id']}/diff?from={h1['id']}&to={h2['id']}").json()
    all_inc_diff_rows = diff_inc["added"] + diff_inc["removed"] + diff_inc["changed"]
    assert all(r.get("clearance_level") != "restricted" for r in all_inc_diff_rows)

    # 7. Workspace isolation: outsider gets 404 on every Living Handover endpoint
    assert outsider.get(f"/api/projects/{pid}/changes").status_code == 404
    assert outsider.get(f"/api/sources/{src_id}/versions").status_code == 404
    assert outsider.get(f"/api/handovers/{h1['id']}/versions").status_code == 404
    assert outsider.get(f"/api/handovers/{h1['id']}/diff?from={h1['id']}&to={h2['id']}").status_code == 404
    assert outsider.post(f"/api/handovers/{h1['id']}/new-version", json={}).status_code == 404
