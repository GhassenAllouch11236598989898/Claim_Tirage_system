"""
Four specialized agents for the Claims Triage System.

1. Classifier Agent   - Categorize claim (injury/property/auto)
2. Severity Agent     - Assign severity (low/medium/high) + estimated payout
3. Reviewer Agent     - Quality check + confidence score
4. Human Gate Agent   - Route to human if severity=high OR confidence<0.8
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from claims_triage.config import settings
from claims_triage.models import (
    ClaimGraphState, ClaimStatus,
    ClassificationOutput, SeverityOutput, ReviewOutput, HumanGateOutput,
    ClaimCategory, SeverityLevel,
)
from claims_triage.tracing import StepTracer
from claims_triage.budget import BudgetEnforcer, BudgetExceededError

logger = logging.getLogger(__name__)

# ── OpenAI Client ──────────────────────────────────────────────────────────────

_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def _call_llm(system_prompt: str, user_prompt: str, response_format: dict | None = None) -> tuple[str, int]:
    """
    Call OpenAI and return (response_text, total_tokens).
    """
    client = get_openai_client()

    kwargs: dict[str, Any] = {
        "model": settings.openai_model,
        "temperature": settings.openai_temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if response_format:
        kwargs["response_format"] = response_format

    response = await client.chat.completions.create(**kwargs)

    content = response.choices[0].message.content or ""
    total_tokens = response.usage.total_tokens if response.usage else 0

    return content, total_tokens


# ── Agent 1: Classifier ───────────────────────────────────────────────────────

CLASSIFIER_SYSTEM_PROMPT = """You are an insurance claim classifier. Your job is to categorize insurance claims into one of these categories:
- injury: Physical injury, medical claims, bodily harm, health-related
- property: Property damage, home damage, theft, vandalism, natural disaster damage
- auto: Vehicle accidents, car damage, collision, traffic incidents

Respond ONLY with valid JSON matching this schema:
{
    "category": "injury" | "property" | "auto",
    "confidence": 0.0 to 1.0,
    "reasoning": "brief explanation",
    "sub_category": "optional more specific category",
    "keywords_detected": ["list", "of", "key", "terms"]
}"""


async def classifier_agent(
    state: ClaimGraphState,
    budget: BudgetEnforcer,
) -> ClaimGraphState:
    """Classify the claim into injury/property/auto."""

    budget.check_budget(state)

    with StepTracer(state, "classifier") as tracer:
        user_prompt = (
            f"Classify this insurance claim:\n\n"
            f"Description: {state.claim.description}\n"
            f"Claimed Amount: ${state.claim.claimed_amount:,.2f}\n"
            f"Policy Limit: ${state.claim.policy_limit:,.2f}\n"
        )
        if state.claim.supporting_info:
            user_prompt += f"Supporting Info: {state.claim.supporting_info}\n"

        tracer.set_input({"description": state.claim.description})

        response_text, tokens = await _call_llm(
            CLASSIFIER_SYSTEM_PROMPT,
            user_prompt,
            response_format={"type": "json_object"},
        )

        tracer.set_tokens(tokens)
        budget.add_tokens(state, tokens)

        # Parse response
        try:
            data = json.loads(response_text)
            classification = ClassificationOutput(
                category=ClaimCategory(data.get("category", "unknown")),
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", ""),
                sub_category=data.get("sub_category"),
                keywords_detected=data.get("keywords_detected", []),
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse classifier response: {e}")
            classification = ClassificationOutput(
                category=ClaimCategory.UNKNOWN,
                confidence=0.3,
                reasoning=f"Failed to parse LLM response: {response_text[:200]}",
            )

        state.classification = classification
        state.status = ClaimStatus.CLASSIFYING
        state.current_agent = "classifier"

        tracer.set_output(classification.model_dump())
        tracer.set_reasoning(classification.reasoning)

    return state


# ── Agent 2: Severity Scorer ──────────────────────────────────────────────────

SEVERITY_SYSTEM_PROMPT = """You are an insurance claim severity scorer. Based on the claim details and classification, assign a severity level and estimate the payout.

Severity levels:
- low: Minor incident, low financial impact, straightforward resolution
- medium: Moderate incident, significant but manageable financial impact
- high: Severe incident, large financial impact, potential litigation, serious injuries

