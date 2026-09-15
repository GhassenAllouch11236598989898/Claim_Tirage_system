"""
Step-level tracing for the Claims Triage System.
Logs every decision with latency, tokens, and reasoning.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Optional

from claims_triage.models import AgentStepTrace, ClaimGraphState

logger = logging.getLogger(__name__)


class StepTracer:
    """
    Context manager for tracing individual agent steps.
    Logs start/end, latency, tokens, input/output, and reasoning.
    """

    def __init__(self, state: ClaimGraphState, agent_name: str):
        self.state = state
        self.agent_name = agent_name
        self.step = AgentStepTrace(
            agent_name=agent_name,
            started_at=datetime.utcnow(),
        )
        self._start_time: float = 0.0

    def __enter__(self) -> "StepTracer":
        self._start_time = time.monotonic()
        self.step.status = "running"
        logger.info(f"[TRACE] [{self.state.claim_id}] Agent '{self.agent_name}' STARTED")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.monotonic() - self._start_time
        self.step.completed_at = datetime.utcnow()
        self.step.latency_ms = round(elapsed * 1000, 2)

        if exc_type:
            self.step.status = "error"
            self.step.error = str(exc_val)
            logger.error(
                f"[TRACE] [{self.state.claim_id}] Agent '{self.agent_name}' FAILED "
                f"after {self.step.latency_ms}ms: {exc_val}"
            )
        else:
            self.step.status = "completed"
            logger.info(
                f"[TRACE] [{self.state.claim_id}] Agent '{self.agent_name}' COMPLETED "
                f"in {self.step.latency_ms}ms | tokens={self.step.tokens_used}"
            )

        # Append to state trace
        if self.state.trace:
            self.state.trace.steps.append(self.step)
            self.state.trace.total_tokens += self.step.tokens_used
            self.state.trace.total_latency_ms += self.step.latency_ms

        return False  # Don't suppress exceptions

    def set_input(self, data: dict[str, Any]):
        """Record input data for this step."""
        self.step.input_data = data

    def set_output(self, data: dict[str, Any]):
        """Record output data for this step."""
        self.step.output_data = data

    def set_reasoning(self, reasoning: str):
        """Record the reasoning for this step."""
        self.step.reasoning = reasoning

    def set_tokens(self, tokens: int):
        """Record tokens used in this step."""
        self.step.tokens_used = tokens

    def to_db_dict(self) -> dict[str, Any]:
        """Convert trace step to a dict for database storage."""
        return {
            "step_id": self.step.step_id,
            "claim_id": self.state.claim_id,
            "agent_name": self.step.agent_name,
            "started_at": self.step.started_at,
            "completed_at": self.step.completed_at,
            "latency_ms": self.step.latency_ms,
            "tokens_used": self.step.tokens_used,
            "input_data": self.step.input_data,
            "output_data": self.step.output_data,
            "reasoning": self.step.reasoning,
            "status": self.step.status,
            "error": self.step.error,
        }
