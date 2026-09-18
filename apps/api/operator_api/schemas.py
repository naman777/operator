from datetime import datetime
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"


class MissionStatus(StrEnum):
    draft = "draft"
    queued = "queued"
    planning = "planning"
    extracting = "extracting"
    researching = "researching"
    matching = "matching"
    verifying = "verifying"
    awaiting_approval = "awaiting_approval"
    generating = "generating"
    updating_pipeline = "updating_pipeline"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class MissionInput(Contract):
    job_url: HttpUrl
    goal: str = Field(
        default="Assess fit and prepare an evidence-backed application pack", min_length=10, max_length=2000
    )
    budget_usd: float = Field(default=1.0, gt=0, le=10, allow_inf_nan=False)


class Source(Contract):
    id: str
    url: HttpUrl
    title: str
    excerpt: str
    retrieved_at: datetime | None = None
    synthetic: bool = False


class Requirement(Contract):
    id: str
    text: str
    category: Literal["skill", "experience", "education", "location", "authorization"]
    importance: Literal["required", "preferred"]
    source_id: str


class JobPosting(Contract):
    id: str
    title: str
    company: str
    url: HttpUrl
    location: str | None = None
    requirements: list[Requirement]
    sources: list[Source]
    synthetic: bool = False


class Evidence(Contract):
    id: str
    text: str
    document_id: str
    source_location: str
    skills: list[str]


class CandidateProfile(Contract):
    id: str
    name: str
    graduation_year: int = Field(ge=1900, le=2200)
    locations: list[str]
    skills: list[str]
    evidence: list[Evidence]
    synthetic: bool = False


class RequirementMatch(Contract):
    requirement_id: str
    status: Literal["supported", "partial", "missing"]
    evidence_ids: list[str]
    explanation: str


class MissionResult(Contract):
    mission_id: str
    eligibility: Literal["eligible", "ineligible", "unknown"]
    score: float = Field(ge=0, le=100)
    rubric_version: Literal["1.0"] = "1.0"
    matches: list[RequirementMatch]
    source_ids: list[str]
    artifact_ids: list[str]


class WorkspaceView(Contract):
    id: str
    name: str
    is_demo: bool


class GuestSession(Contract):
    token: str
    workspace: WorkspaceView


class MissionView(MissionInput):
    id: str
    workspace_id: str
    status: MissionStatus
    created_at: datetime


class EventView(Contract):
    id: str
    mission_id: str
    sequence: int
    type: str
    payload: dict
    created_at: datetime


class FailureSimulation(Contract):
    mode: Literal["transient", "exhausted"] = "transient"


class StepView(Contract):
    id: str
    name: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    attempt: int
    output: dict | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: int | None = None
    error: str | None = None


class RunView(Contract):
    mission: MissionView
    execution_mode: Literal["synthetic-fixture"] = "synthetic-fixture"
    run_number: int
    steps: list[StepView]
    result: MissionResult | None = None
