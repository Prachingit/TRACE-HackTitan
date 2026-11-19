"""Round 3, Improvement B: Readiness Verification tests (non-Atlas fixture)."""

from tests.conftest import join_as, make_project, make_user


def _up(client, pid: str, filename: str, data: bytes, clearance: str = "team"):
    return client.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": (filename, data, "text/plain")},
        data={"clearance_level": clearance},
    )


def test_readiness_verification_full_flow_non_atlas_and_clearance(client):
    admin = make_user("rv_admin@example.com", "Lead Admin")
    ws_id, pid = make_project(admin, "Cobalt Search")
    inc = join_as(admin, ws_id, "rv_inc@example.com", "incoming")
    dep = join_as(admin, ws_id, "rv_dep@example.com", "departing")
    outsider = make_user("rv_out@example.com", "Outsider")

    # Non-Atlas sources: team + restricted + unapproved draft
    team_md = (
        "# Cobalt Search Notes\n\n"
        "Indexing pipeline is assigned to Asha Rao.\n\n"
        "We decided to use Meilisearch for typo tolerance because latency stayed under 25ms.\n\n"
        "Search re-indexer is blocked by missing Redis queue credentials.\n"
    ).encode()
    assert _up(admin, pid, "search_notes.md", team_md, "team").status_code == 201
    assert _up(
        admin,
        pid,
        "restricted_sec.md",
        b"# Secret\n\nVault root token is assigned to Security Bot.\n",
        "restricted",
    ).status_code == 201

    assert admin.post(f"/api/projects/{pid}/analyze").status_code == 202
    claims = admin.get(f"/api/projects/{pid}/claims").json()
    assert len(claims) >= 3

    # Approve ONLY non-restricted claims except leave one team claim unreviewed to verify exclusion
    restricted_ids = {c["id"] for c in claims if c["clearance_level"] == "restricted"}
    assert restricted_ids
    for c in claims:
        if c["id"] in restricted_ids:
            assert admin.post(
                f"/api/claims/{c['id']}/review",
                json={"action": "accept", "resolve_contradictions": True, "note": "Verified for test."},
            ).status_code == 200
        elif "blocked" in c["text"].lower() or "asha" in c["text"].lower() or "meilisearch" in c["text"].lower():
            assert admin.post(
                f"/api/claims/{c['id']}/review",
                json={"action": "accept", "resolve_contradictions": True, "note": "Verified for test."},
            ).status_code == 200

    # Add one rejected claim to confirm rejected claims never enter assessment
    unrev_id = next((c["id"] for c in claims if c["id"] not in restricted_ids and "blocked" not in c["text"].lower() and "asha" not in c["text"].lower() and "meilisearch" not in c["text"].lower()), None)
    if unrev_id:
        assert admin.post(f"/api/claims/{unrev_id}/review", json={"action": "reject", "note": "Outdated."}).status_code == 200

    # Generate, approve, and share handover
    h = admin.post(f"/api/projects/{pid}/handovers", json={"title": "Cobalt Handover"}).json()
    for sec in h["sections"]:
        assert admin.patch(f"/api/handovers/{h['id']}/sections/{sec['section_key']}", json={"review_status": "approved"}).status_code == 200
    assert admin.post(f"/api/handovers/{h['id']}/approve").status_code == 200
    inc_uid = next(m["user_id"] for m in admin.get(f"/api/workspaces/{ws_id}/members").json() if m["role"] == "incoming")

    # Incoming cannot access assessment before handover is shared
    assert inc.get(f"/api/handovers/{h['id']}/assessment").status_code == 403
    assert admin.post(f"/api/handovers/{h['id']}/share", json={"target_user_id": inc_uid}).status_code == 200

    # Non-admin cannot generate assessment
    assert inc.post(f"/api/handovers/{h['id']}/assessment/generate").status_code == 403
    assert dep.post(f"/api/handovers/{h['id']}/assessment/generate").status_code == 403

    # Admin generates assessment (no-LLM fallback -> template, idempotent on second call)
    gen1 = admin.post(f"/api/handovers/{h['id']}/assessment/generate")
    assert gen1.status_code == 201, gen1.text
    ass1 = gen1.json()
    assert ass1["question_count"] >= 2
    assert ass1["text_source"] == "template"
    for q in ass1["questions"]:
        assert len(q["source_claim_ids"]) >= 1
        assert all(cid not in restricted_ids for cid in q["source_claim_ids"])
        if unrev_id:
            assert unrev_id not in q["source_claim_ids"]

    gen2 = admin.post(f"/api/handovers/{h['id']}/assessment/generate")
    assert gen2.status_code == 201
    assert gen2.json()["question_count"] == ass1["question_count"]

    # Incoming fetches assessment: NEVER receives correct_answer, answer_key, or explanation
    inc_ass = inc.get(f"/api/handovers/{h['id']}/assessment")
    assert inc_ass.status_code == 200
    for q in inc_ass.json()["questions"]:
        assert "correct_answer" not in q
        assert "answer_key" not in q
        assert "explanation" not in q

    # Departing & outsider blocked
    assert dep.get(f"/api/handovers/{h['id']}/assessment").status_code == 403
    assert outsider.get(f"/api/handovers/{h['id']}/assessment").status_code == 404
    assert outsider.post("/api/assessment-attempts", json={"handover_id": h["id"]}).status_code == 404

    # 1. Baseline attempt: deliberately answer poorly to trigger weak areas & partial short-answer credit
    att1_res = inc.post("/api/assessment-attempts", json={"handover_id": h["id"]})
    assert att1_res.status_code == 201, att1_res.text
    att1 = att1_res.json()
    assert att1["attempt_kind"] == "baseline"
    for q in att1["questions"]:
        assert "correct_answer" not in q

    # Find short-answer question if present and give partial-term answer
    base_answers = []
    for q in att1["questions"]:
        if q["question_type"] == "short_answer":
            base_answers.append({"question_id": q["id"], "answer_text": "check redis"})
        else:
            base_answers.append({"question_id": q["id"], "answer_text": "Not recorded in the handover"})

    sub1 = inc.post(f"/api/assessment-attempts/{att1['id']}/submit", json={"answers": base_answers})
    assert sub1.status_code == 200, sub1.text
    sub1_data = sub1.json()
    assert sub1_data["status"] == "submitted"
    assert sub1_data["overall_score"] < 70.0
    assert any(ar["status"] == "needs_more_handover" for ar in sub1_data["area_scores"])
    for ans in sub1_data["answers"]:
        assert "correct_answer" not in ans
        assert len(ans["source_claim_ids"]) >= 1
        assert ans["explanation"]

    # Double submit rejected
    assert inc.post(f"/api/assessment-attempts/{att1['id']}/submit", json={"answers": base_answers}).status_code == 409

    # 2. Re-assessment retake: answer using the real answer keys (fetched as admin) -> positive delta
    admin_qs = {q["id"]: q for q in ass1["questions"]}
    att2 = inc.post("/api/assessment-attempts", json={"handover_id": h["id"]}).json()
    assert att2["attempt_number"] == 2
    assert att2["attempt_kind"] == "reassessment"
    good_answers = [
        {"question_id": q["id"], "answer_text": admin_qs[q["id"]]["correct_answer"]}
        for q in att2["questions"]
    ]
    sub2 = inc.post(f"/api/assessment-attempts/{att2['id']}/submit", json={"answers": good_answers}).json()
    assert sub2["overall_score"] > sub1_data["overall_score"]

    # Admin sees before/after delta, weak areas (from baseline), and can send weak areas to Exit Interview
    rdy_adm = admin.get(f"/api/handovers/{h['id']}/readiness").json()
    assert len(rdy_adm["participants"]) == 1
    part = rdy_adm["participants"][0]
    assert part["attempt_count"] == 2
    assert part["delta_overall"] > 0

    # Incoming readiness never includes correct_answer
    rdy_inc = inc.get(f"/api/handovers/{h['id']}/readiness").json()
    for a in rdy_inc["participants"][0]["attempts"]:
        for ans in a["answers"]:
            assert "correct_answer" not in ans

    # Send weak areas to Exit Interview (if any weak area on latest or baseline)
    send_res = admin.post(f"/api/handovers/{h['id']}/readiness/send-to-interview")
    assert send_res.status_code == 200
