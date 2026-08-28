"""Bucket membership. The authority on what belongs on a checklist.

This module, not the model, decides which rules appear in which bucket. Given
identical facts it returns identical sets, run to run and process to process,
because nothing here is stochastic and nothing here is cached across facts.

The agent in app/agent.py calls evaluate_rule through the ADK for the audit
trail, but where the two disagree this module wins and the discrepancy is
logged. See SPEC.md, "Resolved during build planning", decision 3.
"""

from typing import NamedTuple

from app.rules.loader import rules_for
from app.schemas import TransactionFacts
from app.tools import evaluate_rule


class RuleEvaluation(NamedTuple):
    """One rule's verdict, kept for the audit log whether it applied or not."""

    rule_id: str
    applies: bool
    tier: str
    review_note: str | None


class Buckets(NamedTuple):
    """The three display buckets, as ordered lists of rule ids.

    A rule id may appear in both `required` and `broker_review`. That is the
    product working as intended: a required obligation whose scope a broker
    still has to confirm. Do not deduplicate across buckets.
    """

    required: list[str]
    likely: list[str]
    broker_review: list[str]
    rules_evaluated: int
    evaluations: list[RuleEvaluation]


def compose_buckets(facts: TransactionFacts) -> Buckets:
    """Evaluate every rule in scope and sort the applicable ones into buckets.

    Every rule is evaluated, applied or not, and every verdict is returned in
    `evaluations` so the audit log can record the ones that did not apply. A
    checklist that only logs its hits cannot answer "did you consider X".

    Order is file order throughout, which is also display order. Nothing is
    sorted; stability comes from the rule files themselves.
    """
    required: list[str] = []
    likely: list[str] = []
    broker_review: list[str] = []
    evaluations: list[RuleEvaluation] = []

    for rule_id in rules_for(facts.jurisdiction):
        verdict = evaluate_rule(rule_id, facts)
        evaluations.append(
            RuleEvaluation(
                rule_id=rule_id,
                applies=bool(verdict["applies"]),
                tier=str(verdict["tier"]),
                review_note=verdict["review_note"],
            )
        )

        if not verdict["applies"]:
            continue

        tier = verdict["tier"]
        if tier == "required":
            required.append(rule_id)
        elif tier == "likely":
            likely.append(rule_id)

        # Broker review collects two distinct things: anything tiered "review",
        # and anything carrying a review_note whatever its tier. A rule can
        # qualify on both counts and must still appear once.
        if tier == "review" or verdict["review_note"] is not None:
            if rule_id not in broker_review:
                broker_review.append(rule_id)

    return Buckets(
        required=required,
        likely=likely,
        broker_review=broker_review,
        rules_evaluated=len(evaluations),
        evaluations=evaluations,
    )
