"""Pydantic v2 Schemas for TRACE.

These schemas mirror the API Contract exactly.
All JSON contract examples and endpoint responses validate against these models.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, RootModel

# Enumerations / Literal Types
AccessLabel = Literal["public", "internal", "restricted"]
Clearance = Literal["public", "internal", "restricted"]
SourceType = Literal["git", "pr", "task", "note", "chat", "doc"]
ClaimType = Literal[
    "state",
    "decision",
    "task",
    "blocker",
    "dependency",
    "ownership",
    "contradiction",
    "open_loop",
    "gap",
]
ClaimStatus = Literal["verified", "inferred", "conflicting", "missing"]
ReviewState = Literal["pending", "accepted", "edited", "rejected"]
ReviewAction = Literal["accept", "edit", "reject"]
HandoverStatus = Literal["draft", "approved"]


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Project(BaseSchema):
    id: str
    name: str
    description: Optional[str] = None


class Role(BaseSchema):
    id: str
    name: str
    clearance: Clearance


class Source(BaseSchema):
    id: str
    project_id: str
    type: SourceType
    title: str
    origin_ref: str
    access_label: AccessLabel
    created_at: Optional[datetime | str] = None


class ActivityItem(BaseSchema):
    id: str
    source_id: str
    kind: str
    author: Optional[str] = None
    timestamp: Optional[datetime | str] = None
    text: str
    ref: Optional[str] = None
    access_label: AccessLabel


class Evidence(BaseSchema):
    id: Optional[str] = None
    claim_id: Optional[str] = None
    activity_item_id: Optional[str] = None
    source_id: str
    source_title: Optional[str] = None
    quote: str = Field(..., max_length=200)
    locator: str


class Claim(BaseSchema):
    id: str
    project_id: Optional[str] = None
    type: ClaimType
    statement: str
    status: ClaimStatus
    confidence_note: Optional[str] = None
    owner: Optional[str] = None
    access_label: AccessLabel
    review_state: ReviewState = "pending"
    created_at: Optional[datetime | str] = None
    evidence: List[Evidence] = Field(default_factory=list)


class GapQuestion(BaseSchema):
    id: str
    claim_id: str
    question: str
    answer: Optional[str] = None
    answered_by: Optional[str] = None
    answered_at: Optional[datetime | str] = None


class Review(BaseSchema):
    id: str
    claim_id: str
    action: ReviewAction
    edited_statement: Optional[str] = None
    reviewer: str
    version: int = 1
    created_at: Optional[datetime | str] = None


class Handover(BaseSchema):
    id: str
    project_id: str
    version: int = 1
    status: HandoverStatus = "draft"
    approved_by: Optional[str] = None
    approved_at: Optional[datetime | str] = None
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime | str] = None
    created_at: Optional[datetime | str] = None
    claims: List[Claim] = Field(default_factory=list)


class RoleView(BaseSchema):
    role: str
    clearance: Clearance
    handover: Handover
    hidden_count: int = 0


class RoleViewsMap(RootModel[Dict[str, RoleView]]):
    pass


class PlanStep(BaseSchema):
    id: str
    handover_id: Optional[str] = None
    rank: int
    action: str
    reason: str
    claim_ids: List[str] = Field(default_factory=list)


class PlanStepList(RootModel[List[PlanStep]]):
    pass


class GapQuestionList(RootModel[List[GapQuestion]]):
    pass


class HealthResponse(BaseSchema):
    status: str = "ok"


class ContractDoc(BaseSchema):
    version: str
    description: str
    models: Dict[str, Any]
    current_endpoints: List[Dict[str, Any]]
    planned_endpoints: List[Dict[str, Any]]
