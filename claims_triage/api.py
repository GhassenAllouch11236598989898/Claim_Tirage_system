"""
FastAPI Application for the Claims Triage System.

Endpoints:
  POST /claims              - Submit a new claim
  GET  /claims/{id}/trace   - View decision tree / trace
  GET  /pending_approvals   - Claims waiting for human approval
  POST /approve/{id}        - Human approval decision
  GET  /health              - Health check
  GET  /claims/{id}         - Get claim status
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from claims_triage.config import settings
from claims_triage.models import (
    ClaimInput, ClaimStatus, BudgetConfig,
    ClaimSubmissionRequest, ClaimSubmissionResponse,
    ApprovalRequest, ApprovalResponse, ApprovalDecision,
    PendingApproval, TraceResponse, AgentStepTrace,
)
from claims_triage.graph import execute_claim
from claims_triage.checkpointing import RedisCheckpointer
from claims_triage.database import (
    init_db, async_session_factory,
    get_claim, get_trace_steps, get_pending_approvals,
    resolve_approval, update_claim_status,
)

logger = logging.getLogger(__name__)

# ── Shared State ───────────────────────────────────────────────────────────────

checkpointer = RedisCheckpointer()
budget_config = BudgetConfig(
    max_tokens=settings.max_tokens,
    max_wall_clock_seconds=settings.max_wall_clock_seconds,
)


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    logger.info("Starting Claims Triage System...")

    # Init database
    await init_db()
    logger.info("Database initialized.")

    # Connect to Redis
    try:
        await checkpointer.connect()
        logger.info("Redis connected.")
    except Exception as e:
        logger.warning(f"Redis connection failed (checkpointing disabled): {e}")

    # Check for interrupted claims (crash recovery)
    try:
        interrupted = await checkpointer.list_checkpoints()
        if interrupted:
            logger.info(f"Found {len(interrupted)} interrupted claims: {interrupted}")
            for claim_id in interrupted:
                logger.info(f"Claim {claim_id} can be resumed via POST /claims/resume/{claim_id}")
    except Exception as e:
        logger.warning(f"Could not check for interrupted claims: {e}")

    yield

    # Shutdown
    await checkpointer.disconnect()
    logger.info("Claims Triage System shut down.")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Claims Triage System",
    description=(
        "Autonomous Multi-Agent Claims Triage System. "
        "Insurance claims flow through specialized AI agents for classification, "
        "severity scoring, review, and human approval routing."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Background Claim Processor ────────────────────────────────────────────────

async def _process_claim_background(claim: ClaimInput):
    """Process a claim through the graph in the background."""
    try:
        logger.info(f"[API] Processing claim {claim.claim_id} in background...")
        result = await execute_claim(
            claim=claim,
            budget_config=budget_config,
            checkpointer=checkpointer,
        )
        logger.info(
            f"[API] Claim {claim.claim_id} processed | "
            f"status={result.status.value} | tokens={result.budget.tokens_used}"
        )
    except Exception as e:
        logger.error(f"[API] Failed to process claim {claim.claim_id}: {e}")
        try:
            async with async_session_factory() as session:
                await update_claim_status(
                    session, claim.claim_id, "failed", error=str(e)
                )
        except Exception:
            pass


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    redis_ok = False
    try:
        await checkpointer.connect()
        redis_ok = True
    except Exception:
        pass

    return {
        "status": "healthy",
        "service": "claims-triage",
        "redis": "connected" if redis_ok else "disconnected",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/claims", response_model=ClaimSubmissionResponse, status_code=202)
async def submit_claim(request: ClaimSubmissionRequest, background_tasks: BackgroundTasks):
    """
    Submit a new insurance claim for triage.
    The claim is processed asynchronously through the agent pipeline.
    """
    claim = ClaimInput(
        description=request.description,
        policy_number=request.policy_number,
        policy_limit=request.policy_limit,
        claimant_name=request.claimant_name,
        incident_date=request.incident_date,
        claimed_amount=request.claimed_amount,
        supporting_info=request.supporting_info,
    )

    logger.info(
        f"[API] Claim submitted: {claim.claim_id} | "
        f"claimant={claim.claimant_name} | amount=${claim.claimed_amount:,.2f}"
    )

    # Process in background
    background_tasks.add_task(_process_claim_background, claim)

    return ClaimSubmissionResponse(
        claim_id=claim.claim_id,
        status=ClaimStatus.SUBMITTED,
        message="Claim submitted and processing started. Use GET /claims/{id}/trace to monitor progress.",
    )


@app.get("/claims/{claim_id}/trace", response_model=TraceResponse)
async def get_claim_trace(claim_id: str):
    """
    View the complete decision trace for a claim.
    Shows every agent step with latency, tokens, and reasoning.
    """
    async with async_session_factory() as session:
        claim = await get_claim(session, claim_id)
        if not claim:
            raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")

        trace_steps = await get_trace_steps(session, claim_id)

        steps = []
        for step in trace_steps:
            steps.append(AgentStepTrace(
                step_id=step.step_id,
                agent_name=step.agent_name,
                started_at=step.started_at,
                completed_at=step.completed_at,
                latency_ms=step.latency_ms,
                tokens_used=step.tokens_used,
                input_data=step.input_data or {},
                output_data=step.output_data or {},
                reasoning=step.reasoning or "",
                status=step.status or "unknown",
                error=step.error,
            ))

        return TraceResponse(
            claim_id=claim.claim_id,
            status=ClaimStatus(claim.status),
            submitted_at=claim.submitted_at,
            completed_at=claim.completed_at,
            total_tokens=claim.total_tokens or 0,
            total_latency_ms=claim.total_latency_ms or 0,
            steps=steps,
            final_decision=claim.final_decision,
            final_payout=claim.final_payout,
        )


@app.get("/pending_approvals", response_model=list[PendingApproval])
async def list_pending_approvals():
    """
    List all claims waiting for human approval.
    Claims are routed here when severity=high OR confidence<0.8.
    """
    async with async_session_factory() as session:
        approvals = await get_pending_approvals(session)

    return [
        PendingApproval(
            claim_id=a["claim_id"],
            claimant_name=a["claimant_name"],
            description=a["description"],
            category=a.get("category"),
            severity=a.get("severity"),
            estimated_payout=a.get("estimated_payout"),
            overall_confidence=a.get("overall_confidence"),
            reason_for_review=a["reason_for_review"],
            submitted_at=datetime.fromisoformat(a["submitted_at"]) if a.get("submitted_at") else datetime.utcnow(),
        )
        for a in approvals
    ]


@app.post("/approve/{claim_id}", response_model=ApprovalResponse)
async def approve_claim(claim_id: str, request: ApprovalRequest):
    """
    Submit a human approval decision for a pending claim.
    """
    async with async_session_factory() as session:
        claim = await get_claim(session, claim_id)
        if not claim:
            raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")

        if claim.status != "pending_human":
            raise HTTPException(
                status_code=400,
                detail=f"Claim {claim_id} is not pending approval (status: {claim.status})"
            )

        approval = await resolve_approval(
            session,
            claim_id,
            decision=request.decision.value,
            reviewer_name=request.reviewer_name,
            notes=request.notes,
        )

        if not approval:
            raise HTTPException(
                status_code=404,
                detail=f"No pending approval found for claim {claim_id}"
            )

    # Clean up checkpoint
    try:
        await checkpointer.delete_checkpoint(claim_id)
    except Exception:
        pass

    new_status = ClaimStatus.APPROVED if request.decision == ApprovalDecision.APPROVE else ClaimStatus.REJECTED

    return ApprovalResponse(
        claim_id=claim_id,
        decision=request.decision,
        status=new_status,
        message=f"Claim {claim_id} has been {request.decision.value}d by {request.reviewer_name}.",
    )


@app.get("/claims/{claim_id}")
async def get_claim_status(claim_id: str):
    """Get the current status of a claim."""
    async with async_session_factory() as session:
        claim = await get_claim(session, claim_id)
        if not claim:
            raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")

        return {
            "claim_id": claim.claim_id,
            "status": claim.status,
            "claimant_name": claim.claimant_name,
            "claimed_amount": claim.claimed_amount,
            "current_agent": claim.current_agent,
            "total_tokens": claim.total_tokens,
            "total_latency_ms": claim.total_latency_ms,
            "classification": claim.classification_output,
            "severity": claim.severity_output,
            "review": claim.review_output,
            "human_gate": claim.human_gate_output,
            "final_decision": claim.final_decision,
            "final_payout": claim.final_payout,
            "error": claim.error,
            "submitted_at": claim.submitted_at.isoformat() if claim.submitted_at else None,
            "completed_at": claim.completed_at.isoformat() if claim.completed_at else None,
        }


@app.post("/claims/resume/{claim_id}")
async def resume_claim(claim_id: str, background_tasks: BackgroundTasks):
    """
    Resume a previously interrupted claim from its last checkpoint.
    Used for crash recovery.
    """
    state = await checkpointer.load_checkpoint(claim_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail=f"No checkpoint found for claim {claim_id}"
        )

    logger.info(
        f"[API] Resuming claim {claim_id} from agent={state.current_agent}"
    )

    background_tasks.add_task(_process_claim_background, state.claim)

    return {
        "claim_id": claim_id,
        "message": f"Claim resumed from last checkpoint (agent={state.current_agent})",
        "status": state.status.value,
    }


@app.get("/checkpoints")
async def list_active_checkpoints():
    """List all claims with active checkpoints (interrupted/in-progress)."""
    try:
        checkpoints = await checkpointer.list_checkpoints()
        return {"checkpoints": checkpoints, "count": len(checkpoints)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {e}")


# ── Static Dashboard Mount ───────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_dashboard():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/styles.css", include_in_schema=False)
    async def serve_css():
        return FileResponse(STATIC_DIR / "styles.css")

    @app.get("/app.js", include_in_schema=False)
    async def serve_js():
        return FileResponse(STATIC_DIR / "app.js")

