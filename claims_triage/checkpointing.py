"""
Redis checkpointing for the Claims Triage LangGraph state machine.
Enables crash recovery — restart and resume from the last checkpoint.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

import redis.asyncio as aioredis

from claims_triage.config import settings
from claims_triage.models import (
    ClaimGraphState, ClaimInput, ClaimTrace, BudgetStatus,
    ClassificationOutput, SeverityOutput, ReviewOutput, HumanGateOutput,
    ClaimStatus, AgentStepTrace,
)

logger = logging.getLogger(__name__)

CHECKPOINT_PREFIX = "claims_triage:checkpoint:"
CHECKPOINT_TTL = 86400  # 24 hours


class RedisCheckpointer:
    """
    Redis-backed checkpointing for crash recovery.
    Saves full graph state after every agent step.
    On restart, loads the last checkpoint and resumes from there.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.redis_url
        self._redis: Optional[aioredis.Redis] = None

    async def connect(self):
        """Connect to Redis."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            await self._redis.ping()
            logger.info(f"[CHECKPOINT] Connected to Redis at {settings.redis_host}:{settings.redis_port}")

    async def disconnect(self):
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    def _key(self, claim_id: str) -> str:
        return f"{CHECKPOINT_PREFIX}{claim_id}"

    async def save_checkpoint(self, state: ClaimGraphState):
        """
        Save a full state checkpoint to Redis.
        Called after every agent step for crash recovery.
        """
        await self.connect()

        data = self._serialize_state(state)
        key = self._key(state.claim_id)

        await self._redis.set(key, json.dumps(data), ex=CHECKPOINT_TTL)
        logger.info(
            f"[CHECKPOINT] Saved checkpoint for claim {state.claim_id} | "
            f"agent={state.current_agent} | status={state.status.value}"
        )

    async def load_checkpoint(self, claim_id: str) -> Optional[ClaimGraphState]:
        """
        Load the last checkpoint for a claim.
        Returns None if no checkpoint exists.
        """
        await self.connect()

        key = self._key(claim_id)
        raw = await self._redis.get(key)

        if raw is None:
            logger.info(f"[CHECKPOINT] No checkpoint found for claim {claim_id}")
            return None

        data = json.loads(raw)
        state = self._deserialize_state(data)
        logger.info(
            f"[CHECKPOINT] Loaded checkpoint for claim {claim_id} | "
            f"agent={state.current_agent} | status={state.status.value}"
        )
        return state

    async def delete_checkpoint(self, claim_id: str):
        """Delete a checkpoint after successful completion."""
        await self.connect()
        key = self._key(claim_id)
        await self._redis.delete(key)
        logger.info(f"[CHECKPOINT] Deleted checkpoint for claim {claim_id}")

    async def list_checkpoints(self) -> list[str]:
        """List all claim IDs with active checkpoints."""
        await self.connect()
        keys = await self._redis.keys(f"{CHECKPOINT_PREFIX}*")
        return [k.replace(CHECKPOINT_PREFIX, "") for k in keys]

    def _serialize_state(self, state: ClaimGraphState) -> dict[str, Any]:
        """Serialize state to a JSON-compatible dict."""
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

        # Serialize agent outputs
        if state.classification:
            data["classification"] = state.classification.model_dump()
        if state.severity:
            data["severity"] = state.severity.model_dump()
        if state.review:
            data["review"] = state.review.model_dump()
        if state.human_gate:
            data["human_gate"] = state.human_gate.model_dump()

        # Serialize trace
        if state.trace:
            trace_data = state.trace.model_dump()
            # Convert datetime objects
            trace_data["submitted_at"] = state.trace.submitted_at.isoformat()
            if state.trace.completed_at:
                trace_data["completed_at"] = state.trace.completed_at.isoformat()
            for step in trace_data.get("steps", []):
                if isinstance(step.get("started_at"), datetime):
                    step["started_at"] = step["started_at"].isoformat()
                if isinstance(step.get("completed_at"), datetime):
                    step["completed_at"] = step["completed_at"].isoformat()
            data["trace"] = trace_data

        return data

    def _deserialize_state(self, data: dict[str, Any]) -> ClaimGraphState:
        """Deserialize state from a JSON dict."""
        claim = ClaimInput(**data["claim"])

        # Deserialize trace
        trace = None
        if "trace" in data:
            trace_data = data["trace"]
            # Parse datetime strings
            trace_data["submitted_at"] = datetime.fromisoformat(trace_data["submitted_at"])
            if trace_data.get("completed_at"):
                trace_data["completed_at"] = datetime.fromisoformat(trace_data["completed_at"])
            steps = []
            for step_data in trace_data.get("steps", []):
                if isinstance(step_data.get("started_at"), str):
                    step_data["started_at"] = datetime.fromisoformat(step_data["started_at"])
                if isinstance(step_data.get("completed_at"), str):
                    step_data["completed_at"] = datetime.fromisoformat(step_data["completed_at"])
                steps.append(AgentStepTrace(**step_data))
            trace_data["steps"] = steps
            trace_data["status"] = ClaimStatus(trace_data["status"])
            trace = ClaimTrace(**trace_data)

        state = ClaimGraphState(
            claim=claim,
            claim_id=data["claim_id"],
            status=ClaimStatus(data["status"]),
            current_agent=data["current_agent"],
            error=data.get("error"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 2),
            budget=BudgetStatus(**data.get("budget", {})),
            trace=trace,
        )

        # Restore agent outputs
        if "classification" in data:
            state.classification = ClassificationOutput(**data["classification"])
        if "severity" in data:
            state.severity = SeverityOutput(**data["severity"])
        if "review" in data:
            state.review = ReviewOutput(**data["review"])
        if "human_gate" in data:
            state.human_gate = HumanGateOutput(**data["human_gate"])

        return state
