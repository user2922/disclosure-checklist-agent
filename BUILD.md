# BUILD.md — Disclosure Checklist Agent

DevFest DC 2026 Build-a-thon, Entry 3. Eleven numbered prompts, each executed one
at a time, each ending in a checkpoint that can actually be checked.

Source spec: `SPEC.md` in this folder. Read it before Prompt 1.

---

## How to use this document

**PASTE INTO THE AGENT** — the fenced blocks under `## Prompt N`. One per session.
Run the checkpoint after each before moving on.

**READ YOURSELF, DO NOT PASTE** — everything else: the app specification, the
standing rules (Prompt 1 captures them into `CLAUDE.md`), the checkpoints (you ask
the agent to "Run Checkpoint N"), the spot checks, and this section.

Every session after the first, open with:

```
Read CLAUDE.md, SPEC.md, and BUILD_STATUS.md before doing anything.
Report: what phase we're on, what's complete, what's next.
Then wait for my instruction before changing any files.
Non-negotiables from CLAUDE.md apply to this entire session.
```

---

## How this sequence differs from the standard one, and why

The standard Gauntlet sequence is sixteen prompts shaped around a Next.js +
Supabase + Stripe SaaS. This app is Python, has no database, no accounts, and no
payments, and has a fifty-minute build window. Every deviation is listed here so
none of them is silent.

| Standard prompt | Here | Reason |
|---|---|---|
| 2b security utilities | Folded into Prompt 2 | No CSRF-bearing auth surface; the only middleware needed is an Origin check and a rate limiter |
| 3 Database schema | **Prompt 3, Pydantic schemas** | The Pydantic models are this app's shared spine — the thing two or more later prompts touch. Same ownership rule applies: a shape used by ≥2 prompts is defined in Prompt 3 and nowhere else |
| 4 Types & validation | Merged into Prompt 3 | Pydantic is both, in one file |
| 6 Authentication | **Cut** | No accounts. `confirmed_by` is a typed name, not an identity claim. See the honesty note below |
| Stripe tail | **Cut** | No payments |
| Legal/GDPR tail | **Prompt 9, disclaimer** | No personal data is collected. The legal surface is the fixed disclaimer, which is a product requirement, not a footer |
| Polish tail | Folded into Prompt 9 | One page and one log view |
| Testing & CI tail | **Moved up to Prompt 5** | The rule tests are the determinism proof and the demo's whole claim. They come before anything that could depend on them, not after |

**Honesty note on `confirmed_by`.** This build has no authentication, so the
confirmation entry records *a name someone typed*, not a verified broker. Say that
in the README and say it on stage if asked. Claiming the audit log proves who
confirmed would be exactly the overclaim the app is built to argue against.

**Cut order if you run out of time.** Drop Prompt 11 (deploy) and demo from
localhost. Then Prompt 10's smoke script. Prompts 1–9 are the demo. Prompt 6, the
audit log, is not a cut candidate — it is the pitch.

