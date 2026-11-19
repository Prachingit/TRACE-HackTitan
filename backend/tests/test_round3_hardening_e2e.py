"""Round 3 Hardening: Full end-to-end journey (Phases 1-8 + Living Handover + Readiness + Continuity) & regressions."""

from tests.conftest import join_as, make_project, make_user


def test_complete_round3_journey_and_hardening_regressions(client):
    # 0. Health check reports DB and storage accurately
    h_res = client.get("/api/health")
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "ok"
    assert h_res.json()["db"] == "ok"
    assert h_res.json()["storage"] == "ok"

    # 1. Signup, workspace, project, empty states, bad inputs
    admin1 = make_user("r3_admin1@example.com", "Admin One")
    ws_id, pid = make_project(admin1, "Helios Core")
    admin2 = join_as(admin1, ws_id, "r3_admin2@example.com", "admin")
    inc = join_as(admin1, ws_id, "r3_inc@example.com", "incoming")
    dep = join_as(admin1, ws_id, "r3_dep@example.com", "departing")

    # Empty project states return 200 with empty lists (never 500)
    assert admin1.get(f"/api/projects/{pid}/claims").json() == []
    assert admin1.get(f"/api/projects/{pid}/changes").json()["changes"] == []
    assert admin1.get(f"/api/projects/{pid}/graph").json()["edges"] == []
    assert admin1.get(f"/api/projects/{pid}/custody").json() == []

    # Bad upload input: empty file & disallowed extension return 400
    assert admin1.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": ("empty.md", b"", "text/markdown")},
        data={"clearance_level": "team"},
    ).status_code == 400
    assert admin1.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": ("bad.exe", b"MZ...", "application/octet-stream")},
        data={"clearance_level": "team"},
    ).status_code == 400

    # 2. Upload non-Atlas files & analyze
    md_v1 = (
        "# Helios Core\n\n"
        "Owner: Priya Nair handles scheduler.\n\n"
        "We decided to use RabbitMQ for job queues because retries are built in.\n\n"
        "Scheduler deploy is blocked by missing Render env vars.\n"
    ).encode()
    up1 = admin1.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": ("helios.md", md_v1, "text/markdown")},
        data={"clearance_level": "team"},
    )
    assert up1.status_code == 201
    assert admin1.post(f"/api/projects/{pid}/analyze").status_code == 202

    claims = admin1.get(f"/api/projects/{pid}/claims").json()
    assert len(claims) >= 2

    # 3. Optimistic concurrency check on review: two admins review same claim at version=0
    target = claims[0]
    r_ok = admin1.post(
        f"/api/claims/{target['id']}/review",
        json={"action": "accept", "expected_version": target["version"], "resolve_contradictions": True, "note": "A1 ok"},
    )
    assert r_ok.status_code == 200
    r_stale_ver = admin2.post(
        f"/api/claims/{target['id']}/review",
        json={"action": "reject", "expected_version": target["version"], "note": "A2 stale"},
    )
    assert r_stale_ver.status_code == 409
    assert "already updated" in r_stale_ver.json()["detail"].lower()

    # Approve remaining claims
    for c in claims[1:]:
        admin1.post(
            f"/api/claims/{c['id']}/review",
            json={"action": "accept", "resolve_contradictions": True, "note": "Approved."},
        )

    # 4. Continuity Graph + Custody secret rejection + confirm
    assert admin1.post(f"/api/projects/{pid}/graph/rebuild").status_code == 200
    assert len(admin1.get(f"/api/projects/{pid}/graph").json()["edges"]) >= 1
    assert admin1.post(
        f"/api/projects/{pid}/custody",
        json={"kind": "hosting", "name": "Render", "notes": "ghp_secretTokenValue1234567890abcdef"},
    ).status_code == 400
    c_item = admin1.post(
        f"/api/projects/{pid}/custody",
        json={"kind": "hosting", "name": "Render", "owner_person": "Priya Nair", "where_to_request_access": "Ask Priya in #ops"},
    ).json()
    assert admin1.post(f"/api/custody/{c_item['id']}/confirm", json={"status": "confirmed"}).status_code == 200

    # 5. Handover v1 -> approve -> share -> incoming portal + readiness verification + PDF export
    h1 = admin1.post(f"/api/projects/{pid}/handovers", json={"title": "Helios Handover"}).json()
    assert any(s["section_key"] == "continuity_custody" for s in h1["sections"])
    for sec in h1["sections"]:
        assert admin1.patch(f"/api/handovers/{h1['id']}/sections/{sec['section_key']}", json={"review_status": "approved"}).status_code == 200
    assert admin1.post(f"/api/handovers/{h1['id']}/approve").status_code == 200
    inc_uid = next(m["user_id"] for m in admin1.get(f"/api/workspaces/{ws_id}/members").json() if m["role"] == "incoming")
    assert admin1.post(f"/api/handovers/{h1['id']}/share", json={"target_user_id": inc_uid}).status_code == 200

    # Readiness verification
    ass = admin1.post(f"/api/handovers/{h1['id']}/assessment/generate").json()
    assert ass["question_count"] >= 1
    att = inc.post("/api/assessment-attempts", json={"handover_id": h1["id"]}).json()
    sub = inc.post(
        f"/api/assessment-attempts/{att['id']}/submit",
        json={"answers": [{"question_id": q["id"], "answer_text": "Not recorded"} for q in att["questions"]]},
    )
    assert sub.status_code == 200
    assert dep.get(f"/api/handovers/{h1['id']}/assessment").status_code == 403

    # PDF export works
    pdf = inc.get(f"/api/handovers/{h1['id']}/export.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # 6. Living Handover: re-upload changed file -> stale claim -> handover v2 & diff
    md_v2 = (
        "# Helios Core\n\n"
        "Owner: Priya Nair handles scheduler.\n\n"
        "We decided to use Celery with Redis for job queues because team knows Python.\n\n"
        "Scheduler deploy is blocked by missing Render env vars.\n"
    ).encode()
    up2 = admin1.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": ("helios.md", md_v2, "text/markdown")},
        data={"clearance_level": "team"},
    )
    assert up2.status_code == 201 and up2.json()["is_new_version"] is True
    assert len(admin1.get(f"/api/claims?project_id={pid}&stale=true").json()) >= 1
    assert admin1.get(f"/api/handovers/{h1['id']}").json()["freshness"]["out_of_date"] is True

    h2 = admin1.post(f"/api/handovers/{h1['id']}/new-version", json={}).json()
    assert h2["version_number"] == 2
    diff = admin1.get(f"/api/handovers/{h1['id']}/diff?from={h1['id']}&to={h2['id']}")
    assert diff.status_code == 200
