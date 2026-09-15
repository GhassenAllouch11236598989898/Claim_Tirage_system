"""
Database layer for the Claims Triage System.
PostgreSQL via SQLAlchemy for approvals, traces, and claim persistence.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, String, Float, Integer, Text, DateTime, Boolean, JSON,
    create_engine, text
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.asyncio import async_sessionmaker

from claims_triage.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()


# ── ORM Models ─────────────────────────────────────────────────────────────────

class ClaimRecord(Base):
    """Persistent claim record in PostgreSQL."""
    __tablename__ = "claims"

    claim_id = Column(String, primary_key=True)
    description = Column(Text, nullable=False)
    policy_number = Column(String, nullable=False)
    policy_limit = Column(Float, nullable=False)
    claimant_name = Column(String, nullable=False)
    incident_date = Column(String, nullable=False)
    claimed_amount = Column(Float, nullable=False)
    supporting_info = Column(Text, nullable=True)

    # Status
    status = Column(String, default="submitted")
    current_agent = Column(String, default="start")
    submitted_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Agent outputs (stored as JSON)
    classification_output = Column(JSON, nullable=True)
    severity_output = Column(JSON, nullable=True)
    review_output = Column(JSON, nullable=True)
    human_gate_output = Column(JSON, nullable=True)

    # Final decision
    final_decision = Column(String, nullable=True)
    final_payout = Column(Float, nullable=True)

    # Budget
    total_tokens = Column(Integer, default=0)
    total_latency_ms = Column(Float, default=0.0)

    # Error
    error = Column(Text, nullable=True)


class TraceRecord(Base):
    """Step-level trace record for agent decisions."""
    __tablename__ = "traces"

    step_id = Column(String, primary_key=True)
    claim_id = Column(String, nullable=False, index=True)
    agent_name = Column(String, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    latency_ms = Column(Float, nullable=True)
    tokens_used = Column(Integer, default=0)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    reasoning = Column(Text, default="")
    status = Column(String, default="started")
    error = Column(Text, nullable=True)


class ApprovalRecord(Base):
    """Human approval record."""
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String, nullable=False, index=True)
    decision = Column(String, nullable=True)  # approve/reject
    reviewer_name = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    reason_for_review = Column(Text, nullable=False)
    routed_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    is_pending = Column(Boolean, default=True)


# ── Engine & Session ───────────────────────────────────────────────────────────

async_engine = create_async_engine(settings.postgres_url, echo=settings.debug, pool_pre_ping=True)
async_session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create all tables."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully.")


async def get_session() -> AsyncSession:
    """Get a new async session."""
    async with async_session_factory() as session:
        yield session


# ── CRUD Operations ───────────────────────────────────────────────────────────

async def save_claim(session: AsyncSession, claim_data: dict):
    """Save or update a claim record."""
    existing = await session.get(ClaimRecord, claim_data["claim_id"])
    if existing:
        for key, value in claim_data.items():
            setattr(existing, key, value)
    else:
        record = ClaimRecord(**claim_data)
        session.add(record)
    await session.commit()


async def get_claim(session: AsyncSession, claim_id: str) -> Optional[ClaimRecord]:
    """Get a claim by ID."""
    return await session.get(ClaimRecord, claim_id)


async def update_claim_status(session: AsyncSession, claim_id: str, status: str, **kwargs):
    """Update claim status and optional fields."""
    record = await session.get(ClaimRecord, claim_id)
    if record:
        record.status = status
        for key, value in kwargs.items():
            if hasattr(record, key):
                setattr(record, key, value)
        await session.commit()
    return record


async def save_trace_step(session: AsyncSession, trace_data: dict):
    """Save a trace step record."""
    record = TraceRecord(**trace_data)
    session.add(record)
    await session.commit()


async def get_trace_steps(session: AsyncSession, claim_id: str) -> list[TraceRecord]:
    """Get all trace steps for a claim."""
    from sqlalchemy import select
    result = await session.execute(
        select(TraceRecord).where(TraceRecord.claim_id == claim_id).order_by(TraceRecord.started_at)
    )
    return result.scalars().all()


async def create_approval(session: AsyncSession, claim_id: str, reason: str):
    """Create a pending approval record."""
    record = ApprovalRecord(
        claim_id=claim_id,
        reason_for_review=reason,
    )
    session.add(record)
    await session.commit()
    return record


async def get_pending_approvals(session: AsyncSession) -> list[dict]:
    """Get all pending human approvals with claim details."""
    from sqlalchemy import select
    result = await session.execute(
        select(ApprovalRecord, ClaimRecord)
        .join(ClaimRecord, ApprovalRecord.claim_id == ClaimRecord.claim_id)
        .where(ApprovalRecord.is_pending == True)
        .order_by(ApprovalRecord.routed_at)
    )
    approvals = []
    for approval, claim in result.all():
        approvals.append({
            "claim_id": claim.claim_id,
            "claimant_name": claim.claimant_name,
            "description": claim.description,
            "category": (json.loads(claim.classification_output) if isinstance(claim.classification_output, str) else claim.classification_output or {}).get("category"),
            "severity": (json.loads(claim.severity_output) if isinstance(claim.severity_output, str) else claim.severity_output or {}).get("severity"),
            "estimated_payout": (json.loads(claim.severity_output) if isinstance(claim.severity_output, str) else claim.severity_output or {}).get("estimated_payout"),
            "overall_confidence": (json.loads(claim.review_output) if isinstance(claim.review_output, str) else claim.review_output or {}).get("overall_confidence"),
            "reason_for_review": approval.reason_for_review,
            "submitted_at": claim.submitted_at.isoformat() if claim.submitted_at else None,
        })
    return approvals


async def resolve_approval(session: AsyncSession, claim_id: str, decision: str, reviewer_name: str, notes: str = None):
    """Resolve a pending approval."""
    from sqlalchemy import select, update
    # Update approval record
    result = await session.execute(
        select(ApprovalRecord).where(
            ApprovalRecord.claim_id == claim_id,
            ApprovalRecord.is_pending == True
        )
    )
    approval = result.scalar_one_or_none()
    if not approval:
        return None

    approval.decision = decision
    approval.reviewer_name = reviewer_name
    approval.notes = notes
    approval.decided_at = datetime.utcnow()
    approval.is_pending = False

    # Update claim status
    new_status = "approved" if decision == "approve" else "rejected"
    claim = await session.get(ClaimRecord, claim_id)
    if claim:
        claim.status = new_status
        claim.completed_at = datetime.utcnow()
        claim.final_decision = decision

    await session.commit()
    return approval
