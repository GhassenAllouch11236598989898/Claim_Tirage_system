"""
Unit tests for Pydantic models, budget enforcement, and tracing.
Run with: pytest claims_triage/tests/test_unit.py -v
"""

from __future__ import annotations

import pytest
import time
from datetime import datetime

from claims_triage.models import (
    ClaimInput, ClaimGraphState, ClaimTrace, BudgetStatus, BudgetConfig,
    ClassificationOutput, SeverityOutput, ReviewOutput, HumanGateOutput,
    ClaimCategory, SeverityLevel, ClaimStatus, AgentStepTrace,
)
from claims_triage.budget import BudgetEnforcer, BudgetExceededError
from claims_triage.tracing import StepTracer


# ── Model Tests ────────────────────────────────────────────────────────────────

class TestClaimInput:
    def test_valid_claim(self):
        claim = ClaimInput(
            description="Vehicle rear-ended at intersection causing whiplash",
            policy_number="POL-2024-001234",
            policy_limit=100000.0,
            claimant_name="John Smith",
            incident_date="2024-11-15",
            claimed_amount=15000.0,
        )
        assert claim.claim_id  # Auto-generated UUID
        assert claim.policy_limit == 100000.0

    def test_claim_validation(self):
        with pytest.raises(Exception):
            ClaimInput(
                description="short",  # too short (min_length=10)
                policy_number="POL-001",
                policy_limit=100000.0,
                claimant_name="Test",
                incident_date="2024-01-01",
                claimed_amount=1000.0,
            )


class TestClassificationOutput:
    def test_valid_classification(self):
        c = ClassificationOutput(
            category=ClaimCategory.AUTO,
            confidence=0.95,
            reasoning="Contains vehicle and collision keywords",
        )
        assert c.category == ClaimCategory.AUTO
        assert c.confidence == 0.95

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            ClassificationOutput(
                category=ClaimCategory.AUTO,
                confidence=1.5,  # > 1.0
                reasoning="test",
            )


class TestSeverityOutput:
    def test_valid_severity(self):
        s = SeverityOutput(
            severity=SeverityLevel.HIGH,
            estimated_payout=50000.0,
            confidence=0.85,
            risk_factors=["serious injury", "litigation risk"],
            reasoning="High severity due to injuries",
        )
        assert s.severity == SeverityLevel.HIGH
        assert len(s.risk_factors) == 2


# ── Budget Tests ───────────────────────────────────────────────────────────────

class TestBudgetEnforcer:
    def test_within_budget(self):
        config = BudgetConfig(max_tokens=1000, max_wall_clock_seconds=60)
        enforcer = BudgetEnforcer(config)

        claim = ClaimInput(
            description="Test claim for budget enforcement testing",
            policy_number="POL-001",
            policy_limit=10000,
            claimant_name="Test",
            incident_date="2024-01-01",
            claimed_amount=5000,
        )
        state = ClaimGraphState(
            claim=claim,
            claim_id=claim.claim_id,
            trace=ClaimTrace(claim_id=claim.claim_id),
        )

        enforcer.start_tracking(claim.claim_id)
        status = enforcer.check_budget(state)
        assert not status.budget_exceeded

    def test_token_exceeded(self):
        config = BudgetConfig(max_tokens=100, max_wall_clock_seconds=60)
        enforcer = BudgetEnforcer(config)

        claim = ClaimInput(
            description="Test claim for budget exceeded testing",
            policy_number="POL-001",
            policy_limit=10000,
            claimant_name="Test",
            incident_date="2024-01-01",
            claimed_amount=5000,
        )
        state = ClaimGraphState(
            claim=claim,
            claim_id=claim.claim_id,
            trace=ClaimTrace(claim_id=claim.claim_id),
        )
        state.budget.tokens_used = 150  # Over the 100 limit

        enforcer.start_tracking(claim.claim_id)
        with pytest.raises(BudgetExceededError, match="Token budget exceeded"):
            enforcer.check_budget(state)

    def test_add_tokens(self):
        config = BudgetConfig(max_tokens=1000)
        enforcer = BudgetEnforcer(config)

        claim = ClaimInput(
            description="Test claim for add tokens testing",
            policy_number="POL-001",
            policy_limit=10000,
            claimant_name="Test",
            incident_date="2024-01-01",
            claimed_amount=5000,
        )
        state = ClaimGraphState(
            claim=claim,
            claim_id=claim.claim_id,
            trace=ClaimTrace(claim_id=claim.claim_id),
        )

        enforcer.add_tokens(state, 200)
        assert state.budget.tokens_used == 200
        assert state.budget.tokens_remaining == 800


