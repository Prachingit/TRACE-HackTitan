"""FastAPI main application for TRACE."""

from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.db import get_db, init_db
from app.models import Role as RoleModel, Source as SourceModel
from app import schemas

# Clearance ordering: public < internal < restricted
CLEARANCE_ORDER = {
    "public": 1,
    "internal": 2,
    "restricted": 3,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables on startup
    init_db()
    yield

app = FastAPI(
    title="TRACE API",
    description="Team Records, Activity & Context Engine API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration for Vite (5173) and Next/CRA (3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=schemas.HealthResponse, tags=["System"])
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/api/roles", response_model=List[schemas.Role], tags=["Roles"])
def get_roles(db: Session = Depends(get_db)):
    """Retrieve available roles and their clearance levels."""
    roles = db.query(RoleModel).all()
    if not roles:
        # Default fallback if DB has not been seeded yet
        return [
            schemas.Role(id="team_lead", name="Team Lead", clearance="restricted"),
            schemas.Role(id="incoming_developer", name="Incoming Developer", clearance="internal"),
            schemas.Role(id="external_reviewer", name="External Reviewer", clearance="public"),
        ]
    return [schemas.Role.model_validate(r) for r in roles]


@app.get("/api/demo/sources", response_model=List[schemas.Source], tags=["Sources"])
def get_demo_sources(
    role: str = Query(..., description="Role requesting source items (team_lead, incoming_developer, external_reviewer)"),
    db: Session = Depends(get_db),
):
    """Retrieve demo sources filtered by role clearance.
    
    Ordering: public < internal < restricted
    - external_reviewer (public) sees public only
    - incoming_developer (internal) sees public and internal
    - team_lead (restricted) sees public, internal, and restricted
    Unknown roles return HTTP 400.
    """
    role_obj = db.query(RoleModel).filter(RoleModel.id == role).first()
    
    # Handle role clearance determination
    if role_obj is not None:
        role_clearance = role_obj.clearance
    elif role in CLEARANCE_ORDER:
        role_clearance = role
    else:
        # Check standard known role IDs if DB is unseeded
        fallback_roles = {
            "team_lead": "restricted",
            "incoming_developer": "internal",
            "external_reviewer": "public",
        }
        if role in fallback_roles:
            role_clearance = fallback_roles[role]
        else:
            raise HTTPException(status_code=400, detail=f"Unknown role '{role}'")

    max_clearance_rank = CLEARANCE_ORDER[role_clearance]
    allowed_labels = [label for label, rank in CLEARANCE_ORDER.items() if rank <= max_clearance_rank]

    sources = db.query(SourceModel).filter(SourceModel.access_label.in_(allowed_labels)).all()
    return [schemas.Source.model_validate(s) for s in sources]


@app.get("/api/contract", response_model=schemas.ContractDoc, tags=["Contract"])
def get_contract():
    """Return the complete human and machine readable API contract definition."""
    return schemas.ContractDoc(
        version="1.0.0",
        description="TRACE (Team Records, Activity & Context Engine) API Contract",
        models={
            "Source": {
                "fields": {
                    "id": "string (UUID or identifier)",
                    "project_id": "string",
                    "type": "enum: git | pr | task | note | chat | doc",
                    "title": "string",
                    "origin_ref": "string",
                    "access_label": "enum: public | internal | restricted",
                    "created_at": "ISO 8601 string or null",
                }
            },
            "ActivityItem": {
                "fields": {
                    "id": "string",
                    "source_id": "string",
                    "kind": "string",
                    "author": "string or null",
                    "timestamp": "ISO 8601 string or null",
                    "text": "string",
                    "ref": "string or null",
                    "access_label": "enum: public | internal | restricted",
                }
            },
            "Evidence": {
                "fields": {
                    "id": "string or null",
                    "claim_id": "string or null",
                    "activity_item_id": "string or null",
                    "source_id": "string",
                    "source_title": "string or null",
                    "quote": "string (max 200 chars)",
                    "locator": "string",
                }
            },
            "Claim": {
                "fields": {
                    "id": "string",
                    "project_id": "string or null",
                    "type": "enum: state | decision | task | blocker | dependency | ownership | contradiction | open_loop | gap",
                    "statement": "string",
                    "status": "enum: verified | inferred | conflicting | missing",
                    "confidence_note": "string or null",
                    "owner": "string or null",
                    "access_label": "enum: public | internal | restricted",
                    "review_state": "enum: pending | accepted | edited | rejected",
                    "evidence": "list[Evidence]",
                    "created_at": "ISO 8601 string or null",
                }
            },
            "GapQuestion": {
                "fields": {
                    "id": "string",
                    "claim_id": "string",
                    "question": "string",
                    "answer": "string or null",
                    "answered_by": "string or null",
                    "answered_at": "ISO 8601 string or null",
                }
            },
            "Review": {
                "fields": {
                    "id": "string",
                    "claim_id": "string",
                    "action": "enum: accept | edit | reject",
                    "edited_statement": "string or null",
                    "reviewer": "string",
                    "version": "integer",
                    "created_at": "ISO 8601 string or null",
                }
            },
            "RoleView": {
                "fields": {
                    "role": "string",
                    "clearance": "enum: public | internal | restricted",
                    "handover": "Handover",
                    "hidden_count": "integer",
                }
            },
            "Handover": {
                "fields": {
                    "id": "string",
                    "project_id": "string",
                    "version": "integer",
                    "status": "enum: draft | approved",
                    "approved_by": "string or null",
                    "approved_at": "ISO 8601 string or null",
                    "acknowledged_by": "string or null",
                    "acknowledged_at": "ISO 8601 string or null",
                    "created_at": "ISO 8601 string or null",
                    "claims": "list[Claim]",
                }
            },
            "PlanStep": {
                "fields": {
                    "id": "string",
                    "handover_id": "string or null",
                    "rank": "integer",
                    "action": "string",
                    "reason": "string",
                    "claim_ids": "list[string]",
                }
            },
        },
        current_endpoints=[
            {"path": "/health", "method": "GET", "description": "Health check"},
            {"path": "/api/roles", "method": "GET", "description": "List roles and clearance"},
            {"path": "/api/demo/sources", "method": "GET", "description": "Role-filtered demo sources"},
            {"path": "/api/contract", "method": "GET", "description": "API contract schema & roadmap"},
        ],
        planned_endpoints=[
            {"path": "/api/projects/demo/load", "method": "POST", "status": "planned", "phase": 3},
            {"path": "/api/projects/{id}/analyze", "method": "POST", "status": "planned", "phase": 4},
            {"path": "/api/handover", "method": "GET", "query_params": ["role"], "status": "planned", "phase": 5},
            {"path": "/api/claims/{id}/review", "method": "POST", "status": "planned", "phase": 6},
            {"path": "/api/gap-questions/{id}/answer", "method": "POST", "status": "planned", "phase": 6},
            {"path": "/api/handover/approve", "method": "POST", "status": "planned", "phase": 6},
            {"path": "/api/handover/acknowledge", "method": "POST", "status": "planned", "phase": 6},
            {"path": "/api/plan", "method": "GET", "query_params": ["role"], "status": "planned", "phase": 5},
        ],
    )
