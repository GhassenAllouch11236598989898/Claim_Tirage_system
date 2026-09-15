"""
Budget enforcement for the Claims Triage System.
Hard ceiling: 50k tokens, 5 minutes wall-clock.
Blocks runaway loops and enforces resource limits.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from claims_triage.models import BudgetConfig, BudgetStatus, ClaimGraphState

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when the budget ceiling is hit."""
    pass


class BudgetEnforcer:
    """
    Enforces hard budget ceilings on token usage and wall-clock time.
    Checked before every agent step.
    """

    def __init__(self, config: Optional[BudgetConfig] = None):
        self.config = config or BudgetConfig()
        self._start_times: dict[str, float] = {}

    def start_tracking(self, claim_id: str):
        """Start wall-clock tracking for a claim."""
        self._start_times[claim_id] = time.monotonic()
        logger.info(
            f"[BUDGET] [{claim_id}] Tracking started | "
            f"max_tokens={self.config.max_tokens} | max_time={self.config.max_wall_clock_seconds}s"
        )

    def check_budget(self, state: ClaimGraphState) -> BudgetStatus:
        """
        Check if the claim is within budget.
        Raises BudgetExceededError if any ceiling is hit.
        """
        claim_id = state.claim_id
        start_time = self._start_times.get(claim_id, time.monotonic())

        elapsed = time.monotonic() - start_time
        tokens_used = state.budget.tokens_used

        status = BudgetStatus(
            tokens_used=tokens_used,
            tokens_remaining=max(0, self.config.max_tokens - tokens_used),
            wall_clock_elapsed_s=round(elapsed, 2),
            wall_clock_remaining_s=round(max(0, self.config.max_wall_clock_seconds - elapsed), 2),
            budget_exceeded=False,
        )

        # Check token ceiling
        if tokens_used >= self.config.max_tokens:
            status.budget_exceeded = True
            status.exceeded_reason = (
                f"Token budget exceeded: {tokens_used}/{self.config.max_tokens}"
            )
            logger.warning(f"[BUDGET] [{claim_id}] {status.exceeded_reason}")
            raise BudgetExceededError(status.exceeded_reason)

        # Check wall-clock ceiling
        if elapsed >= self.config.max_wall_clock_seconds:
            status.budget_exceeded = True
            status.exceeded_reason = (
                f"Wall-clock budget exceeded: {elapsed:.1f}s/{self.config.max_wall_clock_seconds}s"
            )
            logger.warning(f"[BUDGET] [{claim_id}] {status.exceeded_reason}")
            raise BudgetExceededError(status.exceeded_reason)

        logger.debug(
            f"[BUDGET] [{claim_id}] OK | tokens={tokens_used}/{self.config.max_tokens} | "
            f"time={elapsed:.1f}s/{self.config.max_wall_clock_seconds}s"
        )

        return status

    def add_tokens(self, state: ClaimGraphState, tokens: int):
        """Add tokens to the claim's budget usage."""
        state.budget.tokens_used += tokens
        state.budget.tokens_remaining = max(
            0, self.config.max_tokens - state.budget.tokens_used
        )
        logger.debug(
            f"[BUDGET] [{state.claim_id}] +{tokens} tokens | "
            f"total={state.budget.tokens_used}/{self.config.max_tokens}"
        )

    def stop_tracking(self, claim_id: str):
        """Stop wall-clock tracking for a claim."""
        if claim_id in self._start_times:
            elapsed = time.monotonic() - self._start_times.pop(claim_id)
            logger.info(f"[BUDGET] [{claim_id}] Tracking stopped after {elapsed:.1f}s")

    def get_elapsed(self, claim_id: str) -> float:
        """Get elapsed wall-clock time for a claim."""
        start = self._start_times.get(claim_id)
        if start is None:
            return 0.0
        return time.monotonic() - start
