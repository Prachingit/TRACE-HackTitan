"""Tests for Atlas Workspace database seeder."""

import pytest
from app.db import SessionLocal, init_db
from app.models import Membership, Project, Source, User, Workspace
from app.services.seed import SOURCES_METADATA, USERS_DATA, seed_atlas


@pytest.fixture(autouse=True)
def setup_seed():
    """Initialize DB and run seed before tests."""
    init_db()
    seed_atlas()
    yield


def test_atlas_seed_idempotency():
    """Seeding Atlas multiple times must not duplicate records."""
    db = SessionLocal()
    try:
        initial_workspace_count = db.query(Workspace).count()
        initial_user_count = db.query(User).count()
        initial_membership_count = db.query(Membership).count()
        initial_project_count = db.query(Project).count()
        initial_source_count = db.query(Source).count()

        assert initial_workspace_count == 1
        assert initial_user_count == len(USERS_DATA)
        assert initial_project_count == 1
        assert initial_source_count == len(SOURCES_METADATA)

        # Run seed a second time
        seed_atlas(db=db)

        assert db.query(Workspace).count() == initial_workspace_count
        assert db.query(User).count() == initial_user_count
        assert db.query(Membership).count() == initial_membership_count
        assert db.query(Project).count() == initial_project_count
        assert db.query(Source).count() == initial_source_count
    finally:
        db.close()


def test_atlas_sources_metadata_and_clearance():
    """All 7 Atlas files are registered with appropriate clearance levels."""
    db = SessionLocal()
    try:
        sources = db.query(Source).filter(Source.project_id == "prj-atlas-core").all()
        assert len(sources) == 7

        source_by_id = {s.id: s for s in sources}
        for item in SOURCES_METADATA:
            s = source_by_id.get(item["id"])
            assert s is not None, f"Source {item['id']} missing from DB"
            assert s.clearance_level == item["clearance_level"]
            assert s.status == "registered"
            assert s.filename == item["filename"]

        # Specifically verify restricted record
        restricted = source_by_id["SRC-007"]
        assert restricted.clearance_level == "restricted"
        assert restricted.filename == "restricted_internal.md"

        # Verify public architecture docs
        arch = source_by_id["SRC-005"]
        assert arch.clearance_level == "public"

        # Verify synthetic project flag
        project = db.query(Project).filter(Project.id == "prj-atlas-core").first()
        assert project.is_synthetic is True
    finally:
        db.close()
