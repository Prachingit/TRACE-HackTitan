"""Tenant isolation tests — user B cannot see user A's data."""

import pytest
from fastapi.testclient import TestClient


def _signup_and_login(client: TestClient, email: str, name: str = "Test") -> str:
    """Create user, login, return session token."""
    client.post("/api/auth/signup", json={
        "name": name, "email": email,
        "password": "securepass123", "confirm_password": "securepass123",
    })
    r = client.post("/api/auth/login", json={"email": email, "password": "securepass123"})
    return r.cookies.get("trace_session", "")


def _make_workspace_and_project(client: TestClient, token: str, ws_name: str, proj_name: str):
    ws_r = client.post("/api/workspaces", json={"name": ws_name}, cookies={"trace_session": token})
    ws_id = ws_r.json()["id"]
    proj_r = client.post("/api/projects", json={
        "workspace_id": ws_id,
        "name": proj_name,
    }, cookies={"trace_session": token})
    return ws_id, proj_r.json()["id"]


def test_project_isolation(client: TestClient):
    """User B cannot access User A's project."""
    token_a = _signup_and_login(client, "alice_iso@example.com", "Alice")
    token_b = _signup_and_login(client, "bob_iso@example.com", "Bob")

    _, proj_id_a = _make_workspace_and_project(client, token_a, "Alice WS", "Alice Project")

    # B tries to access A's project
    r = client.get(f"/api/projects/{proj_id_a}", cookies={"trace_session": token_b})
    assert r.status_code == 404


def test_source_isolation(client: TestClient):
    """User B cannot access User A's sources."""
    token_a = _signup_and_login(client, "alice_src@example.com", "Alice")
    token_b = _signup_and_login(client, "bob_src@example.com", "Bob")

    _, proj_id_a = _make_workspace_and_project(client, token_a, "Alice WS Src", "Alice Src Project")

    # Add a manual source to A's project
    client.post(f"/api/projects/{proj_id_a}/sources/manual", json={
        "title": "Secret doc",
        "content": "Top secret content",
        "clearance_level": "team",
    }, cookies={"trace_session": token_a})

    # B tries to list A's sources
    r = client.get(f"/api/projects/{proj_id_a}/sources", cookies={"trace_session": token_b})
    assert r.status_code == 404


def test_workspace_isolation(client: TestClient):
    """User B cannot see User A's workspace members."""
    token_a = _signup_and_login(client, "alice_ws@example.com", "Alice")
    token_b = _signup_and_login(client, "bob_ws@example.com", "Bob")

    ws_r = client.post("/api/workspaces", json={"name": "Alice Private WS"}, cookies={"trace_session": token_a})
    ws_id = ws_r.json()["id"]

    r = client.get(f"/api/workspaces/{ws_id}/members", cookies={"trace_session": token_b})
    assert r.status_code == 404
