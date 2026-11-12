"""Shared test fixtures for TRACE Phase 2 tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.routers.auth import limiter

limiter.enabled = False

TEST_DB_URL = "sqlite:///./test_trace.db"

engine_test = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create all tables in test DB once per session."""
    Base.metadata.create_all(bind=engine_test)
    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=engine_test)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client():
    """Fresh TestClient for each test."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="function")
def db():
    """Provide a DB session that rolls back after each test."""
    connection = engine_test.connect()
    transaction = connection.begin()
    session = TestingSession(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()



@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    """Per-test upload dir; background jobs use the test DB session factory."""
    from app import db as db_module
    from app.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(db_module, "SessionLocal", TestingSession)


def make_user(email: str, name: str = "User") -> TestClient:
    """Return a TestClient that is signed up and logged in as a fresh user."""
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/auth/signup", json={
        "name": name, "email": email,
        "password": "securepass123", "confirm_password": "securepass123",
    })
    assert r.status_code == 201, r.text
    return c


def make_project(c: TestClient, name: str = "P"):
    ws = c.post("/api/workspaces", json={"name": f"WS {name}"}).json()
    pr = c.post("/api/projects", json={"workspace_id": ws["id"], "name": name}).json()
    return ws["id"], pr["id"]


def join_as(admin: TestClient, ws_id: str, email: str, role: str) -> TestClient:
    token = admin.post(f"/api/workspaces/{ws_id}/invites", json={"role": role}).json()["token"]
    other = make_user(email)
    r = other.post("/api/workspaces/join", json={"token": token})
    assert r.status_code == 201, r.text
    return other
