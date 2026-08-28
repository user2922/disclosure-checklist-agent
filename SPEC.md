# Spec: Disclosure Checklist Agent

DevFest DC 2026 Build-a-thon — Entry 3 (Startup Innovation / Consumer track)
Build window: ~50 minutes on the shared ADK scaffold. Read this whole file before writing code.

## Objective

**What:** A web app where a DMV real estate agent enters six transaction facts and an ADK agent returns the required seller-disclosure checklist for that transaction — each item citing its governing rule — plus a separate list of items flagged for licensed-broker review. The agent recommends; a human confirms. Every rule consulted is written to an audit log.

**Why:** Disclosure requirements differ across DC, Maryland, and Virginia and change with property facts (year built, condo/HOA, tenant occupancy). Agents miss items, and missed disclosures are the most common source of post-closing liability. Today this knowledge lives in brokers' heads and static PDFs.

**User:** A licensed real estate agent or transaction coordinator at an independent brokerage in the DMV.

**The decision boundary (this is the pitch):** The agent never determines compliance. It produces a *recommendation* with three confidence tiers and a mandatory "Broker Review" bucket. The UI has a single "Confirm checklist" button that only a human can press, and confirmation is recorded in the audit log with a timestamp. Judges have spent the day hearing "an agent that pre-screens is not an agent that determines" — this app is that principle built.

**User stories:**
1. As an agent, I enter facts about a 1970 Maryland single-family home and see lead-paint and MD Residential Property Disclosure/Disclaimer on the required list, each citing the rule.
2. As an agent, I change year built to 1985 and lead-paint disappears from required.
3. As an agent, I toggle "tenant-occupied" on a DC property and see the TOPA notice appear in Required and a note flagged for broker review about tenant notice timing.
4. As a broker, I open the audit log and see every rule the agent evaluated, what it concluded, and who confirmed the checklist.

## Tech Stack

- Python 3.12
- Google Agent Development Kit (ADK) — latest stable; agent runtime
- Gemini 2.5 Flash (or the fastest model available on the day) via ADK
- FastAPI + Uvicorn — HTTP layer
- Pydantic v2 — all agent input/output schemas
- Jinja2 — single server-rendered page (no JS build step; keep it simple)
- Cloud Run — deploy target (reuse Entry 1 deploy script)
- pytest — tests
- Reuse from scaffold: agent bootstrap, audit-log middleware, deploy script, base HTML layout

## Commands

```
Setup:   python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
Dev:     uvicorn app.main:app --reload --port 8080
Test:    pytest -q
Lint:    ruff check . --fix && ruff format .
Deploy:  ./scripts/deploy.sh disclosure-agent
Smoke:   curl -X POST localhost:8080/api/checklist -H 'Content-Type: application/json' -d @tests/fixtures/md_1970_sfh.json
```

## Project Structure

```
app/
  main.py               → FastAPI app, routes: GET /, POST /api/checklist, POST /api/confirm, GET /audit
  agent.py              → ADK agent definition, tool registration, system instruction
  schemas.py            → TransactionFacts, ChecklistItem, ChecklistResult, AuditEntry (Pydantic)
  rules/
    dc.yaml             → DC disclosure rules
    md.yaml             → Maryland disclosure rules
    va.yaml             → Virginia disclosure rules
    federal.yaml        → Federal rules (lead paint)
    loader.py           → Loads YAML, exposes rules_for(jurisdiction)
  tools.py              → ADK tools: get_rules(jurisdiction), evaluate_rule(rule_id, facts)
  audit.py              → Append-only JSONL audit log (from scaffold)
  templates/
    index.html          → Intake form + results + confirm button
    audit.html          → Audit log viewer
tests/
  test_rules.py         → Deterministic rule evaluation, no LLM
  test_schemas.py       → Schema validation
  fixtures/             → Sample TransactionFacts JSON for demo + tests
scripts/
  deploy.sh             → Cloud Run deploy (from scaffold)
SPEC.md
```

## Core Design

### Input: TransactionFacts (six fields, all required)

