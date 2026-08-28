"""Load the YAML rule files and expose them by jurisdiction.

Rules are data. Nothing in this module decides whether a rule applies — that is
app/tools.py — and nothing here calls a model. A malformed rule file raises at
import time rather than producing a checklist that is quietly missing an
obligation.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import Jurisdiction, TransactionFacts

RULES_DIR = Path(__file__).parent
FEDERAL_FILE = "federal.yaml"
JURISDICTION_FILES: dict[Jurisdiction, str] = {
    Jurisdiction.DC: "dc.yaml",
    Jurisdiction.MD: "md.yaml",
    Jurisdiction.VA: "va.yaml",
}

# The complete applies_when grammar. Anything else raises at load time rather
# than being silently ignored — a condition nobody evaluates is an obligation
# nobody surfaces.
OPERATORS = frozenset({"lt", "gte", "ne"})

FACT_FIELDS = frozenset(TransactionFacts.model_fields)


class Rule(BaseModel):
    """One disclosure rule, as authored in YAML."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    applies_when: dict[str, Any] = Field(default_factory=dict)
    tier: Literal["required", "likely", "review"]
    summary: str = Field(min_length=1)
    review_note: str | None = None

    @field_validator("applies_when")
    @classmethod
    def _validate_grammar(cls, conditions: dict[str, Any]) -> dict[str, Any]:
        """Reject unknown fields and unknown operators at load time.

        An empty mapping is legal and means the rule applies to every
        transaction in its file's scope.
        """
        for field, condition in conditions.items():
            if field not in FACT_FIELDS:
                raise ValueError(
                    f"applies_when references unknown fact field {field!r}; "
                    f"valid fields are {sorted(FACT_FIELDS)}"
                )
            if isinstance(condition, dict):
                if len(condition) != 1:
                    raise ValueError(
                        f"applies_when[{field!r}] must hold exactly one operator, "
                        f"got {sorted(condition)}"
                    )
                operator = next(iter(condition))
                if operator not in OPERATORS:
                    raise ValueError(
                        f"applies_when[{field!r}] uses unknown operator {operator!r}; "
                        f"valid operators are {sorted(OPERATORS)}"
                    )
        return conditions


def _load_file(filename: str) -> list[Rule]:
    """Parse one rule file. Raises on malformed YAML or an invalid rule."""
    path = RULES_DIR / filename
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{filename}: expected a list of rules, got {type(raw).__name__}")
    return [Rule.model_validate(entry) for entry in raw]


@lru_cache(maxsize=1)
def load_all() -> dict[str, list[Rule]]:
    """Parse every rule file once, keyed by filename.

    Raises on a duplicate id anywhere across the four files. Two rules sharing
    an id would make evaluation order decide which one a lookup returns, which
    is exactly the kind of silent wrong answer this build exists to avoid.
    """
    loaded: dict[str, list[Rule]] = {}
    seen: dict[str, str] = {}

    for filename in [FEDERAL_FILE, *JURISDICTION_FILES.values()]:
        rules = _load_file(filename)
        for rule in rules:
            if rule.id in seen:
                raise ValueError(
                    f"duplicate rule id {rule.id!r} in {filename} "
                    f"(already defined in {seen[rule.id]})"
                )
            seen[rule.id] = filename
        loaded[filename] = rules

    return loaded


@lru_cache(maxsize=len(JURISDICTION_FILES))
def rules_for(jurisdiction: str) -> dict[str, Rule]:
    """Return federal rules followed by that jurisdiction's, keyed by id.

    Insertion order is file order, and file order is display order. The returned
    mapping is cached and shared — treat it as read-only.
    """
    key = Jurisdiction(jurisdiction)
    everything = load_all()
    ordered: dict[str, Rule] = {}
    for rule in everything[FEDERAL_FILE]:
        ordered[rule.id] = rule
    for rule in everything[JURISDICTION_FILES[key]]:
        ordered[rule.id] = rule
    return ordered
