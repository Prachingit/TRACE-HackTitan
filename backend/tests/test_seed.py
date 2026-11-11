"""Tests for TRACE database seed script."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Project, Role, Source
from scripts.seed import DEMO_SOURCES_META, ROLES_DATA, seed


@pytest.fixture(autouse=True)
def run_seed():
    """Ensure a clean, seeded database before each test run."""
    seed(reset=True)
    yield


def test_seed_idempotency():
    """Seeding twice must not duplicate rows."""
    session = SessionLocal()
    try:
        initial_proj_count = session.query(Project).count()
        initial_role_count = session.query(Role).count()
        initial_source_count = session.query(Source).count()
        assert initial_proj_count == 1
        assert initial_role_count == 3
        assert initial_source_count == len(DEMO_SOURCES_META)

        # Run seed a second time without reset
        seed(reset=False)

        second_proj_count = session.query(Project).count()
        second_role_count = session.query(Role).count()
        second_source_count = session.query(Source).count()

        assert second_proj_count == initial_proj_count
        assert second_role_count == initial_role_count
        assert second_source_count == initial_source_count
    finally:
        session.close()


def test_every_demo_file_registered():
    """Every defined demo source file must exist in the database."""
    session = SessionLocal()
    try:
        sources = session.query(Source).all()
        source_ids = {s.id for s in sources}
        for item in DEMO_SOURCES_META:
            assert item["id"] in source_ids, f"Source '{item['id']}' not registered in database."
    finally:
        session.close()


def test_restricted_file_access_label():
    """The vendor budget note must be registered with access_label 'restricted'."""
    session = SessionLocal()
    try:
        restricted_source = session.query(Source).filter(Source.id == "src-restricted-budget").first()
        assert restricted_source is not None
        assert restricted_source.access_label == "restricted"
        assert "vendor_budget_notes.md" in restricted_source.origin_ref
    finally:
        session.close()


def test_public_and_internal_sources():
    """Public README and internal sources must have their designated labels."""
    session = SessionLocal()
    try:
        readme = session.query(Source).filter(Source.id == "src-readme").first()
        assert readme is not None
        assert readme.access_label == "public"

        git_log = session.query(Source).filter(Source.id == "src-git-log").first()
        assert git_log is not None
        assert git_log.access_label == "internal"
    finally:
        session.close()