| Field | Type | Values |
|---|---|---|
| jurisdiction | enum | DC, MD, VA |
| property_type | enum | single_family, condo, townhome_hoa, multi_family |
| year_built | int | 1800–2026 |
| has_association | bool | condo association or HOA governs the property |
| seller_occupancy | enum | owner_occupied, tenant_occupied, vacant |
| financing | enum | conventional, fha, va, cash |

### Rule file format (YAML)

Rules are **deterministic data**, not prompt text. The LLM does not decide whether a rule applies; it explains and phrases. Example:

```yaml
- id: fed_lead_paint
  name: Lead-Based Paint Disclosure
  citation: "42 U.S.C. § 4852d; 24 CFR Part 35"
  applies_when:
    year_built: { lt: 1978 }
  tier: required
  summary: Seller must provide the EPA lead hazard pamphlet, disclose known lead-based paint, and give the buyer a 10-day inspection opportunity.

- id: dc_topa
  name: Tenant Opportunity to Purchase Act (TOPA) Notice
  citation: "D.C. Code § 42-3404.02 et seq."
  applies_when:
    jurisdiction: DC
    seller_occupancy: tenant_occupied
  tier: required
  review_note: Single-family TOPA exemptions and elderly/disabled tenant carve-outs depend on facts not captured here. Broker must verify tenant status and notice timing.
```

`applies_when` supports equality on enums/bools and `lt`/`gte` on year_built. `review_note` is optional; when present, the item ALSO appears in Broker Review with that note.

### Seed rules (verify each against current statute before demo — these are starting points, not legal advice)

**Federal**
- Lead-based paint disclosure — year_built < 1978

**DC**
- Seller's Disclosure Statement (D.C. Code § 42-1301 et seq.) — all residential
- TOPA notice — tenant_occupied (review_note on exemptions)
- Condominium resale certificate / public offering statement (D.C. Code § 42-1904.11) — property_type condo
- HOA disclosure — has_association and not condo (review_note: scope varies)
- Underground storage tank disclosure — all (review_note: only if a tank exists or existed; broker to confirm)

**Maryland**
- Residential Property Disclosure and Disclaimer Statement (Md. Real Prop. § 10-702) — all residential resale
- Condominium resale certificate (Md. Real Prop. § 11-135) — condo
- Homeowners Association disclosures (Md. Real Prop. § 11B-106) — has_association and not condo
- Lead paint: Maryland Lead Poisoning Prevention Program registration — tenant_occupied and year_built < 1978 (review_note)

**Virginia**
- Residential Property Disclosure Act statement (Va. Code § 55.1-700 et seq.) — all residential resale
- Condominium Act resale certificate (Va. Code § 55.1-1990) — condo
- Property Owners' Association Act disclosure packet (Va. Code § 55.1-1808) — has_association and not condo
- Septic/onsite sewage and private well disclosures (Va. Code § 55.1-704 area) — flagged for review, since the intake doesn't capture utilities

**Financing-driven review flags (not disclosures, but the agent should surface them)**
- fha or va financing → Broker Review: appraisal condition requirements and, for VA, regional wood-destroying-insect inspection conventions
- multi_family → Broker Review: additional tenant and rent-roll disclosures likely apply; not modeled

### Output: ChecklistResult

```python
class ChecklistItem(BaseModel):
    rule_id: str
    name: str
    citation: str
    tier: Literal["required", "likely", "review"]
    reason: str          # one sentence, LLM-phrased, references the triggering fact
    review_note: str | None = None

class ChecklistResult(BaseModel):
    facts: TransactionFacts
    required: list[ChecklistItem]
    likely: list[ChecklistItem]
    broker_review: list[ChecklistItem]
    disclaimer: str      # fixed string, see Boundaries
    rules_evaluated: int
    result_id: str       # UUID, used by /api/confirm
```

### Agent flow

1. `POST /api/checklist` validates `TransactionFacts`.
2. ADK agent is invoked with the facts. Its only tools are `get_rules(jurisdiction)` and `evaluate_rule(rule_id, facts)`. `evaluate_rule` is pure Python and returns `applies: bool, tier, review_note`.
3. Agent loops over every rule for federal + the jurisdiction, calls `evaluate_rule` on each, and composes `ChecklistResult` with a one-sentence `reason` per applied item. Non-applied rules are still logged.
4. Response is validated against `ChecklistResult` (Pydantic); on validation failure, retry once, then return a plain error — never a partial checklist.
5. Every tool call and the final result are appended to the audit log with `result_id`.
6. `POST /api/confirm {result_id, confirmed_by}` records human confirmation. Nothing in the app can call this except the button.

