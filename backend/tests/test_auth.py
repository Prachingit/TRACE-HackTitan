"""Auth endpoint tests."""

import pytest
from fastapi.testclient import TestClient


def test_signup_success(client: TestClient):
    r = client.post("/api/auth/signup", json={
        "name": "Test User",
        "email": "test_signup@example.com",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == "test_signup@example.com"
    assert "id" in data
    # Cookie set
    assert "trace_session" in r.cookies


def test_signup_duplicate_email(client: TestClient):
    payload = {
        "name": "Dup User",
        "email": "dup_user@example.com",
        "password": "securepass123",
        "confirm_password": "securepass123",
    }
    r1 = client.post("/api/auth/signup", json=payload)
    assert r1.status_code == 201
    r2 = client.post("/api/auth/signup", json=payload)
    assert r2.status_code == 409


def test_signup_password_too_short(client: TestClient):
    r = client.post("/api/auth/signup", json={
        "name": "Short Pass",
        "email": "shortpass@example.com",
        "password": "abc",
        "confirm_password": "abc",
    })
    assert r.status_code == 422


def test_signup_passwords_mismatch(client: TestClient):
    r = client.post("/api/auth/signup", json={
        "name": "Mismatch",
        "email": "mismatch@example.com",
        "password": "securepass123",
        "confirm_password": "differentpass",
    })
    assert r.status_code == 422


def test_login_success(client: TestClient):
    # First create the user
    client.post("/api/auth/signup", json={
        "name": "Login Test",
        "email": "login_test@example.com",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })
    r = client.post("/api/auth/login", json={
        "email": "login_test@example.com",
        "password": "securepass123",
    })
    assert r.status_code == 200
    assert "trace_session" in r.cookies


def test_login_wrong_password(client: TestClient):
    client.post("/api/auth/signup", json={
        "name": "Wrong Pass Test",
        "email": "wrongpass@example.com",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })
    r = client.post("/api/auth/login", json={
        "email": "wrongpass@example.com",
        "password": "wrongpassword",
    })
    assert r.status_code == 401
    # Generic error — do not reveal email existence
    assert "Invalid email or password" in r.json()["detail"]


def test_login_unknown_email(client: TestClient):
    r = client.post("/api/auth/login", json={
        "email": "nobody@example.com",
        "password": "securepass123",
    })
    assert r.status_code == 401
    assert "Invalid email or password" in r.json()["detail"]


def test_me_authenticated(client: TestClient):
    client.post("/api/auth/signup", json={
        "name": "Me User",
        "email": "me_user@example.com",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })
    r_login = client.post("/api/auth/login", json={
        "email": "me_user@example.com",
        "password": "securepass123",
    })
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "me_user@example.com"


def test_me_unauthenticated(client: TestClient):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_logout(client: TestClient):
    client.post("/api/auth/signup", json={
        "name": "Logout User",
        "email": "logout_user@example.com",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })
    r_login = client.post("/api/auth/login", json={
        "email": "logout_user@example.com",
        "password": "securepass123",
    })
    token = r_login.cookies.get("trace_session")
    r_logout = client.post("/api/auth/logout", cookies={"trace_session": token})
    assert r_logout.status_code == 204


def test_forgot_password_no_smtp(client: TestClient):
    r = client.post("/api/auth/forgot-password", json={"email": "anyone@example.com"})
    assert r.status_code == 202
    assert "not configured" in r.json()["message"].lower()