**Deployment decision, taken 2026-08-28: localhost only.** Prompt 11's deploy is
deferred rather than dropped — the prompt stays, unrun, so it is there if a GCP
project turns up (ask whoever owns Entry 1's deploy script; it may already exist).
Consequence, stated plainly: SPEC.md's success criterion "Deployed to Cloud Run;
public URL responds in under 5 seconds" goes unmet, and the demo runs from a
laptop. Every other success criterion is unaffected. Prompt 11's README work is
**not** deferred — fold it into the Prompt 10 session, because the Limitations
section is a product requirement, not a deploy artifact.

**Local development on this machine.** Windows on ARM64, Python 3.12.10 at
`py -3.12`. SPEC.md's setup line is bash; on Windows the equivalents are:

```
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

If PowerShell refuses the activate script, `Set-ExecutionPolicy -Scope Process
RemoteSigned` for that window. `scripts/smoke.sh` and `scripts/scan-secrets.sh`
are bash — run them from Git Bash, which is present.

**Rough budget:** 1 · 3min — 2 · 4min — 3 · 4min — 4 · 5min — 5 · 6min —
6 · 3min — 7 · 8min — 8 · 6min — 9 · 6min — 10 · 3min — 11 · 5min.

---

## App specification

| | |
|---|---|
| **Name** | Disclosure Checklist Agent |
| **What** | Six transaction facts in, a cited seller-disclosure checklist out, plus a broker-review bucket. The agent recommends; a human confirms. |
| **Users** | Licensed DMV real estate agents and transaction coordinators |
| **Accounts** | None. Single shared instance, no login |
| **Tiers** | None. Not monetized |
| **Data stored** | An append-only JSONL audit log. No personal data, no database |

**Routes** — this list is the source of truth; Prompt 8 must create exactly these.

| Method | Route | Returns |
|---|---|---|
| GET | `/` | Intake form, and results after a submit |
| POST | `/api/checklist` | `ChecklistResult` JSON — 422 bad facts, 429 rate limited, 503 model unavailable |
| POST | `/api/confirm` | Confirmation entry — 403 bad Origin, 404 unknown `result_id` |
| GET | `/audit` | Audit log viewer, HTML |
| GET | `/api/audit` | Audit entries as JSON, optional `result_id` filter |
| GET | `/health` | `{"status":"ok","model":"<GEMINI_MODEL>"}` |

**Pinned stack.** Python 3.12 · FastAPI · Uvicorn · Pydantic v2 · pydantic-settings
· Jinja2 · PyYAML · google-adk · pytest · httpx · ruff. Pin every version in
`requirements.txt` at Prompt 2 and never float one afterwards.

**Environment variables**

| Bucket | Var | Note |
|---|---|---|
| REQUIRED | `GEMINI_MODEL` | One spelling, everywhere. Never a hardcoded model id |
| REQUIRED | `APP_URL` | Origin allowed to POST `/api/confirm` |
| REQUIRED | `AUDIT_LOG_PATH` | Default `./audit.jsonl` |
| FEATURE | `GOOGLE_API_KEY` | Unset means **offline mode**: reasons come from each rule's `summary` and no model is called. Set it from Prompt 7 for the live agent |
| OPTIONAL | `RATE_LIMIT_PER_MINUTE` | Default 10 |
| OPTIONAL | `MAX_MODEL_CALLS_PER_DAY` | Default 200 |

---

## Standing rules

These go into `CLAUDE.md` at Prompt 1 and are re-read every session. They are the
Gauntlet Phase-Zero non-negotiables, adapted to this stack. Rules that do not
apply are listed as not applying, so nobody re-adds the scaffolding they imply.

**Rule 0 — The model never decides applicability.** Rule membership is computed by
`compose_buckets` in pure Python. The model writes one sentence of prose per
applied item and nothing else. This is the product; it is not an implementation
preference.

**Rule 1 — No secrets in code.** All secrets in environment variables.
`.env.example` holds placeholder names only. `.env`, `.env.local`, and any
service-account JSON are gitignored before the first commit.

**Rule 2 — Validate env at startup.** `app/config.py` holds a `pydantic-settings`
`Settings` object. The app crashes on boot if a REQUIRED var is missing. Nothing
anywhere reads `os.environ` directly.

**Rule 3 — Row-level security.** Not applicable: there is no database. The
equivalent guarantee here is that the audit log is append-only and is never
rewritten, truncated, or edited in place.

**Rule 4 — Fail-closed limits and caching on the metered API.** Gemini is metered,
so all three are mandatory: a per-IP rate limit that returns 429 when the limiter
itself errors, never open; a `MAX_MODEL_CALLS_PER_DAY` ceiling checked before every
call; and a cache keyed on the SHA-256 of the canonical `TransactionFacts` JSON, so
the same facts are never billed twice.

**Rule 5 — Generic errors to the client.** Clients get a generic message and a
`result_id`. Stack traces, file paths, and provider errors go to the server log
only.

**Rule 6 — Auth on every route.** Not applicable: no accounts. The equivalent
guarantee is that `/api/confirm` accepts only a `result_id` that already exists in
the audit log, and returns 404 — never 403 — when it does not.

**Rule 7 — Pydantic validation on every input.** Every request body is parsed into
a model. Every query parameter is typed. Invalid input returns 422 with a generic
message.

**Rule 8 — Webhook idempotency.** Not applicable: no webhooks. The equivalent
guarantee is that confirming the same `result_id` twice appends a second entry and
never mutates the first.

**Rule 9 — No placeholder code.** No `TODO`, no commented-out branches, no stub
returning fake data, no mock rule. Every function called is implemented. Offline
mode is not a stub and does not violate this rule: it returns each rule's own
`summary` text from the YAML, records `mode: "offline"`, and says so on the page.
A fallback that invented prose, or that stayed silent about not calling the
model, would violate it.

**Rule 10 — Origin check on mutations.** `POST /api/confirm` compares the `Origin`
header against `APP_URL` and returns 403 on a mismatch or a missing header. This is
what makes "only the button can confirm" a real control rather than a claim.

**Rule 11 — Double-submit prevention.** The confirm button disables itself on
submit and does not re-enable.

**Rule 12 — Server-side auth routes.** Not applicable.

**Rule 13 — No unbacked claims.** The fixed disclaimer renders on every result, in
full, verbatim. Nothing in the UI, the README, or the pitch may describe the output
as a compliance determination, a legal review, or advice. No "compliant",
"certified", or "verified" badge anywhere.

**Rule 14 — Model id in an env var.** `GEMINI_MODEL`, one spelling, read through
`Settings`, logged once at startup. A model-not-found error surfaces as its own
error type, not a generic 500.

**Rule 15 — Track model cost per operation.** Every model call appends a
`model_call` audit entry with the `result_id`, input tokens, output tokens, and
latency in milliseconds.

**Rule 16 — Dev/prod separation.** The same code runs in both, driven only by env
values. Dev values live in `.env` (gitignored). Production values live only in the
Cloud Run service configuration.

---
## Prompt 1 — Spec validation and standing rules

```
Read SPEC.md in full. Write no application code in this phase. Your job is to
prove the spec is internally consistent before anything is built on it, then
produce the two files every later session re-reads.

First, run these consistency checks and report each as PASS or FAIL with the
line you checked:

1. The routes in SPEC.md's Project Structure comment for app/main.py match the
   routes in the Agent flow section, and both match this set: GET /, POST
   /api/checklist, POST /api/confirm, GET /audit. Note that GET /api/audit and
   GET /health are additions from BUILD.md and are expected to be absent from
   SPEC.md.
2. The six TransactionFacts fields in the input table appear with identical
   names and identical enum values in the Testing Strategy fixtures.
3. Every rule named in the Testing Strategy expectations exists in the Seed
   rules section.
4. The three tier values in ChecklistItem's Literal match the tier values used
   in the seed rules and in the ChecklistResult bucket names.
5. The disclaimer string appears exactly once in SPEC.md, under Boundaries.

Report every FAIL and stop for my decision. Do not silently fix the spec.

Then create these files:

1. CLAUDE.md — the Standing Rules section of BUILD.md copied verbatim, all
   seventeen rules including Rule 0 and including the four marked "not
   applicable", followed by the exact disclaimer string, the six field names
   with their exact enum values, and the route table. This file is the
   agent's memory between sessions; it must be readable standalone.

2. SPEC.md — leave the existing file as the authority. Append a short section
   headed "Resolved during build planning" recording: the applies_when grammar
   is extended with a `ne` operator; the financing and property-type review
   flags live in federal.yaml alongside the lead-paint rule; the server, not
   the model, is the authority on bucket membership; there is no
   authentication, so confirmed_by is a typed name and not a verified identity;
   and an unset GOOGLE_API_KEY puts the app in offline mode, where reason text
   comes from each rule's summary and the mode is recorded and displayed.

3. BUILD_STATUS.md — a checklist of the eleven prompts, all unchecked, with a
   "current phase" line at the top.

Do not create app/, tests/, or requirements.txt yet.
```

### Checkpoint 1

- [ ] All five consistency checks reported, each with an explicit PASS or FAIL
- [ ] `CLAUDE.md` contains seventeen numbered rules including Rule 0
- [ ] The disclaimer string in `CLAUDE.md` is byte-identical to the one in `SPEC.md`
- [ ] `CLAUDE.md` lists all six field names with their exact enum values
- [ ] `SPEC.md` has a "Resolved during build planning" section naming all five decisions
- [ ] `BUILD_STATUS.md` lists eleven prompts, all unchecked
- [ ] `ls app tests requirements.txt` fails — no code was written this phase

---

## Prompt 2 — Project scaffold, config, and secret hygiene

```
Set up the project skeleton and the configuration layer. Everything later
depends on Settings existing and being validated.

1. requirements.txt — pin an exact version for each of: fastapi, uvicorn,
   pydantic (2.x), pydantic-settings, jinja2, pyyaml, google-adk, pytest,
   httpx, ruff, watchfiles. Pin the versions that actually resolve, by
   installing first and reading them back — do not invent version numbers.
   If the shared ADK scaffold already provides a requirements.txt, add only
   what is missing and tell me which packages you added before installing —
   SPEC.md requires asking before new dependencies.

   Two win-arm64 constraints, learned the hard way on this machine: use plain
   uvicorn, never uvicorn[standard], because that extra pulls httptools which
   has no win_arm64 wheel and fails to compile. And pin cryptography at 46.0.3
   or later, because google-adk's resolver otherwise picks an older release
   with no win_arm64 wheel and falls back to building Rust from source.

2. app/config.py — a pydantic-settings Settings class reading, with these exact
   names: GEMINI_MODEL (str, required), APP_URL (str, required),
   AUDIT_LOG_PATH (str, default "./audit.jsonl"), GOOGLE_API_KEY (str or None,
   default None), RATE_LIMIT_PER_MINUTE (int, default 10),
   MAX_MODEL_CALLS_PER_DAY (int, default 200). Expose a module-level
   get_settings() memoized with functools.lru_cache. Raise on a missing
   required var with a message naming the variable. Nothing else in the
   codebase may read os.environ.

3. .env.example — the six vars above, bucketed under three comment headers
   REQUIRED, FEATURE, OPTIONAL, placeholder values only, never a real key.

4. .gitignore — .env, .env.local, *.jsonl, .venv, __pycache__, *.json files
   matching a service account pattern.

5. pyproject.toml — ruff config only: line-length 100, target-version py312,
   select E, F, I, UP.

6. scripts/scan-secrets.sh — grep the tracked tree for an AIza-prefixed key, a
   private_key JSON field, and a sk- prefixed token. Exit 1 on any hit, exit 0
   clean, and print the file count it scanned so "clean" is distinguishable
   from "scanned nothing".

7. app/main.py — a FastAPI app with GET /health only, returning status ok and
   the configured model id. Log the model id once at startup.

Then run: ruff check ., scripts/scan-secrets.sh, and uvicorn against /health.
```

### Checkpoint 2

- [ ] `uvicorn app.main:app --port 8080` starts and `GET /health` returns 200 with the model id
- [ ] Unsetting `GEMINI_MODEL` makes the app refuse to start, with the variable named in the message
- [ ] `grep -rn "os.environ" app/` returns only `app/config.py`
- [ ] `scripts/scan-secrets.sh` exits 0 and prints a nonzero file count
- [ ] `.env.example` has all six vars under REQUIRED / FEATURE / OPTIONAL headers
- [ ] `git check-ignore .env` succeeds
- [ ] `ruff check .` exits 0

> **Spot check — environment and secrets.** Before Prompt 3:
> - [ ] No real key value anywhere in the tracked tree, including `.env.example`
> - [ ] **Canary the scanner.** Put a Google-key-shaped string into a tracked file —
>   the four characters `AIza` followed by 35 alphanumerics — run
>   `scripts/scan-secrets.sh`, confirm it exits 1, then remove it. Construct the
>   string rather than pasting one from here, or this document becomes a permanent
>   hit and the scanner gets ignored. A scanner nobody has watched fail is decoration.
> - [ ] The scanner reports a nonzero file count, so an empty scan cannot read as a pass
>
> **Spot check — connection pooling: SKIPPED, no database.** Recorded here so the
> omission is deliberate rather than forgotten.

---

## Prompt 3 — Pydantic schemas, the shared spine

```
Create app/schemas.py. This file owns every shape used by two or more later
prompts. No later prompt may redefine any of these; it imports them.

1. Four str-valued Enums with these exact members and values:
   Jurisdiction: DC, MD, VA (values uppercase).
   PropertyType: single_family, condo, townhome_hoa, multi_family.
   SellerOccupancy: owner_occupied, tenant_occupied, vacant.
   Financing: conventional, fha, va, cash.
   Enum values are the lowercase strings above except Jurisdiction. These
   strings appear in YAML rule files, JSON fixtures, and form values — one
   spelling each, everywhere.

2. TransactionFacts — all six fields required, no defaults: jurisdiction,
   property_type, year_built (int, ge=1800, le=2026), has_association (bool),
   seller_occupancy, financing. Configure the model frozen so facts cannot be
   mutated after validation. Add a method canonical_hash() returning the
   SHA-256 hex digest of the model dumped to JSON with sorted keys — Prompt 7's
   cache key depends on this being stable.

3. Tier — a Literal type alias of exactly "required", "likely", "review".

4. ChecklistItem — rule_id, name, citation, tier (Tier), reason (str, min
   length 1), review_note (str or None, default None).

5. ChecklistResult — facts (TransactionFacts), required, likely, broker_review
   (each list[ChecklistItem], default empty), disclaimer (str), rules_evaluated
   (int, ge=1), result_id (str), mode (Literal of exactly "live", "cached",
   "offline" — how the reason prose was produced). Add a validator rejecting a
   disclaimer that is not byte-identical to the DISCLAIMER constant, so an
   unvalidated result cannot be returned.

6. ConfirmRequest — result_id (str), confirmed_by (str, min length 1, max 120).

7. AuditEntry — timestamp (datetime, UTC), kind (Literal of exactly
   "rule_evaluated", "model_call", "result", "confirmation", "error"),
   result_id (str), payload (dict).

8. DISCLAIMER — a module-level UPPER_CASE constant holding the disclaimer
   string from SPEC.md, byte-identical, including punctuation.

Type-hint every signature. No business logic in this file.
```

### Checkpoint 3

- [ ] `TransactionFacts(year_built=1799, ...)` raises a `ValidationError`
- [ ] `TransactionFacts(year_built=2027, ...)` raises a `ValidationError`
- [ ] Assigning to a field on a constructed `TransactionFacts` raises — the model is frozen
- [ ] The same facts produce the same `canonical_hash()` across two Python processes
- [ ] `ChecklistResult` with a disclaimer one character off from `DISCLAIMER` is rejected
- [ ] `DISCLAIMER` is byte-identical to the string in `SPEC.md` (diff them)
- [ ] `ChecklistItem` with `tier="mandatory"` is rejected
- [ ] `ChecklistResult` with `mode="fake"` is rejected
- [ ] `ruff check .` exits 0

---

## Prompt 4 — Rule data files and loader

```
Rules are data. Nothing in this phase reads or writes Python rule logic — that
is Prompt 5.

Create four YAML files under app/rules/ using exactly these rule ids. Later
prompts and the tests reference them by id, so a typo here is a build-wide
break.

federal.yaml — applies regardless of jurisdiction:
  fed_lead_paint            year_built lt 1978, tier required
  fin_fha_appraisal         financing fha, tier review
  fin_va_wdi                financing va, tier review
  prop_multi_family_review  property_type multi_family, tier review

dc.yaml:
  dc_sellers_disclosure     all, tier required
  dc_topa                   seller_occupancy tenant_occupied, tier required
  dc_condo_resale           property_type condo, tier required
  dc_hoa_disclosure         has_association true AND property_type ne condo,
                            tier required
  dc_underground_tank       all, tier review

md.yaml:
  md_residential_disclosure all, tier required
  md_condo_resale           property_type condo, tier required
  md_hoa_disclosure         has_association true AND property_type ne condo,
                            tier required
  md_lead_registration      seller_occupancy tenant_occupied AND year_built lt
                            1978, tier review

va.yaml:
  va_rpda                   all, tier required
  va_condo_resale           property_type condo, tier required
  va_poa_packet             has_association true AND property_type ne condo,
                            tier required
  va_septic_well            all, tier review

Every rule carries: id, name, citation, applies_when, tier, summary. Add
review_note to dc_topa, dc_underground_tank, dc_hoa_disclosure,
md_lead_registration, va_septic_well, fin_fha_appraisal, fin_va_wdi, and
prop_multi_family_review. Take the names, citations, and note wording from
SPEC.md's Seed rules section. A rule that applies to every transaction has an
empty applies_when mapping, not a missing key.

Then app/rules/loader.py:

1. A Rule Pydantic model mirroring those keys, with tier typed as the Tier
   alias from schemas.py.
2. load_all() parsing all four files at import, raising on an unknown key, a
   duplicate id across any two files, or a tier outside the Tier alias.
3. rules_for(jurisdiction) returning an ordered dict of federal rules followed
   by that jurisdiction's rules, keyed by id. Never mutate the cached rules.

The applies_when grammar: a bare scalar means equality; {lt: N} and {gte: N}
compare integers; {ne: value} means not-equal. Nothing else is legal, and an
unrecognised operator must raise at load time, not be silently ignored.
```

### Checkpoint 4

- [ ] `rules_for("DC")` returns 9 rules, `rules_for("MD")` 8, `rules_for("VA")` 8
- [ ] The first four ids in every jurisdiction's result are the federal ones, in file order
- [ ] Adding a duplicate id to `md.yaml` makes the import raise, naming the id
- [ ] Adding `applies_when: {year_built: {gt: 1990}}` raises at load time on the unknown operator
- [ ] Every rule listed above exists with a non-empty `citation`
- [ ] All eight rules named above have a `review_note`; no other rule does
- [ ] `grep -rn "lead" app/*.py` returns nothing — no disclosure is hardcoded in Python

---
## Prompt 5 — Deterministic engine and the rule tests

```
This is the phase the product's claim rests on. Membership in the three buckets
is decided here, in pure Python, and never by the model.

1. app/tools.py — three functions, each type-hinted, each with a docstring the
   ADK will read:

   get_rules(jurisdiction: str) -> list[dict] — returns the id, name, citation
   and tier of every rule for that jurisdiction. Never returns applies_when;
   the model has no business reading the conditions.

   evaluate_rule(rule_id: str, facts: TransactionFacts) -> dict — returns
   applies, tier and review_note. Pure. Never calls the model. Never raises on
   an unknown rule id; returns applies False, tier "review", review_note None.
   A rule with an empty applies_when applies to every transaction.

   A private _match(field, condition, facts) implementing the grammar: bare
   scalar is equality, {lt: N} and {gte: N} on integers, {ne: value} not-equal.
   Compare enum members by their value so a YAML string matches.

2. app/engine.py — compose_buckets(facts) -> tuple of three lists of rule ids
   plus an int. Iterate rules_for(facts.jurisdiction) in order, call
   evaluate_rule on every one, and build: required (applied, tier required),
   likely (applied, tier likely), broker_review (applied and review_note is not
   None, regardless of tier, plus any applied rule of tier review). A rule with
   tier required and a review_note appears in both required and broker_review.
   Return the total count of rules evaluated, applied or not. Sort nothing —
   file order is the display order, and it must be stable.

3. tests/fixtures/ — four JSON files of TransactionFacts:
   md_1970_sfh.json   MD single_family 1970 false owner_occupied conventional
   md_1985_sfh.json   same, year_built 1985
   dc_condo_tenant.json  DC condo 2005 true tenant_occupied cash
   va_townhome_hoa.json  VA townhome_hoa 1995 true owner_occupied va

4. tests/test_rules.py — assert exact sets, not membership:
   md_1970  required {fed_lead_paint, md_residential_disclosure}, review set()
   md_1985  required {md_residential_disclosure}, review set()
   dc_condo required {dc_sellers_disclosure, dc_topa, dc_condo_resale},
            review {dc_topa, dc_underground_tank}
   va_town  required {va_rpda, va_poa_packet},
            review {fin_va_wdi, va_septic_well}
   Also assert rules_evaluated is 8, 8, 9, 8 respectively. Add a determinism
   test running compose_buckets twenty times on one fixture and asserting all
   twenty results are equal. Add a test that an unknown rule id returns applies
   False rather than raising.

5. tests/test_schemas.py — an out-of-range year_built and an invalid
   jurisdiction each raise ValidationError.

No network, no API key, no model. pytest -q must pass with both unset.
```

### Checkpoint 5

- [ ] `pytest -q` exits 0 with `GOOGLE_API_KEY` and `GEMINI_MODEL` both unset
- [ ] The four fixtures assert exact set equality, not `in` — read the file and confirm
- [ ] Changing `md_1970_sfh.json` to 1985 makes the lead-paint assertion fail
- [ ] `dc_topa` appears in both the required set and the broker-review set
- [ ] The determinism test runs `compose_buckets` at least 20 times and compares results
- [ ] `evaluate_rule("no_such_rule", facts)` returns `applies` False and does not raise
- [ ] `grep -n "model\|genai\|adk" app/tools.py app/engine.py` returns nothing

> **Spot check — determinism.** Before Prompt 6:
> - [ ] `rules_evaluated` equals the full rule count for the jurisdiction plus federal
>   in all four fixtures — 8, 8, 9, 8. A number lower than that means the loop skipped
>   rules and the audit log will under-report
> - [ ] Deliberately break `_match` so `lt` compares backwards and confirm at least two
>   fixture tests go red. A test suite nobody has watched fail is not a safety net

---

## Prompt 6 — Append-only audit log

```
The audit log is the pitch, not plumbing. It must record every rule the agent
considered, not only the ones that applied.

Create app/audit.py:

1. append(kind, result_id, payload) -> None. Opens AUDIT_LOG_PATH from Settings
   in append mode, writes one JSON object per line, flushes and fsyncs, closes.
   Never opens the file for writing or truncating. Never rewrites a line. The
   object has exactly four keys: timestamp (UTC, ISO-8601, with a Z suffix),
   kind, result_id, payload. Validate it through AuditEntry before writing so a
   malformed entry cannot reach the file.

2. Five kinds, matching the AuditEntry Literal exactly: rule_evaluated,
   model_call, result, confirmation, error.

3. append_rule_evaluations(result_id, facts, evaluations) -> None. One
   rule_evaluated entry per rule considered, applied or not, each carrying
   rule_id, applies, tier, and the facts hash. This is what makes "every rule
   the agent evaluated" true rather than aspirational.

4. read_entries(limit=200, result_id=None) -> list[AuditEntry]. Reads the file,
   parses each line, returns newest first, filtered by result_id when given. A
   malformed line is skipped and counted, never raised — a corrupt line must
   not take down the audit view. Return the skipped count alongside.

5. result_exists(result_id) -> bool. True only if a result entry with that id
   has been written. Prompt 8's /api/confirm depends on this for its 404.

6. If AUDIT_LOG_PATH's parent directory does not exist, create it at first
   write. If the file does not exist, reading returns an empty list rather than
   raising.

Add a README note, and be ready to say it on stage: Cloud Run's filesystem is
ephemeral, so the log lives only for the life of the instance. A production
deployment writes to Firestore or a GCS object. Do not pretend otherwise in
the UI.

Add tests/test_audit.py using a tmp_path fixture: appending twice leaves two
lines, the first line is unchanged after the second write, and a hand-corrupted
line is skipped by read_entries with the skip counted.
```

### Checkpoint 6

- [ ] Two `append` calls leave exactly two lines, and line 1 is byte-identical before and after the second
- [ ] `append` with `kind="fabricated"` raises before writing anything to the file
- [ ] `read_entries` on a file with a corrupted middle line returns the good entries and a skip count of 1
- [ ] `read_entries` on a nonexistent path returns an empty list, not an exception
- [ ] `result_exists` returns False for an id that only has `rule_evaluated` entries
- [ ] `append_rule_evaluations` on the DC fixture writes 9 lines
- [ ] Every timestamp parses as UTC ISO-8601 and ends in `Z`
- [ ] `pytest -q` exits 0

---

## Prompt 7 — ADK agent, model wiring, and cost control

```
The agent phrases; it does not decide. Wire it so that is structurally true,
not just instructed.

1. app/agent.py — an ADK agent whose model id comes only from
   Settings.GEMINI_MODEL. Register get_rules and evaluate_rule from tools.py as
   its tools; register nothing else. The system instruction states that the
   agent must call evaluate_rule for every id returned by get_rules, must not
   infer applicability from its own knowledge of law, and must return one
   sentence per applied rule naming the triggering fact.

2. run_checklist(facts) -> ChecklistResult, the only entry point Prompt 8
   calls, in this order:
   a. Generate a result_id (uuid4 hex).
   b. Call compose_buckets(facts). Its output is the authority on membership.
      Write the rule evaluations to the audit log.
   c. If GOOGLE_API_KEY is unset, enter offline mode: take each applied rule's
      reason verbatim from its summary field in the YAML, log a model_call
      entry with mode "offline" and zero tokens, and skip to (g). Never
      fabricate prose offline and never degrade silently — the mode is
      recorded here and displayed by Prompt 9.
   d. Check the cache keyed on facts.canonical_hash(). On a hit, reuse the
      cached reason strings, log a model_call entry with mode "cached" and
      zero tokens, and skip to (g).
   e. Check the rate limit and the daily ceiling. Over either, raise the
      corresponding error without calling the model.
   f. Invoke the agent for the prose, logging a model_call entry with mode
      "live". If the agent's own applied-rule set differs from
      compose_buckets', log an error entry naming both sets and use
      compose_buckets' — never the agent's.
   g. Build ChecklistResult with DISCLAIMER, rules_evaluated and mode from the
      steps above, and validate it. On ValidationError, retry the model once;
      on a second failure raise ModelOutputError. Never return a partial or
      unvalidated checklist. Offline mode never retries — a summary that fails
      validation is a rule-data bug, not a model failure.
   h. Append a result audit entry carrying the mode, then return.

3. app/limits.py — an in-process per-IP sliding window of
   RATE_LIMIT_PER_MINUTE, and a daily counter against MAX_MODEL_CALLS_PER_DAY.
   Both fail closed: if the limiter itself errors, the request is blocked.

4. app/cache.py — a bounded dict, max 256 entries, keyed on the facts hash,
   holding rule_id-to-reason mappings. Cache hits must not call the model.

5. Named exceptions: RateLimitExceeded, DailyCeilingExceeded,
   ModelUnavailable, ModelOutputError. A model-not-found response from the
   provider raises ModelUnavailable with the configured id in the message.

Log each model call to the audit log with its mode, input tokens, output
tokens, and latency in milliseconds.
```

### Checkpoint 7

- [ ] With `GOOGLE_API_KEY` unset, `run_checklist` returns a valid result whose reasons equal the rules' `summary` strings
- [ ] That offline result carries `mode: "offline"` in both the audit entry and the returned object — no silent degradation
- [ ] Submitting identical facts twice makes exactly one model call — the second logs `mode: "cached"`
- [ ] With `RATE_LIMIT_PER_MINUTE=2`, the third request in a minute raises `RateLimitExceeded` before any model call
- [ ] Forcing the limiter to raise internally results in a blocked request, not an allowed one
- [ ] With `MAX_MODEL_CALLS_PER_DAY=1`, the second uncached request raises `DailyCeilingExceeded`
- [ ] Setting `GEMINI_MODEL` to a nonexistent id raises `ModelUnavailable` naming that id
- [ ] Forcing the model to return an unusable `reason` triggers exactly one retry, then `ModelOutputError`
- [ ] A `model_call` audit entry exists per call with both token counts and a latency
- [ ] `run_checklist` on the DC fixture returns the same three id sets as `compose_buckets`

> **Spot check — metered API controls.** Before Prompt 8:
> - [ ] The rate limiter is proven in **both** directions: a request under the limit is
>   allowed, a request over it is blocked. Only testing the block half is the common miss
> - [ ] No model call happens on a cache hit — assert on the call count, not the latency
> - [ ] `GOOGLE_API_KEY` appears in no log line, no audit entry, and no error message
>
> **Spot check — payment integration: SKIPPED, no payments.** Recorded deliberately.

---

## Prompt 8 — FastAPI routes

```
Wire the HTTP layer. No business logic in main.py — routes validate, call into
agent.py and audit.py, and translate exceptions to status codes.

Create exactly these routes, and no others:

1. GET / — renders the intake form. On no query, defaults matching
   md_1985_sfh so the demo's first submit is one click.

2. POST /api/checklist — body parsed into TransactionFacts. Returns 200 with
   the ChecklistResult. 422 on a validation failure, with a generic message and
   the field names only. 429 on RateLimitExceeded or DailyCeilingExceeded, with
   a Retry-After header. 503 on ModelUnavailable or ModelOutputError. Accepts
   both a JSON body and a form-encoded submit from the page, returning JSON for
   the former and the rendered page for the latter.

3. POST /api/confirm — body parsed into ConfirmRequest. Before anything else,
   compare the Origin header to Settings.APP_URL; a mismatch or a missing
   Origin returns 403 and appends an error audit entry. Then check
   result_exists(result_id): unknown returns 404, never 403 — a 403 would
   confirm the id exists. On success append a confirmation entry with
   result_id, confirmed_by, and the timestamp, and return it.

4. GET /audit — renders audit.html with the most recent 200 entries and the
   skipped-line count.

5. GET /api/audit — the same data as JSON, with an optional result_id query
   parameter, typed and validated.

6. GET /health — status ok and the configured model id. Never the API key.

Add a global exception handler: any unhandled exception appends an error audit
entry with the traceback, logs it server-side, and returns 500 with a generic
body carrying only a correlation id. No stack trace, no file path, and no
provider message ever reaches the client.

Register Jinja2 templates and a static mount if the scaffold provides one. Keep
route handlers under fifteen lines each; anything longer belongs in agent.py.
```

### Checkpoint 8

- [ ] `POST /api/checklist` with `year_built: 1799` returns 422 and no stack trace in the body
- [ ] `POST /api/checklist` with `jurisdiction: "PA"` returns 422
- [ ] `POST /api/confirm` with an `Origin` of `https://evil.example` returns 403
- [ ] `POST /api/confirm` with a valid Origin and an unknown `result_id` returns 404, not 403
- [ ] `POST /api/confirm` twice with the same id returns 200 twice and leaves two audit entries
- [ ] Raising inside a handler returns a 500 whose body has a correlation id and nothing else
- [ ] `GET /health` response contains no substring of `GOOGLE_API_KEY`
- [ ] The route list matches the BUILD.md table exactly — no extras

> **Spot check — data access.** Before Prompt 9:
> - [ ] Every route that reads the audit log takes its filter from a validated query
>   parameter, never from an unchecked string interpolated into a path
> - [ ] The 404-not-403 rule on `/api/confirm` is verified by request, not by reading code
> - [ ] Nothing in the app calls `/api/confirm` itself — grep the templates and Python for it;
>   only the form's submit button may reach it

---
## Prompt 9 — Templates, the disclaimer, and the confirm button

```
Server-rendered Jinja2 only. No build step, no framework, no client-side state.
The UI's job is to make the decision boundary visible from the back of the
room.

1. app/templates/base.html — one page shell. Inline CSS in a style block, no
   CDN. A readable system font stack, a max width around 900px, and enough
   contrast to survive a projector. Header links: the form and /audit.

2. app/templates/index.html — extends base.

   The intake form, six controls, all required, method post to
   /api/checklist: jurisdiction select, property_type select, year_built number
   input with min 1800 and max 2026, has_association checkbox, seller_occupancy
   select, financing select. Option values are the enum values from
   schemas.py, byte-identical — a mismatch here fails validation at the edge
   and is invisible in the markup. Preselect the md_1985_sfh values.

   The results, when present, in three labelled sections in this order:
   Required, Likely, Broker Review. Render Likely only when non-empty. Each
   item shows the rule name, the citation in a monospace span, and the reason
   sentence. Broker Review items also render review_note, visually distinct.
   A rule appearing in both Required and Broker Review renders in both — do
   not deduplicate; that duplication is the point.

   Every section renders an empty state rather than collapsing to nothing:
   "No items in this category for these facts."

   The disclaimer, rendered verbatim from the result's disclaimer field, on
   every result, above the confirm control and not behind a toggle.

   A mode line on every result, from the result's mode field. When mode is
   "offline", state plainly that no model was called and the wording is the
   rule's own summary text. Do not hide this behind a tooltip — an app whose
   pitch is honesty about what the agent did cannot be coy about not having
   run one.

   The confirm control: a text input for confirmed_by, a hidden result_id, and
   a single button reading "Confirm checklist", posting to /api/confirm. The
   button disables itself on submit and does not re-enable. After a successful
   confirmation the page shows who confirmed and when, and the button stays
   disabled.

3. app/templates/audit.html — extends base. A table of the most recent 200
   entries: timestamp, kind, result_id, and a compact payload summary.
   Confirmation rows visually distinct. Show the skipped-line count when it is
   nonzero. Empty state when the log has no entries.

4. Escape all values. Rule names, citations, and reasons come from YAML and
   from the model; render them escaped, never with a raw filter.
```

### Checkpoint 9

- [ ] The form's option values match `schemas.py` enum values exactly — diff them
- [ ] Submitting the default form returns a rendered result, not JSON
- [ ] The disclaimer text on the page is byte-identical to `DISCLAIMER`
- [ ] On the DC tenant-occupied fixture, TOPA renders in Required **and** in Broker Review
- [ ] A section with no items shows the empty-state line rather than disappearing
- [ ] Clicking Confirm disables the button and it does not re-enable
- [ ] A rule name containing `<script>` renders as text, not as markup
- [ ] With `GOOGLE_API_KEY` unset, the page states no model was called; with it set, it does not
- [ ] `/audit` shows the confirmation row after the button is pressed

---

## Prompt 10 — Demo fixtures, smoke script, and end-to-end verification

```
Prove the three demo beats work as a sequence, from a cold start, before the
deploy phase touches anything.

1. scripts/smoke.sh — takes a base URL, defaulting to http://localhost:8080.
   POSTs each of the four fixtures to /api/checklist and asserts, per fixture,
   the exact required and broker_review rule-id sets and the rules_evaluated
   count from Prompt 5's table (8, 8, 9, 8). Use a JSON parser, not grep, for
   set comparison. Print one PASS or FAIL line per fixture, each naming the
   result's mode. Exit 1 if any fixture fails; exit 2 if the server is
   unreachable, so "server down" cannot read as "tests passed". Every set
   assertion must hold identically in offline and live mode — membership does
   not depend on the model, so the script is green with no API key.

2. Extend it with the three demo assertions, each named in the output:
   Beat 1 — md_1985_sfh has no fed_lead_paint in required; the same body with
   year_built 1970 does. Both in one run.
   Beat 2 — dc_condo_tenant with seller_occupancy owner_occupied has no
   dc_topa; with tenant_occupied it appears in required and in broker_review.
   Beat 3 — after a checklist call, POST /api/confirm with the returned
   result_id and confirmed_by "Smoke Test" returns 200, and GET
   /api/audit?result_id=... contains a confirmation entry and nine
   rule_evaluated entries.

3. tests/test_routes.py — the same assertions against a FastAPI TestClient with
   the model layer stubbed, so they run in pytest with no API key. Stub the
   prose only; compose_buckets must run for real.

4. A README section "Demo run order" listing the exact clicks and the expected
   on-screen change for each beat, so the presenter is not improvising.

Run the whole thing from a cold start: fresh audit log, server started, smoke
script green, then open the browser and walk the three beats by hand once. Fix
anything the hand-run surfaces that the script missed, and add an assertion for
it.
```

### Checkpoint 10

- [ ] `scripts/smoke.sh` exits 0 against a running server and prints four PASS lines
- [ ] The same four PASS lines appear with `GOOGLE_API_KEY` unset, each labelled `offline`
- [ ] With the server stopped, the script exits 2 and says the server is unreachable
- [ ] Beat 1, 2, and 3 each print a named PASS line
- [ ] Changing an expected set in the script makes the corresponding fixture print FAIL
- [ ] `pytest -q` exits 0 with no API key set, including `test_routes.py`
- [ ] A cold-start hand-run of all three beats matches the README's stated on-screen changes
- [ ] `/api/audit` for the DC result returns 9 `rule_evaluated` entries plus a result and a confirmation

---

> **Deferred as of 2026-08-28 — localhost demo.** Do not run this prompt as
> written. Run **item 5 only** (the README, including the Limitations section) at
> the end of Prompt 10, and treat these checkpoint items as waived for now, with
> the reason recorded: every item requiring a live service URL. The two that still
> apply and must pass are the secret scan and the unmodified deploy script. If a
> GCP project appears, run the whole prompt and restore the waived items.

## Prompt 11 — Cloud Run deploy and README

```
Ship it, and write down what is true about it.

1. Reuse the shared scaffold's scripts/deploy.sh unchanged. SPEC.md requires
   asking before modifying it — if it needs a change, stop and tell me what and
   why rather than editing it.

2. If the scaffold has no container definition, add a Dockerfile: a python:3.12
   slim base, requirements installed as their own layer before the app is
   copied, a non-root user, and uvicorn bound to 0.0.0.0 on the PORT
   environment variable Cloud Run injects. Never hardcode 8080 as the listen
   port.

   Build the image with Cloud Build, via gcloud run deploy --source . — not
   with a local docker build. The dev machine is Windows on ARM64 and Cloud Run
   runs linux/amd64 only, so a locally built image is the wrong architecture
   and fails at deploy with an error that does not mention architecture. If a
   local build is ever unavoidable, it must pass --platform linux/amd64.

3. Set the service's environment variables in the deploy invocation:
   GEMINI_MODEL, APP_URL set to the deployed URL, AUDIT_LOG_PATH, and
   GOOGLE_API_KEY as a secret reference, never a literal in any committed file
   or shell history. APP_URL must equal the real service URL or Prompt 8's
   Origin check rejects every confirmation in production.

4. Deploy, then run scripts/smoke.sh against the public URL. It must exit 0.
   Time a single /api/checklist request against the live URL and record the
   number; SPEC.md's success criterion is under five seconds.

5. README.md — what it does, the decision boundary in two sentences, setup and
   run commands, the six inputs, the demo run order from Prompt 10, and a
   Limitations section stating plainly: the audit log is on an ephemeral
   filesystem and does not survive an instance restart; confirmed_by is a typed
   name and not a verified identity, because there is no authentication; and
   the seed rules are a starting point that has not been verified against
   current statute by a licensed attorney.

6. Run scripts/scan-secrets.sh one last time against the tracked tree before
   the final commit, and confirm git log has no .env, no key, and no
   service-account JSON in any commit, not only the last one.
```

### Checkpoint 11

- [ ] The public Cloud Run URL returns 200 on `/health` with the configured model id
- [ ] `scripts/smoke.sh https://<service-url>` exits 0 with four PASS lines
- [ ] A single `/api/checklist` request against the live URL completes in under 5 seconds — record it
- [ ] `POST /api/confirm` succeeds against the live URL, confirming `APP_URL` matches the service URL
- [ ] `scripts/scan-secrets.sh` exits 0 and `git log -p | grep -c "AIza"` returns 0
- [ ] The README Limitations section names all three limitations
- [ ] `scripts/deploy.sh` is unmodified from the scaffold — `git diff` against it is empty

---

## Service keys, by the prompt that first needs them

| Service | First needed | Placeholder enough? |
|---|---|---|
| Google AI / Gemini API key (`GOOGLE_API_KEY`) | **Prompt 7**, and only to demo the real agent | Unset is a supported mode, not a placeholder — the whole build runs, tests, and smokes green without it. But offline mode demos a rules engine, not an ADK agent, so get the key for the stage |
| Gemini model id (`GEMINI_MODEL`) | Prompt 2 | No — the app refuses to boot without it. Any string works until Prompt 7; use the real Flash-class id from then on |
| GCP project + Cloud Run deploy credentials | **Prompt 11** | No. Provision before the build starts; `gcloud auth login` mid-demo is how a build window disappears |
| Artifact Registry / Cloud Build | Prompt 11 | No, and it is enabled per-project — check it the day before, not on the day |

Neither is build work, and both are wall-clock blockers — but only one is a hard
one. **Cloud Run needs billing enabled on the project; sort that before the fifty
minutes start or drop Prompt 11 and demo from localhost.** The Gemini key is a
two-minute AI Studio free-tier issue with no billing, and offline mode means an
unset key degrades the demo rather than stopping the build. Check whether the
event hands out platform access before spending build time on either.

---

## Open questions carried from SPEC.md

Resolved in this plan, recorded so the reasoning is not lost:

- **The `likely` tier.** Implemented in the schema and in `compose_buckets`, populated
  by no seed rule. The section renders only when non-empty, so it is invisible in the
  demo and available the moment a rule is tagged `likely`.
- **Model choice.** Read from `GEMINI_MODEL`; the code never names a model. Pick the
  Flash-class id on the day and set the variable.
- **Statute verification.** Not resolved by this plan and not resolvable by code. The
  citations in Prompt 4 come from SPEC.md's seed list. Verify them before the demo, and
  say on stage that they are seeds — the README Limitations section commits to this.

---

## Handoff

When Checkpoint 11 passes, the build is done. Post-build hardening is the
**harden** skill's A–G cascade — run it, don't inline a summary of it here.

For this app: Phase A (payments) does not apply; Phase F (mobile store) does not
apply. B, C, D, E, and G do. Given the event timeline, the realistic order is to
demo first and run the cascade afterwards if the project continues past the
build-a-thon.

**Validate this document before using it:**

```
node ~/.claude/plugins/cache/gauntlet-skills/gauntlet/0.1.0/skills/build/gates/lint-buildplan.mjs BUILD.md
```

Structure only — a clean result means the prompts are shaped correctly, not that
they are good.