### Determinism guarantee

Given identical facts, the sets `required`, `likely`, and `broker_review` must be identical run-to-run, because membership is decided by `evaluate_rule`, not the model. Only `reason` wording may vary. `tests/test_rules.py` enforces this without an API key.

## Code Style

```python
# app/tools.py
from app.rules.loader import rules_for
from app.schemas import TransactionFacts


def evaluate_rule(rule_id: str, facts: TransactionFacts) -> dict:
    """Deterministically decide whether a single rule applies to these facts.

    Returns {"applies": bool, "tier": str, "review_note": str | None}.
    Never calls the model. Never raises on an unknown rule — returns applies=False.
    """
    rule = rules_for(facts.jurisdiction).get(rule_id)
    if rule is None:
        return {"applies": False, "tier": "review", "review_note": None}
    applies = all(_match(field, cond, facts) for field, cond in rule.applies_when.items())
    return {"applies": applies, "tier": rule.tier, "review_note": rule.review_note}
```

- snake_case functions and variables, PascalCase Pydantic models, UPPER_CASE for the disclaimer constant.
- Type hints on every function signature. Docstrings on tools (ADK reads them).
- No business logic in `main.py`; routes call into `agent.py` and `tools.py`.
- Rules live in YAML only. Never hardcode a disclosure in Python or a prompt.

## Testing Strategy

- Framework: pytest. Tests in `tests/`. No network or API key required for the suite.
- `test_rules.py`: for each fixture, assert exact `required`/`broker_review` rule-id sets. Minimum fixtures:
  - MD, single_family, 1970, no association, owner_occupied, conventional → lead paint + MD disclosure required
  - MD same but 1985 → lead paint absent
  - DC, condo, 2005, association, tenant_occupied, cash → DC disclosure + condo resale + TOPA required; TOPA in review
  - VA, townhome_hoa, 1995, association, owner_occupied, va → VA RPDA + POA packet required; VA financing note in review
- `test_schemas.py`: invalid jurisdiction and year_built out of range are rejected with 422.
- Manual check before demo: run all four fixtures through the live agent and confirm the audit log shows `rules_evaluated` equal to the total rule count for that jurisdiction plus federal.
- No coverage target; the rule tests are the safety net.

## Boundaries

**Always**
- Keep `evaluate_rule` pure and model-free.
- Validate agent output against `ChecklistResult` before returning it.
- Append to the audit log on every tool call, result, and confirmation.
- Render the fixed disclaimer on every result: "This checklist is a starting point generated from seed rules. It is not legal advice. A licensed broker must confirm requirements before use."
- Run `pytest -q` before every commit.

**Ask first**
- Adding any dependency beyond the scaffold's `requirements.txt`.
- Adding rules for a jurisdiction other than DC/MD/VA.
- Adding intake fields beyond the six.
- Any change to the deploy script.

**Never**
- Let the model decide rule applicability.
- Return a checklist that failed schema validation.
- Commit `.env`, API keys, or service-account JSON.
- Auto-confirm a checklist or expose `/api/confirm` to anything but the UI button.
- Present output as a compliance determination.

## Success Criteria

- [ ] All four fixtures pass `pytest -q` with exact rule-id sets, offline.
- [ ] Live demo: changing year_built from 1985 to 1970 on the MD fixture adds lead paint to Required within one request cycle.
- [ ] Live demo: toggling DC seller_occupancy to tenant_occupied adds TOPA to both Required and Broker Review.
- [ ] `/audit` shows every rule evaluated for the last request and the human confirmation entry after the button is pressed.
- [ ] Deployed to Cloud Run; public URL responds in under 5 seconds for a checklist request.
- [ ] The disclaimer appears on every result page.

## Demo Script (3 minutes)

