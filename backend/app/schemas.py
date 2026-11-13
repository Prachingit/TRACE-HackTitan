"""Pydantic v2 Schemas for TRACE API.

Defines the contract for Phase 1 endpoints, matching the frontend contract exactly.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseSchema):
    status: str = "ok"
    version: str = "1.0.0"
    db: str = "ok"
    storage: str = "ok"


class DemoLoadResponse(BaseSchema):
    project_id: str
    workspace_id: str
    sources_registered: int


class CurrentUserResponse(BaseSchema):
    id: str
    name: str
    email: str
    role: str
    workspace_id: str
    workspace_name: str


class ProjectResponse(BaseSchema):
    id: str
    workspace_id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    team_size: int = 1
    technologies: Optional[str] = None
    start_date: Optional[datetime] = None
    is_synthetic: bool = False
    created_at: Optional[datetime] = None


class MemberResponse(BaseSchema):
    user_id: str
    name: str
    email: str
    role: str


class SourceResponse(BaseSchema):
    id: str
    type: str
    filename: str
    status: str
    clearance_level: str
    source_timestamp: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None


class ProjectSummaryResponse(BaseSchema):
    project_id: str
    project_name: str
    is_synthetic: bool
    source_count: int
    sources_by_type: Dict[str, int]
    member_count: int
    claim_count: int
    open_contradiction_count: int


class ErrorResponse(BaseSchema):
    detail: str
