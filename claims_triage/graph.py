"""
LangGraph State Machine for the Claims Triage System.
Proper directed graph with conditional edges, checkpointing, and budget enforcement.

Graph flow:
  START → classifier → severity_scorer → reviewer → human_gate → END
                                                          ↓
                                                   (if high severity or low confidence)
                                                          ↓
                                                  PENDING_HUMAN → (wait for approval) → END
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from langgraph.graph import StateGraph, END

from claims_triage.models import (
    ClaimGraphState, ClaimInput, ClaimTrace, ClaimStatus,
    BudgetConfig, BudgetStatus,
)
from claims_triage.agents import (
    classifier_agent, severity_agent, reviewer_agent, human_gate_agent,
)
from claims_triage.budget import BudgetEnforcer, BudgetExceededError
from claims_triage.checkpointing import RedisCheckpointer
from claims_triage.database import (
    async_session_factory, save_claim, update_claim_status,
    save_trace_step, create_approval,
)
from claims_triage.tracing import StepTracer

logger = logging.getLogger(__name__)


# ── Graph Node Wrappers ───────────────────────────────────────────────────────
# LangGraph nodes receive and return the state dict.
# We wrap our agents to handle checkpointing and persistence.


def build_claims_graph(
    budget_config: BudgetConfig | None = None,
    checkpointer: RedisCheckpointer | None = None,
) -> tuple[StateGraph, BudgetEnforcer, RedisCheckpointer]:
    """
    Build the LangGraph state machine for claims triage.
    Returns (compiled_graph, budget_enforcer, checkpointer).
    """

    budget = BudgetEnforcer(budget_config)
    if checkpointer is None:
        checkpointer = RedisCheckpointer()

    # ── Node functions ─────────────────────────────────────────────────────

    async def classify_node(state: dict[str, Any]) -> dict[str, Any]:
        """Classifier agent node."""
        graph_state = _dict_to_state(state)
        graph_state = await classifier_agent(graph_state, budget)
        await _checkpoint_and_persist(graph_state, checkpointer, "classifier")
        return _state_to_dict(graph_state)

    async def severity_node(state: dict[str, Any]) -> dict[str, Any]:
        """Severity scorer agent node."""
        graph_state = _dict_to_state(state)
        graph_state = await severity_agent(graph_state, budget)
        await _checkpoint_and_persist(graph_state, checkpointer, "severity_scorer")
        return _state_to_dict(graph_state)

    async def review_node(state: dict[str, Any]) -> dict[str, Any]:
        """Reviewer agent node."""
        graph_state = _dict_to_state(state)
        graph_state = await reviewer_agent(graph_state, budget)
        await _checkpoint_and_persist(graph_state, checkpointer, "reviewer")
        return _state_to_dict(graph_state)

    async def human_gate_node(state: dict[str, Any]) -> dict[str, Any]:
        """Human gate agent node."""
        graph_state = _dict_to_state(state)
        graph_state = await human_gate_agent(graph_state, budget)
        await _checkpoint_and_persist(graph_state, checkpointer, "human_gate")
        return _state_to_dict(graph_state)

    async def budget_exceeded_node(state: dict[str, Any]) -> dict[str, Any]:
        """Handle budget exceeded — terminate gracefully."""
        graph_state = _dict_to_state(state)
        graph_state.status = ClaimStatus.BUDGET_EXCEEDED
        graph_state.error = "Budget ceiling exceeded"
        if graph_state.trace:
            graph_state.trace.completed_at = datetime.utcnow()
        await _checkpoint_and_persist(graph_state, checkpointer, "budget_exceeded")
        return _state_to_dict(graph_state)

    async def complete_node(state: dict[str, Any]) -> dict[str, Any]:
        """Finalize the claim after auto-approval."""
        graph_state = _dict_to_state(state)
        if graph_state.trace:
            graph_state.trace.completed_at = datetime.utcnow()
            graph_state.trace.final_decision = "auto_approved"
            if graph_state.human_gate and graph_state.human_gate.final_payout is not None:
                graph_state.trace.final_payout = graph_state.human_gate.final_payout
        await _checkpoint_and_persist(graph_state, checkpointer, "complete")
        await checkpointer.delete_checkpoint(graph_state.claim_id)
        return _state_to_dict(graph_state)

    async def pending_human_node(state: dict[str, Any]) -> dict[str, Any]:
        """Route to human approval queue."""
        graph_state = _dict_to_state(state)
        reason = graph_state.human_gate.reason if graph_state.human_gate else "Unknown reason"

        # Create approval record in DB
        try:
            async with async_session_factory() as session:
                await create_approval(session, graph_state.claim_id, reason)
        except Exception as e:
            logger.error(f"Failed to create approval record: {e}")

        await _checkpoint_and_persist(graph_state, checkpointer, "pending_human")
        return _state_to_dict(graph_state)

    # ── Conditional edge functions ─────────────────────────────────────────

    def route_after_human_gate(state: dict[str, Any]) -> str:
        """Route based on human gate decision."""
        human_gate = state.get("human_gate")
        if human_gate and human_gate.get("routed_to_human"):
            return "pending_human"
        return "complete"

    def check_budget_before_step(state: dict[str, Any]) -> str:
        """Check budget before proceeding to the next step."""
        budget_data = state.get("budget", {})
        if budget_data.get("budget_exceeded"):
            return "budget_exceeded"
        return "continue"

    # ── Build the graph ────────────────────────────────────────────────────

    # LangGraph StateGraph uses dict-based state
    graph = StateGraph(dict)

    # Add nodes
    graph.add_node("classify", classify_node)
    graph.add_node("severity", severity_node)
    graph.add_node("review", review_node)
    graph.add_node("human_gate", human_gate_node)
    graph.add_node("complete", complete_node)
    graph.add_node("pending_human", pending_human_node)
    graph.add_node("budget_exceeded", budget_exceeded_node)

    # Set entry point
    graph.set_entry_point("classify")

    # Add edges (linear flow with conditional branching at human_gate)
    graph.add_edge("classify", "severity")
    graph.add_edge("severity", "review")
    graph.add_edge("review", "human_gate")

    # Conditional: human_gate → complete OR pending_human
    graph.add_conditional_edges(
        "human_gate",
        route_after_human_gate,
        {
            "complete": "complete",
            "pending_human": "pending_human",
        },
    )

    # Terminal nodes
    graph.add_edge("complete", END)
    graph.add_edge("pending_human", END)
    graph.add_edge("budget_exceeded", END)

    compiled = graph.compile()
    return compiled, budget, checkpointer


# ── Helper Functions ───────────────────────────────────────────────────────────

def _state_to_dict(state: ClaimGraphState) -> dict[str, Any]:
    """Convert Pydantic state to LangGraph-compatible dict."""
    data = {
        "claim": state.claim.model_dump(),
        "claim_id": state.claim_id,
        "status": state.status.value,
        "current_agent": state.current_agent,
        "error": state.error,
        "retry_count": state.retry_count,
        "max_retries": state.max_retries,
        "budget": state.budget.model_dump(),
    }

    if state.classification:
        data["classification"] = state.classification.model_dump()
    if state.severity:
        data["severity"] = state.severity.model_dump()
    if state.review:
        data["review"] = state.review.model_dump()
    if state.human_gate:
        data["human_gate"] = state.human_gate.model_dump()

    if state.trace:
        trace_dict = {
            "claim_id": state.trace.claim_id,
            "status": state.trace.status.value,
            "submitted_at": state.trace.submitted_at.isoformat(),
            "completed_at": state.trace.completed_at.isoformat() if state.trace.completed_at else None,
            "total_tokens": state.trace.total_tokens,
            "total_latency_ms": state.trace.total_latency_ms,
            "final_decision": state.trace.final_decision,
            "final_payout": state.trace.final_payout,
            "budget_remaining_tokens": state.trace.budget_remaining_tokens,
            "wall_clock_remaining_s": state.trace.wall_clock_remaining_s,
            "steps": [s.model_dump() for s in state.trace.steps],
        }
        data["trace"] = trace_dict

    return data


def _dict_to_state(data: dict[str, Any]) -> ClaimGraphState:
    """Convert LangGraph dict back to Pydantic state."""
    from claims_triage.models import (
        ClaimInput, ClassificationOutput, SeverityOutput, ReviewOutput,
        HumanGateOutput, ClaimTrace, AgentStepTrace, BudgetStatus, ClaimStatus,
    )

    claim = ClaimInput(**data["claim"]) if isinstance(data.get("claim"), dict) else data.get("claim")

    state = ClaimGraphState(
        claim=claim,
        claim_id=data.get("claim_id", ""),
        status=ClaimStatus(data.get("status", "submitted")),
        current_agent=data.get("current_agent", "start"),
        error=data.get("error"),
        retry_count=data.get("retry_count", 0),
        max_retries=data.get("max_retries", 2),
        budget=BudgetStatus(**data["budget"]) if isinstance(data.get("budget"), dict) else BudgetStatus(),
    )

    if isinstance(data.get("classification"), dict):
        state.classification = ClassificationOutput(**data["classification"])
    if isinstance(data.get("severity"), dict):
        state.severity = SeverityOutput(**data["severity"])
    if isinstance(data.get("review"), dict):
        state.review = ReviewOutput(**data["review"])
    if isinstance(data.get("human_gate"), dict):
        state.human_gate = HumanGateOutput(**data["human_gate"])

    if isinstance(data.get("trace"), dict):
        trace_data = data["trace"]
        steps = []
        for s in trace_data.get("steps", []):
            if isinstance(s, dict):
                if isinstance(s.get("started_at"), str):
                    s["started_at"] = datetime.fromisoformat(s["started_at"])
                if isinstance(s.get("completed_at"), str):
                    s["completed_at"] = datetime.fromisoformat(s["completed_at"])
                steps.append(AgentStepTrace(**s))
            else:
                steps.append(s)

        submitted_at = trace_data.get("submitted_at")
        if isinstance(submitted_at, str):
            submitted_at = datetime.fromisoformat(submitted_at)
        completed_at = trace_data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        state.trace = ClaimTrace(
            claim_id=trace_data["claim_id"],
            status=ClaimStatus(trace_data.get("status", "submitted")),
            submitted_at=submitted_at or datetime.utcnow(),
            completed_at=completed_at,
            total_tokens=trace_data.get("total_tokens", 0),
            total_latency_ms=trace_data.get("total_latency_ms", 0),
            steps=steps,
            final_decision=trace_data.get("final_decision"),
            final_payout=trace_data.get("final_payout"),
            budget_remaining_tokens=trace_data.get("budget_remaining_tokens", 50000),
            wall_clock_remaining_s=trace_data.get("wall_clock_remaining_s", 300),
        )

    return state


async def _checkpoint_and_persist(
    state: ClaimGraphState,
    checkpointer: RedisCheckpointer,
    agent_name: str,
):
    """Save checkpoint to Redis and persist state to PostgreSQL."""
    try:
        await checkpointer.save_checkpoint(state)
    except Exception as e:
        logger.error(f"Failed to save checkpoint for {state.claim_id}: {e}")

    # Persist to DB
    try:
        async with async_session_factory() as session:
            claim_data = {
                "claim_id": state.claim_id,
                "description": state.claim.description,
                "policy_number": state.claim.policy_number,
                "policy_limit": state.claim.policy_limit,
                "claimant_name": state.claim.claimant_name,
                "incident_date": state.claim.incident_date,
                "claimed_amount": state.claim.claimed_amount,
                "supporting_info": state.claim.supporting_info,
                "status": state.status.value,
                "current_agent": state.current_agent,
                "total_tokens": state.budget.tokens_used,
                "total_latency_ms": state.trace.total_latency_ms if state.trace else 0,
            }

            if state.classification:
                claim_data["classification_output"] = state.classification.model_dump()
            if state.severity:
                claim_data["severity_output"] = state.severity.model_dump()
            if state.review:
                claim_data["review_output"] = state.review.model_dump()
            if state.human_gate:
                claim_data["human_gate_output"] = state.human_gate.model_dump()
            if state.status in (ClaimStatus.COMPLETED, ClaimStatus.APPROVED, ClaimStatus.REJECTED):
                claim_data["completed_at"] = datetime.utcnow()
            if state.error:
                claim_data["error"] = state.error

            await save_claim(session, claim_data)

            # Save trace steps
            if state.trace and state.trace.steps:
                latest_step = state.trace.steps[-1]
                await save_trace_step(session, {
                    "step_id": latest_step.step_id,
                    "claim_id": state.claim_id,
                    "agent_name": latest_step.agent_name,
                    "started_at": latest_step.started_at,
                    "completed_at": latest_step.completed_at,
                    "latency_ms": latest_step.latency_ms,
                    "tokens_used": latest_step.tokens_used,
                    "input_data": latest_step.input_data,
                    "output_data": latest_step.output_data,
                    "reasoning": latest_step.reasoning,
                    "status": latest_step.status,
                    "error": latest_step.error,
                })
    except Exception as e:
        logger.error(f"Failed to persist state for {state.claim_id}: {e}")


# ── Graph Executor ─────────────────────────────────────────────────────────────

async def execute_claim(
    claim: ClaimInput,
    budget_config: BudgetConfig | None = None,
    checkpointer: RedisCheckpointer | None = None,
) -> ClaimGraphState:
    """
    Execute a claim through the full triage graph.

    1. Check for existing checkpoint (crash recovery)
    2. Build graph
    3. Run through all agents
    4. Return final state
    """

    compiled_graph, budget, ckpt = build_claims_graph(budget_config, checkpointer)

    # Check for crash recovery
    existing_state = await ckpt.load_checkpoint(claim.claim_id)

    if existing_state:
        logger.info(
            f"[GRAPH] Resuming claim {claim.claim_id} from checkpoint | "
            f"last_agent={existing_state.current_agent}"
        )
        # Determine which node to resume from
        initial_state = _state_to_dict(existing_state)
        resume_node = _get_resume_node(existing_state.current_agent)
        logger.info(f"[GRAPH] Will resume from node: {resume_node}")
    else:
        # Fresh start
        logger.info(f"[GRAPH] Starting new claim {claim.claim_id}")
        trace = ClaimTrace(
            claim_id=claim.claim_id,
            status=ClaimStatus.SUBMITTED,
        )
        graph_state = ClaimGraphState(
            claim=claim,
            claim_id=claim.claim_id,
            trace=trace,
        )
        initial_state = _state_to_dict(graph_state)

    # Start budget tracking
    budget.start_tracking(claim.claim_id)

    try:
        # Run the graph
        result = await compiled_graph.ainvoke(initial_state)

        # Convert back to Pydantic
        final_state = _dict_to_state(result)

        logger.info(
            f"[GRAPH] Claim {claim.claim_id} completed | "
            f"status={final_state.status.value} | "
            f"tokens={final_state.budget.tokens_used}"
        )

        return final_state

    except BudgetExceededError as e:
        logger.warning(f"[GRAPH] Budget exceeded for claim {claim.claim_id}: {e}")
        # Load latest state from checkpoint
        state = await ckpt.load_checkpoint(claim.claim_id)
        if state:
            state.status = ClaimStatus.BUDGET_EXCEEDED
            state.error = str(e)
            if state.trace:
                state.trace.completed_at = datetime.utcnow()
            await _checkpoint_and_persist(state, ckpt, "budget_exceeded")
            return state
        raise

    except Exception as e:
        logger.error(f"[GRAPH] Error processing claim {claim.claim_id}: {e}")
        state = await ckpt.load_checkpoint(claim.claim_id)
        if state:
            state.status = ClaimStatus.FAILED
            state.error = str(e)
            await _checkpoint_and_persist(state, ckpt, "error")
            return state
        raise

    finally:
        budget.stop_tracking(claim.claim_id)


def _get_resume_node(last_agent: str) -> str:
    """Determine which node to resume from after a crash."""
    agent_order = ["start", "classifier", "severity_scorer", "reviewer", "human_gate"]
    try:
        idx = agent_order.index(last_agent)
        if idx + 1 < len(agent_order):
            return agent_order[idx + 1]
    except ValueError:
        pass
    return "classify"  # Default to start