1. "Disclosures differ by jurisdiction and by facts. Agents miss them. This tool recommends; a broker confirms." (20s)
2. MD 1985 single-family → checklist. Change to 1970 → lead paint appears with citation. (40s)
3. DC condo, flip to tenant-occupied → TOPA appears in Required *and* in Broker Review with the exemption note. "This is where the agent stops." (40s)
4. Press Confirm as broker. Open `/audit`: every rule evaluated, the result, the confirmation. (40s)
5. "Same scaffold as our other two entries — deterministic rules, model for language, human for decisions." (20s)

## Open Questions

- Which Gemini model is fastest on the day's platform access? Default to the Flash-class model.
- Confirm current statute citations for each seed rule before the demo (DC underground storage tank and MD lead registration are the least certain).
- Should `likely` tier be used at all in v1, or collapse to `required` + `broker_review`? Default: implement the field, populate it only if a rule is tagged `likely`; no seed rules use it.

---

## Resolved during build planning

Decisions taken between this spec and `BUILD.md`. The spec above remains the
authority on intent; these record where the build makes something concrete that
the spec left open, and where it deliberately departs.

1. **The `applies_when` grammar gains a `ne` operator.** The spec allows equality
   on enums and bools plus `lt`/`gte` on `year_built`. Three rules —
   `dc_hoa_disclosure`, `md_hoa_disclosure`, `va_poa_packet` — need "has an
   association **and is not** a condo", which equality alone cannot express.
   Legal operators are therefore: a bare scalar (equality), `{lt: N}`,
   `{gte: N}`, `{ne: value}`. Anything else raises at load time rather than
   being silently ignored.

2. **The financing and property-type review flags live in `federal.yaml`.** The
   spec's file list annotates that file "Federal rules (lead paint)", but
   `fin_fha_appraisal`, `fin_va_wdi`, and `prop_multi_family_review` are not
   jurisdiction-specific and would otherwise be triplicated across DC, MD, and
   VA. `federal.yaml` is therefore read as "rules that apply regardless of
   jurisdiction". No fifth rule file is added.

3. **The server, not the agent, is the authority on bucket membership.** The
   spec has the agent loop over `evaluate_rule` and compose the result. The
   build keeps that loop — it is what makes the audit log's "every rule the
   agent evaluated" true — but adds `compose_buckets`, a pure-Python computation
   run independently on every request. Where the two disagree, `compose_buckets`
   wins and the discrepancy is written to the audit log as an error entry. This
   makes the spec's determinism guarantee structural rather than instructed.

4. **`confirmed_by` is a typed name, not a verified identity.** There is no
   authentication in this build. The confirmation audit entry records what
   someone typed into a text box. The README's Limitations section and the demo
   patter must both say so. Claiming the audit log proves *who* confirmed would
   be precisely the overclaim this product exists to argue against.

5. **An unset `GOOGLE_API_KEY` puts the app in offline mode.** Reason text is
   taken verbatim from each rule's `summary` field, no model is called, and the
   result carries `mode: "offline"` in both the audit entry and the rendered
   page. Bucket membership, citations, tiers, the audit log, and the confirm
   flow are all unchanged, because none of them ever depended on the model. This
   is not a stub and not a silent fallback: it is a declared mode, and it is why
   the full test suite and smoke script run green with no API key. It does mean
   an offline demo shows a deterministic rules engine rather than an ADK agent —
   a safety net, not the plan.

### Known imprecision in the spec above, accepted rather than edited

The Testing Strategy fixtures are written as positional prose — `MD,
single_family, 1970, no association, owner_occupied, conventional` — so field
names are absent and `has_association` appears as "no association" rather than a
boolean. Values and ordering match the input table exactly. `BUILD.md` Prompt 5
pins all four fixtures as explicit JSON with field names and booleans, which
resolves the ambiguity downstream; the prose above is left as written.

### Deployment

Cloud Run deployment is **deferred as of 2026-08-28**; this build targets
localhost. The success criterion "Deployed to Cloud Run; public URL responds in
under 5 seconds" is therefore unmet by design. Every other success criterion is
unaffected. `BUILD.md` Prompt 11 is retained, unrun, for if a GCP project
becomes available.