Respond ONLY with valid JSON matching this schema:
{
    "severity": "low" | "medium" | "high",
    "estimated_payout": number (dollar amount),
    "confidence": 0.0 to 1.0,
    "risk_factors": ["list", "of", "risk", "factors"],
    "reasoning": "brief explanation of severity assessment"
}"""


async def severity_agent(
    state: ClaimGraphState,
    budget: BudgetEnforcer,
) -> ClaimGraphState:
    """Score the severity of the classified claim."""

    budget.check_budget(state)

    with StepTracer(state, "severity_scorer") as tracer:
        classification = state.classification
        user_prompt = (
            f"Score the severity of this insurance claim:\n\n"
            f"Description: {state.claim.description}\n"
            f"Category: {classification.category.value if classification else 'unknown'}\n"
            f"Classification Confidence: {classification.confidence if classification else 0}\n"
            f"Claimed Amount: ${state.claim.claimed_amount:,.2f}\n"
            f"Policy Limit: ${state.claim.policy_limit:,.2f}\n"
        )
        if state.claim.supporting_info:
            user_prompt += f"Supporting Info: {state.claim.supporting_info}\n"

        tracer.set_input({
            "description": state.claim.description,
            "category": classification.category.value if classification else "unknown",
        })

        response_text, tokens = await _call_llm(
            SEVERITY_SYSTEM_PROMPT,
            user_prompt,
            response_format={"type": "json_object"},
        )

        tracer.set_tokens(tokens)
        budget.add_tokens(state, tokens)

        try:
            data = json.loads(response_text)
            severity = SeverityOutput(
                severity=SeverityLevel(data.get("severity", "medium")),
                estimated_payout=min(
                    float(data.get("estimated_payout", 0)),
                    state.claim.policy_limit,
                ),
                confidence=float(data.get("confidence", 0.5)),
                risk_factors=data.get("risk_factors", []),
                reasoning=data.get("reasoning", ""),
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse severity response: {e}")
            severity = SeverityOutput(
                severity=SeverityLevel.MEDIUM,
                estimated_payout=state.claim.claimed_amount * 0.5,
                confidence=0.3,
                reasoning=f"Failed to parse LLM response: {response_text[:200]}",
            )

        state.severity = severity
        state.status = ClaimStatus.SCORING
        state.current_agent = "severity_scorer"

        tracer.set_output(severity.model_dump())
        tracer.set_reasoning(severity.reasoning)

    return state


# ── Agent 3: Reviewer ─────────────────────────────────────────────────────────

REVIEWER_SYSTEM_PROMPT = """You are an insurance claim reviewer performing quality checks. Review the classification and severity assessment for consistency, accuracy, and completeness.

Your job:
1. Verify the classification makes sense given the description
2. Check if the severity rating aligns with the claim details
3. Assess overall confidence in the automated decision
4. Flag any concerns or anomalies
5. Determine if human review is needed

