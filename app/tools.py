"""The two tools the ADK agent is allowed to call.

Both are pure Python. Neither calls a model, and neither may be made to.
Standing Rule 0: the model writes prose, never applicability.

Docstrings here are read by the ADK and become the tool descriptions the model
sees, so they are written for that audience as well as for a human reader.
"""

from typing import Any

from app.rules.loader import Rule, rules_for
from app.schemas import TransactionFacts


def get_rules(jurisdiction: str) -> list[dict[str, str]]:
    """List every disclosure rule that could apply in a jurisdiction.

    Returns one entry per rule with its id, name, citation and tier, for the
    given jurisdiction plus the rules that apply everywhere. Call evaluate_rule
    on each id to find out whether it actually applies to a transaction.

    The conditions themselves are deliberately not returned. Deciding whether a
    rule applies is not the caller's job.

    Args:
        jurisdiction: One of "DC", "MD" or "VA".

    Returns:
        A list of dicts with keys: id, name, citation, tier.
    """
    return [
        {"id": rule.id, "name": rule.name, "citation": rule.citation, "tier": rule.tier}
        for rule in rules_for(jurisdiction).values()
    ]


def evaluate_rule(rule_id: str, facts: TransactionFacts) -> dict[str, Any]:
    """Decide whether one disclosure rule applies to one set of transaction facts.

    Deterministic and total: the same rule and facts always give the same
    answer, and an unrecognised rule id returns applies=False rather than
    raising. Never calls a model.

    Args:
        rule_id: The id of the rule to evaluate, from get_rules.
        facts: The six transaction facts.

    Returns:
        A dict with keys: applies (bool), tier (str), review_note (str or None).
    """
    rule = rules_for(facts.jurisdiction).get(rule_id)
    if rule is None:
        return {"applies": False, "tier": "review", "review_note": None}

    applies = all(_match(field, condition, facts) for field, condition in rule.applies_when.items())
    return {"applies": applies, "tier": rule.tier, "review_note": rule.review_note}


def _match(field: str, condition: Any, facts: TransactionFacts) -> bool:
    """Evaluate one applies_when condition against the facts.

    The grammar is closed: a bare scalar means equality, and the only operators
    are lt, gte and ne. The loader has already rejected anything else at import
    time, so an unknown operator reaching here is a bug, not user input — hence
    the raise rather than a False.
    """
    actual = getattr(facts, field)

    if not isinstance(condition, dict):
        return bool(actual == condition)

    operator, operand = next(iter(condition.items()))
    if operator == "lt":
        return bool(actual < operand)
    if operator == "gte":
        return bool(actual >= operand)
    if operator == "ne":
        return bool(actual != operand)
    raise ValueError(f"unreachable: loader admitted unknown operator {operator!r}")


def rule_by_id(rule_id: str, jurisdiction: str) -> Rule | None:
    """Return the full Rule, including summary and review_note, or None.

    Used by the engine and by offline mode, which takes its reason text from
    each rule's own summary. Not registered as an agent tool.
    """
    return rules_for(jurisdiction).get(rule_id)
