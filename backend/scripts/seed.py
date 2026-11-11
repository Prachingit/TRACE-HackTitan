"""Seed script for TRACE.

Registers the demo project, default roles with clearances, and one Source
record per demo file with its appropriate access_label.
Idempotent: Re-running does not duplicate rows.
Supports '--reset' to cleanly re-create the database.
Does NOT parse file contents into activity_items (Phase 3 scope).
"""

import argparse
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.db import Base, SessionLocal, engine, init_db
from app.models import Project, Role, Source

DEMO_DATA_DIR = Path(settings.DEMO_DATA_DIR).resolve()

DEMO_SOURCES_META = [
    {
        "id": "src-git-log",
        "type": "git",
        "title": "Git Commit Log",
        "origin_ref": "data/demo/git_log.json",
        "access_label": "internal",
    },
    {
        "id": "src-pull-requests",
        "type": "pr",
        "title": "GitHub Pull Requests",
        "origin_ref": "data/demo/pull_requests.json",
        "access_label": "internal",
    },
    {
        "id": "src-tasks",
        "type": "task",
        "title": "Project Tasks CSV",
        "origin_ref": "data/demo/tasks.csv",
        "access_label": "internal",
    },
    {
        "id": "src-note-standup-oct12",
        "type": "note",
        "title": "Meeting Note: Standup Oct 12",
        "origin_ref": "data/demo/notes/standup_oct12.md",
        "access_label": "internal",
    },
    {
        "id": "src-note-sprint-review-oct26",
        "type": "note",
        "title": "Meeting Note: Sprint Review Oct 26",
        "origin_ref": "data/demo/notes/sprint_review_oct26.md",
        "access_label": "internal",
    },
    {
        "id": "src-note-sprint-planning-nov02",
        "type": "note",
        "title": "Meeting Note: Sprint Planning Nov 02",
        "origin_ref": "data/demo/notes/sprint_planning_nov02.md",
        "access_label": "internal",
    },
    {
        "id": "src-chat",
        "type": "chat",
        "title": "Team Chat Logs",
        "origin_ref": "data/demo/chat.json",
        "access_label": "internal",
    },
    {
        "id": "src-readme",
        "type": "doc",
        "title": "CampusConnect Project README",
        "origin_ref": "data/demo/README_project.md",
        "access_label": "public",
    },
    {
        "id": "src-restricted-budget",
        "type": "doc",
        "title": "Vendor Budget & Contract Pricing (Restricted)",
        "origin_ref": "data/demo/restricted/vendor_budget_notes.md",
        "access_label": "restricted",
    },
]

ROLES_DATA = [
    {"id": "team_lead", "name": "Team Lead", "clearance": "restricted"},
    {"id": "incoming_developer", "name": "Incoming Developer", "clearance": "internal"},
    {"id": "external_reviewer", "name": "External Reviewer", "clearance": "public"},
]


def seed(reset: bool = False) -> None:
    if reset:
        print("[TRACE Seed] --reset specified. Dropping all tables...")
        Base.metadata.drop_all(bind=engine)

    init_db()
    session = SessionLocal()

    try:
        # 1. Project
        project_id = "proj-campusconnect"
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            project = Project(
                id=project_id,
                name="CampusConnect",
                description="Student events discovery and ticket reservation platform.",
            )
            session.add(project)
            session.flush()

        # 2. Roles
        roles_loaded = 0
        for r_info in ROLES_DATA:
            role = session.query(Role).filter(Role.id == r_info["id"]).first()
            if not role:
                role = Role(
                    id=r_info["id"],
                    name=r_info["name"],
                    clearance=r_info["clearance"],
                )
                session.add(role)
                roles_loaded += 1
            else:
                role.name = r_info["name"]
                role.clearance = r_info["clearance"]

        # 3. Sources
        sources_loaded = 0
        for s_info in DEMO_SOURCES_META:
            source = session.query(Source).filter(Source.id == s_info["id"]).first()
            if not source:
                source = Source(
                    id=s_info["id"],
                    project_id=project.id,
                    type=s_info["type"],
                    title=s_info["title"],
                    origin_ref=s_info["origin_ref"],
                    access_label=s_info["access_label"],
                )
                session.add(source)
                sources_loaded += 1
            else:
                source.title = s_info["title"]
                source.origin_ref = s_info["origin_ref"]
                source.access_label = s_info["access_label"]

        session.commit()

        # Print summary
        total_projects = session.query(Project).count()
        total_roles = session.query(Role).count()
        total_sources = session.query(Source).count()
        public_sources = session.query(Source).filter(Source.access_label == "public").count()
        internal_sources = session.query(Source).filter(Source.access_label == "internal").count()
        restricted_sources = session.query(Source).filter(Source.access_label == "restricted").count()

        print("=" * 60)
        print(" TRACE Database Seeding Completed Successfully")
        print("=" * 60)
        print(f" Database Target  : {settings.DATABASE_URL}")
        print(f" Projects in DB   : {total_projects} ({project.name})")
        print(f" Roles Seeded     : {total_roles} (team_lead, incoming_developer, external_reviewer)")
        print(f" Sources Seeded   : {total_sources} total files registered")
        print(f"   - Public       : {public_sources}")
        print(f"   - Internal     : {internal_sources}")
        print(f"   - Restricted   : {restricted_sources}")
        print(" Note: Activity items are NOT parsed (Phase 3 scope).")
        print("=" * 60)

    except Exception as e:
        session.rollback()
        print(f"[TRACE Seed ERROR] Failed to seed database: {e}", file=sys.stderr)
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed TRACE database with demo dataset metadata.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables before seeding.")
    args = parser.parse_args()
    seed(reset=args.reset)
