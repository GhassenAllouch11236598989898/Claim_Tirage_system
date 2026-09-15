"""
Pydantic models for the Claims Triage System.
Typed agent communication schemas for every stage of the pipeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────────

class ClaimCategory(str, Enum):
    INJURY = "injury"
    PROPERTY = "property"
    AUTO = "auto"
    UNKNOWN = "unknown"


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ClaimStatus(str, Enum):
    SUBMITTED = "submitted"
    CLASSIFYING = "classifying"
    SCORING = "scoring"
    REVIEWING = "reviewing"
    PENDING_HUMAN = "pending_human"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


# ── Input Models ───────────────────────────────────────────────────────────────

class ClaimInput(BaseModel):
    """Incoming insurance claim submission."""
    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str = Field(..., min_length=10, description="Detailed claim description")
    policy_number: str = Field(..., description="Insurance policy number")
    policy_limit: float = Field(..., gt=0, description="Maximum coverage amount")
    claimant_name: str = Field(..., description="Name of the claimant")
    incident_date: str = Field(..., description="Date of the incident (YYYY-MM-DD)")
    claimed_amount: float = Field(..., gt=0, description="Amount being claimed")
    supporting_info: Optional[str] = Field(None, description="Additional supporting information")

    class Config:
        json_schema_extra = {
            "example": {
                "description": "Vehicle rear-ended at intersection causing whiplash and bumper damage",
                "policy_number": "POL-2024-001234",
                "policy_limit": 100000.0,
                "claimant_name": "John Smith",
                "incident_date": "2024-11-15",
                "claimed_amount": 15000.0,
                "supporting_info": "Police report #PR-2024-5678 filed. Medical exam scheduled."
            }
        }


# ── Agent Output Models ────────────────────────────────────────────────────────

class ClassificationOutput(BaseModel):
    """Output from the Classifier agent."""
    category: ClaimCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    sub_category: Optional[str] = None
    keywords_detected: list[str] = Field(default_factory=list)


class SeverityOutput(BaseModel):
    """Output from the Severity Scorer agent."""
    severity: SeverityLevel
    estimated_payout: float = Field(..., ge=0.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_factors: list[str] = Field(default_factory=list)
    reasoning: str


class ReviewOutput(BaseModel):
    """Output from the Reviewer agent."""
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    recommendation: str
    flags: list[str] = Field(default_factory=list)
    requires_human_review: bool
    reasoning: str
    suggested_payout: Optional[float] = None


class HumanGateOutput(BaseModel):
    """Output from the Human Gate agent."""
    routed_to_human: bool
    reason: str
    auto_decision: Optional[str] = None
    final_payout: Optional[float] = None


# ── Trace / Logging Models ─────────────────────────────────────────────────────

class AgentStepTrace(BaseModel):
    """Individual step in the agent execution trace."""
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    latency_ms: Optional[float] = None
    tokens_used: int = 0
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    status: str = "started"
    error: Optional[str] = None


class ClaimTrace(BaseModel):
    """Complete trace for a claim's journey through the system."""
    claim_id: str
    status: ClaimStatus = ClaimStatus.SUBMITTED
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    steps: list[AgentStepTrace] = Field(default_factory=list)
    final_decision: Optional[str] = None
    final_payout: Optional[float] = None
    budget_remaining_tokens: int = 50000
    wall_clock_remaining_s: float = 300.0


# ── Budget Models ──────────────────────────────────────────────────────────────

class BudgetConfig(BaseModel):
    """Budget ceiling configuration."""
    max_tokens: int = 50000
    max_wall_clock_seconds: float = 300.0  # 5 minutes


class BudgetStatus(BaseModel):
    """Current budget usage."""
    tokens_used: int = 0
    tokens_remaining: int = 50000
    wall_clock_elapsed_s: float = 0.0
    wall_clock_remaining_s: float = 300.0
    budget_exceeded: bool = False
    exceeded_reason: Optional[str] = None


# ── Graph State ────────────────────────────────────────────────────────────────

class ClaimGraphState(BaseModel):
    """
    LangGraph state machine state.
    This is the single state object that flows through the entire graph.
    """
    # Core claim data
    claim: ClaimInput
    claim_id: str = ""

    # Agent outputs (populated as claim flows through)
    classification: Optional[ClassificationOutput] = None
    severity: Optional[SeverityOutput] = None
    review: Optional[ReviewOutput] = None
    human_gate: Optional[HumanGateOutput] = None

    # Status tracking
    status: ClaimStatus = ClaimStatus.SUBMITTED
    current_agent: str = "start"

    # Budget tracking
    budget: BudgetStatus = Field(default_factory=BudgetStatus)

    # Trace
    trace: ClaimTrace = None  # type: ignore[assignment]

    # Error handling
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2

    class Config:
        arbitrary_types_allowed = True


# ── API Request/Response Models ────────────────────────────────────────────────

class ClaimSubmissionRequest(BaseModel):
    """API request to submit a new claim."""
    description: str = Field(..., min_length=10)
    policy_number: str
    policy_limit: float = Field(..., gt=0)
    claimant_name: str
    incident_date: str
    claimed_amount: float = Field(..., gt=0)
    supporting_info: Optional[str] = None


class ClaimSubmissionResponse(BaseModel):
    """API response after submitting a claim."""
    claim_id: str
    status: ClaimStatus
    message: str


class ApprovalRequest(BaseModel):
    """API request for human approval decision."""
    decision: ApprovalDecision
    reviewer_name: str
    notes: Optional[str] = None


class ApprovalResponse(BaseModel):
    """API response after human approval."""
    claim_id: str
    decision: ApprovalDecision
    status: ClaimStatus
    message: str


class PendingApproval(BaseModel):
    """A claim waiting for human approval."""
    claim_id: str
    claimant_name: str
    description: str
    category: Optional[str] = None
    severity: Optional[str] = None
    estimated_payout: Optional[float] = None
    overall_confidence: Optional[float] = None
    reason_for_review: str
    submitted_at: datetime


class TraceResponse(BaseModel):
    """API response for claim trace."""
    claim_id: str
    status: ClaimStatus
    submitted_at: datetime
    completed_at: Optional[datetime] = None
    total_tokens: int
    total_latency_ms: float
    steps: list[AgentStepTrace]
    final_decision: Optional[str] = None
    final_payout: Optional[float] = None