Respond ONLY with valid JSON matching this schema:
{
    "overall_confidence": 0.0 to 1.0,
    "recommendation": "approve_auto" | "needs_human_review" | "flag_for_investigation",
    "flags": ["list", "of", "concerns"],
    "requires_human_review": true | false,
    "reasoning": "detailed explanation of review findings",
    "suggested_payout": number or null
}"""


async def reviewer_agent(
    state: ClaimGraphState,
    budget: BudgetEnforcer,
) -> ClaimGraphState:
    """Review the classification and severity for quality."""

    budget.check_budget(state)

    with StepTracer(state, "reviewer") as tracer:
        classification = state.classification
        severity = state.severity

        user_prompt = (
            f"Review this insurance claim assessment:\n\n"
            f"--- Claim Details ---\n"
            f"Description: {state.claim.description}\n"
            f"Claimed Amount: ${state.claim.claimed_amount:,.2f}\n"
            f"Policy Limit: ${state.claim.policy_limit:,.2f}\n"
            f"\n--- Classification ---\n"
            f"Category: {classification.category.value if classification else 'N/A'}\n"
            f"Confidence: {classification.confidence if classification else 0}\n"
            f"Reasoning: {classification.reasoning if classification else 'N/A'}\n"
            f"\n--- Severity Assessment ---\n"
            f"Severity: {severity.severity.value if severity else 'N/A'}\n"
            f"Estimated Payout: ${severity.estimated_payout:,.2f if severity else 0}\n"
            f"Confidence: {severity.confidence if severity else 0}\n"
            f"Risk Factors: {', '.join(severity.risk_factors) if severity else 'N/A'}\n"
            f"Reasoning: {severity.reasoning if severity else 'N/A'}\n"
        )

        tracer.set_input({
            "category": classification.category.value if classification else "N/A",
            "severity": severity.severity.value if severity else "N/A",
        })

        response_text, tokens = await _call_llm(
            REVIEWER_SYSTEM_PROMPT,
            user_prompt,
            response_format={"type": "json_object"},
        )

        tracer.set_tokens(tokens)
        budget.add_tokens(state, tokens)

        try:
            data = json.loads(response_text)
            review = ReviewOutput(
                overall_confidence=float(data.get("overall_confidence", 0.5)),
                recommendation=data.get("recommendation", "needs_human_review"),
                flags=data.get("flags", []),
                requires_human_review=data.get("requires_human_review", True),
                reasoning=data.get("reasoning", ""),
                suggested_payout=data.get("suggested_payout"),
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse reviewer response: {e}")
            review = ReviewOutput(
                overall_confidence=0.3,
                recommendation="needs_human_review",
                flags=["Failed to parse LLM response"],
                requires_human_review=True,
                reasoning=f"Parse error, defaulting to human review: {response_text[:200]}",
            )

        state.review = review
        state.status = ClaimStatus.REVIEWING
        state.current_agent = "reviewer"

        tracer.set_output(review.model_dump())
        tracer.set_reasoning(review.reasoning)

    return state


# ── Agent 4: Human Gate ───────────────────────────────────────────────────────

async def human_gate_agent(
    state: ClaimGraphState,
    budget: BudgetEnforcer,
) -> ClaimGraphState:
    """
    Decision gate: route to human if severity=high OR confidence<0.8.
    No LLM call needed — this is pure logic.
    """

    budget.check_budget(state)

    with StepTracer(state, "human_gate") as tracer:
        severity = state.severity
        review = state.review

        severity_is_high = severity and severity.severity == SeverityLevel.HIGH
        confidence_is_low = review and review.overall_confidence < settings.human_gate_confidence_threshold
        reviewer_flagged = review and review.requires_human_review

        needs_human = severity_is_high or confidence_is_low or reviewer_flagged

        reasons = []
        if severity_is_high:
            reasons.append(f"Severity is HIGH (threshold trigger)")
        if confidence_is_low:
            reasons.append(f"Confidence {review.overall_confidence:.2f} < {settings.human_gate_confidence_threshold}")
        if reviewer_flagged:
            reasons.append("Reviewer flagged for human review")

        tracer.set_input({
            "severity": severity.severity.value if severity else "N/A",
            "overall_confidence": review.overall_confidence if review else 0,
            "reviewer_flagged": reviewer_flagged,
        })

        if needs_human:
            gate_output = HumanGateOutput(
                routed_to_human=True,
                reason="; ".join(reasons),
            )
            state.status = ClaimStatus.PENDING_HUMAN
            logger.info(
                f"[HUMAN_GATE] [{state.claim_id}] Routed to human: {gate_output.reason}"
            )
        else:
            # Auto-approve
            estimated = severity.estimated_payout if severity else 0
            suggested = review.suggested_payout if review and review.suggested_payout else estimated

            gate_output = HumanGateOutput(
                routed_to_human=False,
                reason="All checks passed — auto-approved",
                auto_decision="approve",
                final_payout=suggested,
            )
            state.status = ClaimStatus.COMPLETED
            logger.info(
                f"[HUMAN_GATE] [{state.claim_id}] Auto-approved | payout=${suggested:,.2f}"
            )

        state.human_gate = gate_output
        state.current_agent = "human_gate"

        tracer.set_output(gate_output.model_dump())
        tracer.set_reasoning(gate_output.reason)
        tracer.set_tokens(0)  # No LLM call for this agent

    return state
