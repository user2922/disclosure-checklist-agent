"""Deterministic rule evaluation. No network, no API key, no model.

These assertions are the product's central claim made checkable: given the same
facts, the same obligations, every time. They assert exact set equality rather
than membership — a test that only checks `in` passes happily while the engine
silently adds a rule that should not be there.
"""

import json
from pathlib import Path

import pytest

from app.engine import compose_buckets
from app.rules.loader import rules_for
from app.schemas import TransactionFacts
from app.tools import evaluate_rule, get_rules

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> TransactionFacts:
    """Load one fixture by stem, e.g. "md_1970_sfh"."""
    return TransactionFacts.model_validate(
        json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    )


# (fixture, required ids, broker_review ids, rules_evaluated)
CASES = [
    (
        "md_1970_sfh",
        {"fed_lead_paint", "md_residential_disclosure"},
        set(),
        8,
    ),
    (
        "md_1985_sfh",
        {"md_residential_disclosure"},
        set(),
        8,
    ),
    (
        "dc_condo_tenant",
        {"dc_sellers_disclosure", "dc_topa", "dc_condo_resale"},
        {"dc_topa", "dc_underground_tank"},
        9,
    ),
    (
        "va_townhome_hoa",
        {"va_rpda", "va_poa_packet"},
        {"fin_va_wdi", "va_septic_well"},
        8,
    ),
]


@pytest.mark.parametrize(("name", "required", "review", "evaluated"), CASES)
def test_fixture_produces_exact_rule_sets(
    name: str, required: set[str], review: set[str], evaluated: int
) -> None:
    buckets = compose_buckets(load_fixture(name))
    assert set(buckets.required) == required
    assert set(buckets.broker_review) == review
    assert buckets.likely == [], "no seed rule is tiered 'likely'"
    assert buckets.rules_evaluated == evaluated


@pytest.mark.parametrize(("name", "required", "review", "evaluated"), CASES)
def test_every_rule_in_scope_is_evaluated(
    name: str, required: set[str], review: set[str], evaluated: int
) -> None:
    """A rule that is never evaluated is an obligation never considered.

    The audit log's "every rule the agent evaluated" claim depends on this
    count matching the full rule set, not just the hits.
    """
    facts = load_fixture(name)
    buckets = compose_buckets(facts)
    assert len(buckets.evaluations) == len(rules_for(facts.jurisdiction))
    assert [e.rule_id for e in buckets.evaluations] == list(rules_for(facts.jurisdiction))


def test_lead_paint_appears_only_below_1978() -> None:
    """The first demo beat, asserted rather than trusted."""
    assert "fed_lead_paint" in compose_buckets(load_fixture("md_1970_sfh")).required
    assert "fed_lead_paint" not in compose_buckets(load_fixture("md_1985_sfh")).required


def test_topa_appears_in_both_required_and_broker_review() -> None:
    """The second demo beat. A required rule with a review_note lands in both."""
    buckets = compose_buckets(load_fixture("dc_condo_tenant"))
    assert "dc_topa" in buckets.required
    assert "dc_topa" in buckets.broker_review


def test_topa_absent_when_not_tenant_occupied() -> None:
    facts = load_fixture("dc_condo_tenant").model_copy(
        update={"seller_occupancy": "owner_occupied"}
    )
    buckets = compose_buckets(facts)
    assert "dc_topa" not in buckets.required
    assert "dc_topa" not in buckets.broker_review


def test_broker_review_has_no_duplicates() -> None:
    """A rule qualifying on both counts must still appear once."""
    for name, *_ in CASES:
        review = compose_buckets(load_fixture(name)).broker_review
        assert len(review) == len(set(review)), name


def test_results_are_identical_across_twenty_runs() -> None:
    """Determinism, asserted directly. Membership must not vary run to run."""
    facts = load_fixture("dc_condo_tenant")
    first = compose_buckets(facts)
    for _ in range(20):
        again = compose_buckets(facts)
        assert again.required == first.required
        assert again.likely == first.likely
        assert again.broker_review == first.broker_review
        assert again.rules_evaluated == first.rules_evaluated


def test_unknown_rule_id_returns_false_and_does_not_raise() -> None:
    verdict = evaluate_rule("no_such_rule", load_fixture("md_1970_sfh"))
    assert verdict["applies"] is False
    assert verdict["review_note"] is None


def test_get_rules_never_exposes_conditions() -> None:
    """The model is not given the conditions; it does not decide applicability."""
    for entry in get_rules("DC"):
        assert set(entry) == {"id", "name", "citation", "tier"}


def test_hoa_rule_excludes_condominiums() -> None:
    """The `ne` operator, which the spec's original grammar could not express."""
    dc = compose_buckets(load_fixture("dc_condo_tenant"))
    assert "dc_hoa_disclosure" not in dc.required

    townhome = load_fixture("dc_condo_tenant").model_copy(update={"property_type": "townhome_hoa"})
    assert "dc_hoa_disclosure" in compose_buckets(townhome).required
