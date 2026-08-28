"""Every shape used by more than one phase of the build.

This module owns them. No other module may redefine a model declared here —
import it instead. There is no business logic in this file: the rules live in
YAML (app/rules/), and membership is decided in app/engine.py.

Standing Rule 0 applies to everything downstream of this file: the model writes
prose, never applicability.
"""

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The exact string SPEC.md requires on every result. Byte-identical or not at
# all — ChecklistResult rejects anything else, so a paraphrase cannot reach a
# user. Never reflow this for line length.
DISCLAIMER = (
    "This checklist is a starting point generated from seed rules. "
    "It is not legal advice. "
    "A licensed broker must confirm requirements before use."
)


# --------------------------------------------------------------------------
# Enums. These exact strings appear in the YAML rule files, the JSON fixtures,
# and the HTML form's option values. One spelling each, everywhere.
# --------------------------------------------------------------------------


class Jurisdiction(StrEnum):
    """The three DMV jurisdictions. Values are uppercase, unlike the others."""

    DC = "DC"
    MD = "MD"
    VA = "VA"


class PropertyType(StrEnum):
    SINGLE_FAMILY = "single_family"
    CONDO = "condo"
    TOWNHOME_HOA = "townhome_hoa"
    MULTI_FAMILY = "multi_family"


class SellerOccupancy(StrEnum):
    OWNER_OCCUPIED = "owner_occupied"
    TENANT_OCCUPIED = "tenant_occupied"
    VACANT = "vacant"


class Financing(StrEnum):
    CONVENTIONAL = "conventional"
    FHA = "fha"
    VA = "va"
    CASH = "cash"


Tier = Literal["required", "likely", "review"]
# live      the model wrote the wording
# cached    identical facts seen before; no provider call
# offline   no API key is configured; wording is each rule's own summary
# degraded  a key IS configured but the call failed; wording fell back to
#           summaries rather than failing the request. Distinct from offline so
#           "we have no key" and "the model just broke" never look the same.
Mode = Literal["live", "cached", "offline", "degraded"]
AuditKind = Literal["rule_evaluated", "model_call", "result", "confirmation", "error"]


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------


class TransactionFacts(BaseModel):
    """The six facts a checklist is derived from. All required, no defaults.

    Frozen: once validated, these facts cannot change underneath a result that
    was computed from them.
    """

    model_config = ConfigDict(frozen=True)

    jurisdiction: Jurisdiction
    property_type: PropertyType
    year_built: int = Field(ge=1800, le=2026)
    has_association: bool
    seller_occupancy: SellerOccupancy
    financing: Financing

    def canonical_hash(self) -> str:
        """SHA-256 of this fact set, stable across processes and runs.

        Used as the response-cache key, so it must not depend on dict ordering
        or on Python's per-process hash seed.
        """
        payload = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


class ChecklistItem(BaseModel):
    """One disclosure obligation, as presented to the user."""

    rule_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    tier: Tier
    reason: str = Field(min_length=1)
    review_note: str | None = None


class ChecklistResult(BaseModel):
    """A complete checklist. Never returned unless it validates.

    A rule may legitimately appear in both `required` and `broker_review` — that
    duplication is the product, not a bug. Do not deduplicate it.
    """

    facts: TransactionFacts
    required: list[ChecklistItem] = Field(default_factory=list)
    likely: list[ChecklistItem] = Field(default_factory=list)
    broker_review: list[ChecklistItem] = Field(default_factory=list)
    disclaimer: str
    rules_evaluated: int = Field(ge=1)
    result_id: str = Field(min_length=1)
    mode: Mode

    @field_validator("disclaimer")
    @classmethod
    def _disclaimer_is_exact(cls, v: str) -> str:
        """Reject any disclaimer that is not byte-identical to DISCLAIMER.

        This is the enforcement point for standing Rule 13. A truncated or
        reworded disclaimer is a compliance-claim problem, not a layout problem.
        """
        if v != DISCLAIMER:
            raise ValueError("disclaimer must be byte-identical to DISCLAIMER")
        return v


class ConfirmRequest(BaseModel):
    """A human's confirmation of a checklist.

    `confirmed_by` is a name someone typed. There is no authentication in this
    build, so it is not a verified identity and must never be presented as one.
    """

    result_id: str = Field(min_length=1)
    confirmed_by: str = Field(min_length=1, max_length=120)


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------


class AuditEntry(BaseModel):
    """One append-only audit line. Validated before it reaches the file."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    kind: AuditKind
    result_id: str = Field(min_length=1)
    payload: dict

    @field_validator("timestamp")
    @classmethod
    def _must_be_utc(cls, v: datetime) -> datetime:
        """Reject naive or non-UTC timestamps.

        An audit log whose entries cannot be ordered across timezones is not an
        audit log.
        """
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return v.astimezone(UTC)
