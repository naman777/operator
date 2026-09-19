from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


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


class EligibilityRequirements(Contract):
    graduation_year_min: int | None = Field(default=None, ge=1900, le=2200)
    graduation_year_max: int | None = Field(default=None, ge=1900, le=2200)
    experience_years_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    experience_years_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    accepted_work_authorizations: list[str] | None = None
    internship_start: date | None = None
    internship_end: date | None = None
    source_ids: list[str] = Field(default_factory=list)
    # Only set after all hard requirements have been reviewed against the cited source.
    requirements_complete: bool = False

    @model_validator(mode="after")
    def valid_ranges(self):
        for lower, upper in (
            (self.graduation_year_min, self.graduation_year_max),
            (self.experience_years_min, self.experience_years_max),
            (self.internship_start, self.internship_end),
        ):
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("Eligibility lower bound must not exceed upper bound")
        if self.accepted_work_authorizations == []:
            raise ValueError("Authorization alternatives must not be empty")
        return self


class JobPosting(Contract):
    id: str
    title: str
    company: str
    url: HttpUrl
    location: str | None = None
    requirements: list[Requirement]
    eligibility_requirements: EligibilityRequirements | None = None
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
    work_authorization: list[str] = Field(default_factory=list)
    experience_years: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    available_from: date | None = None
    available_until: date | None = None
    employment_type_preference: list[str] = Field(default_factory=list)
    evidence: list[Evidence]
    synthetic: bool = False
    # Records where structured fields (graduation_year, experience_years) were last set from.
    parse_source: Literal["synthetic", "user-correction", "heuristic-v1"] = "synthetic"


class RequirementMatch(Contract):
    requirement_id: str
    status: Literal["supported", "partial", "missing"]
    evidence_ids: list[str]
    explanation: str


class EligibilityCheck(Contract):
    check: str
    status: Literal["pass", "fail", "unknown"]
    detail: str
    candidate_value: str | None = None
    required_value: str | None = None


class MissionResult(Contract):
    mission_id: str
    eligibility: Literal["eligible", "ineligible", "unknown"]
    eligibility_checks: list[EligibilityCheck] = Field(default_factory=list)
    score: float = Field(ge=0, le=100)
    rubric_version: Literal["1.0"] = "1.0"
    matches: list[RequirementMatch]
    source_ids: list[str]
    artifact_ids: list[str]


class WorkspaceView(Contract):
    id: str
    name: str
    is_demo: bool
    expires_at: datetime | None = None


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
    execution_mode: Literal["synthetic-fixture", "public-snapshot"] = "synthetic-fixture"
    run_number: int
    steps: list[StepView]
    result: MissionResult | None = None


APPLICATION_STAGES = ("saved", "applied", "interview", "offer", "rejected")


class ApplicationView(Contract):
    id: str
    workspace_id: str
    opportunity_id: str
    mission_id: str | None = None
    stage: str
    fit_score: float | None = None
    company: str | None = None
    title: str | None = None
    job_url: str | None = None
    created_at: datetime
    updated_at: datetime


class StageUpdate(Contract):
    stage: Literal["saved", "applied", "interview", "offer", "rejected"]
    note: str | None = None


class ApprovalView(Contract):
    id: str
    mission_id: str
    workspace_id: str
    action_type: str
    proposed_payload: dict
    status: Literal["pending", "approved", "rejected"]
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    expires_at: datetime | None = None
    risk_level: Literal["low", "medium", "high"] = "medium"
    created_at: datetime


class ApprovalResolution(Contract):
    note: str | None = None


class ApprovalProposalUpdate(Contract):
    proposed_payload: dict


class ActionProposal(Contract):
    mission_id: str
    action_type: Literal["email_draft", "calendar_event"]
    proposed_payload: dict


class ExternalActionView(Contract):
    id: str
    workspace_id: str
    mission_id: str
    approval_id: str
    type: Literal["email_draft", "calendar_event"]
    payload: dict
    provider: Literal["mock"]
    status: Literal["created"]
    created_at: datetime


class ArtifactCitation(Contract):
    kind: Literal["candidate", "job"]
    reference_id: str
    excerpt: str
    document_id: str | None = None
    source_location: str | None = None
    url: HttpUrl | None = None
    requirement_ids: list[str] = Field(default_factory=list)


class ArtifactContent(Contract):
    generation_method: Literal["evidence-template-v1", "agents-sdk-v1"] = "evidence-template-v1"
    needs_review: Literal[True] = True
    text: str | None = None
    suggestions: list[str] = Field(default_factory=list)
    citations: list[ArtifactCitation] = Field(default_factory=list)


class ArtifactView(Contract):
    id: str
    mission_id: str
    workspace_id: str
    type: Literal["cover_letter", "resume_suggestions", "recruiter_message", "interview_brief"]
    version: int
    content: ArtifactContent
    status: Literal["draft", "final", "superseded"]
    superseded_by: str | None = None
    created_at: datetime


class ArtifactUpdate(Contract):
    """Body for PATCH /v1/artifacts/{id} — submit a revised draft."""

    expected_version: int = Field(ge=1)
    content: ArtifactContent


class ProfileUpdate(Contract):
    expected_version: int = Field(ge=0)
    profile: CandidateProfile


class ProfileState(Contract):
    version: int
    profile: CandidateProfile


class DocumentInput(Contract):
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=10, max_length=100000)


class DocumentReceipt(Contract):
    document_id: str
    evidence_count: int
    profile_version: int


class OpportunityImport(Contract):
    url: HttpUrl


class ImportReceipt(Contract):
    import_id: str
    posting: JobPosting
    screenshot_available: bool = False


class EvalRunRequest(Contract):
    dataset_version: Literal["opportunity-v1"] = "opportunity-v1"


class EvalMetrics(Contract):
    case_count: int = Field(ge=1)
    requirement_accuracy: float = Field(ge=0, le=1)
    score_mae: float = Field(ge=0, le=100)
    citation_coverage: float = Field(ge=0, le=1)
    unsupported_positive_rate: float = Field(ge=0, le=1)
    mean_latency_ms: float = Field(ge=0)


class EvalCaseResult(Contract):
    case_id: str
    job_title: str
    passed: bool
    expected_score: float
    actual_score: float
    requirement_accuracy: float
    citation_coverage: float
    unsupported_positive_count: int
    latency_ms: float


class EvalRunView(Contract):
    id: str
    workspace_id: str
    dataset_version: str
    evaluator_version: str
    metrics: EvalMetrics
    case_results: list[EvalCaseResult]
    created_at: datetime


class EvalComparison(Contract):
    baseline_id: str
    candidate_id: str
    deltas: dict[str, float]
    regression: bool
