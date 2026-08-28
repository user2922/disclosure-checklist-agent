"""Schema validation. The boundaries every later phase relies on holding."""

import pytest
from pydantic import ValidationError

from app.schemas import (
    DISCLAIMER,
    AuditEntry,
    ChecklistItem,
    ChecklistResult,
    ConfirmRequest,
    TransactionFacts,
)

VALID_FACTS = {
    "jurisdiction": "MD",
    "property_type": "single_family",
    "year_built": 1970,
    "has_association": False,
    "seller_occupancy": "owner_occupied",
    "financing": "conventional",
}


def facts(**overrides: object) -> TransactionFacts:
    return TransactionFacts.model_validate({**VALID_FACTS, **overrides})


@pytest.mark.parametrize("year", [1799, 2027, -1])
def test_year_built_out_of_range_is_rejected(year: int) -> None:
    with pytest.raises(ValidationError):
        facts(year_built=year)


@pytest.mark.parametrize("year", [1800, 1978, 2026])
def test_year_built_boundaries_are_accepted(year: int) -> None:
    assert facts(year_built=year).year_built == year


@pytest.mark.parametrize("value", ["PA", "dc", "", "Maryland"])
def test_invalid_jurisdiction_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        facts(jurisdiction=value)


def test_facts_are_frozen() -> None:
    with pytest.raises(ValidationError):
        facts().year_built = 1985  # type: ignore[misc]


def test_canonical_hash_is_order_independent_and_fact_sensitive() -> None:
    assert facts().canonical_hash() == facts().canonical_hash()
    assert facts().canonical_hash() != facts(year_built=1971).canonical_hash()


def test_disclaimer_must_be_byte_identical() -> None:
    base = {
        "facts": facts(),
        "rules_evaluated": 8,
        "result_id": "abc",
        "mode": "offline",
    }
    ChecklistResult(disclaimer=DISCLAIMER, **base)
    for bad in (DISCLAIMER + " ", DISCLAIMER[:-1], DISCLAIMER.replace(".", "!"), ""):
        with pytest.raises(ValidationError):
            ChecklistResult(disclaimer=bad, **base)


@pytest.mark.parametrize("tier", ["mandatory", "REQUIRED", "urgent", ""])
def test_invalid_tier_is_rejected(tier: str) -> None:
    with pytest.raises(ValidationError):
        ChecklistItem(rule_id="r", name="n", citation="c", tier=tier, reason="because")


def test_empty_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ChecklistItem(rule_id="r", name="n", citation="c", tier="required", reason="")


def test_confirmed_by_must_be_present_and_bounded() -> None:
    ConfirmRequest(result_id="r", confirmed_by="A Broker")
    with pytest.raises(ValidationError):
        ConfirmRequest(result_id="r", confirmed_by="")
    with pytest.raises(ValidationError):
        ConfirmRequest(result_id="r", confirmed_by="x" * 121)


def test_audit_entry_rejects_unknown_kind_and_naive_timestamp() -> None:
    import datetime

    with pytest.raises(ValidationError):
        AuditEntry(kind="fabricated", result_id="r", payload={})
    with pytest.raises(ValidationError):
        AuditEntry(
            timestamp=datetime.datetime(2026, 1, 1),
            kind="result",
            result_id="r",
            payload={},
        )
    assert AuditEntry(kind="result", result_id="r", payload={}).timestamp.tzinfo is not None