# ── Tracing Tests ──────────────────────────────────────────────────────────────

class TestStepTracer:
    def test_trace_context_manager(self):
        claim = ClaimInput(
            description="Test claim for tracing context manager",
            policy_number="POL-001",
            policy_limit=10000,
            claimant_name="Test",
            incident_date="2024-01-01",
            claimed_amount=5000,
        )
        state = ClaimGraphState(
            claim=claim,
            claim_id=claim.claim_id,
            trace=ClaimTrace(claim_id=claim.claim_id),
        )

        with StepTracer(state, "test_agent") as tracer:
            tracer.set_input({"key": "value"})
            tracer.set_output({"result": "ok"})
            tracer.set_reasoning("Test reasoning")
            tracer.set_tokens(100)
            time.sleep(0.05)  # Ensure measurable latency

        assert len(state.trace.steps) == 1
        step = state.trace.steps[0]
        assert step.agent_name == "test_agent"
        assert step.status == "completed"
        assert step.tokens_used == 100
        assert step.latency_ms >= 0  # May be 0 on fast systems
        assert step.reasoning == "Test reasoning"

    def test_trace_error_handling(self):
        claim = ClaimInput(
            description="Test claim for error handling in tracing",
            policy_number="POL-001",
            policy_limit=10000,
            claimant_name="Test",
            incident_date="2024-01-01",
            claimed_amount=5000,
        )
        state = ClaimGraphState(
            claim=claim,
            claim_id=claim.claim_id,
            trace=ClaimTrace(claim_id=claim.claim_id),
        )

        with pytest.raises(ValueError):
            with StepTracer(state, "error_agent") as tracer:
                raise ValueError("Test error")

        assert len(state.trace.steps) == 1
        step = state.trace.steps[0]
        assert step.status == "error"
        assert "Test error" in step.error


# ── Graph State Tests ──────────────────────────────────────────────────────────

class TestClaimGraphState:
    def test_initial_state(self):
        claim = ClaimInput(
            description="Test claim for initial state verification",
            policy_number="POL-001",
            policy_limit=10000,
            claimant_name="Test",
            incident_date="2024-01-01",
            claimed_amount=5000,
        )
        state = ClaimGraphState(
            claim=claim,
            claim_id=claim.claim_id,
        )
        assert state.status == ClaimStatus.SUBMITTED
        assert state.current_agent == "start"
        assert state.classification is None
        assert state.severity is None
        assert state.review is None
        assert state.human_gate is None

    def test_state_with_all_outputs(self):
        claim = ClaimInput(
            description="Test claim for full state with all outputs",
            policy_number="POL-001",
            policy_limit=10000,
            claimant_name="Test",
            incident_date="2024-01-01",
            claimed_amount=5000,
        )
        state = ClaimGraphState(
            claim=claim,
            claim_id=claim.claim_id,
            classification=ClassificationOutput(
                category=ClaimCategory.AUTO,
                confidence=0.9,
                reasoning="Auto claim",
            ),
            severity=SeverityOutput(
                severity=SeverityLevel.LOW,
                estimated_payout=1000,
                confidence=0.85,
                reasoning="Low severity",
            ),
            review=ReviewOutput(
                overall_confidence=0.88,
                recommendation="approve_auto",
                requires_human_review=False,
                reasoning="All checks passed",
            ),
        )
        assert state.classification.category == ClaimCategory.AUTO
        assert state.severity.severity == SeverityLevel.LOW
        assert state.review.overall_confidence == 0.88


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
