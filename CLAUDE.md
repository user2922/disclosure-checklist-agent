# CLAUDE.md — Disclosure Checklist Agent

Re-read this file at the start of every session. It is the only thing that
survives a context reset.

DevFest DC 2026 Build-a-thon, Entry 3. Python 3.12, Google ADK, FastAPI, Jinja2.
The agent recommends; a human confirms.

## Standing rules

Non-negotiable, every file, every session. These are the Gauntlet Phase-Zero rules
adapted to this stack. Rules that do not apply are listed as not applying, so
nobody re-adds the scaffolding they imply — copied verbatim from `BUILD.md`, which
remains the source if the two ever disagree.

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

## The disclaimer — byte-identical, every result, no exceptions

```
This checklist is a starting point generated from seed rules. It is not legal advice. A licensed broker must confirm requirements before use.
```

Held as the `DISCLAIMER` constant in `app/schemas.py`. `ChecklistResult` rejects
any disclaimer that is not exactly this string. Never paraphrase it, never
truncate it for layout, never put it behind a toggle.

---

## The six fields — one spelling each, everywhere

These strings appear in `app/schemas.py`, the YAML rule files, the JSON fixtures,
and the HTML form's option values. A mismatch in any one of those places fails
validation at the edge and is invisible in the markup.

| Field | Type | Exact values |
|---|---|---|
| `jurisdiction` | enum | `DC` · `MD` · `VA` (uppercase) |
| `property_type` | enum | `single_family` · `condo` · `townhome_hoa` · `multi_family` |
| `year_built` | int | 1800–2026 inclusive |
| `has_association` | bool | `true` · `false` |
| `seller_occupancy` | enum | `owner_occupied` · `tenant_occupied` · `vacant` |
| `financing` | enum | `conventional` · `fha` · `va` · `cash` |

`ChecklistResult.mode` is a fourth enum: `live` · `cached` · `offline`.

---

## Routes — exactly these, no others

| Method | Route | Returns |
|---|---|---|
| GET | `/` | Intake form, and results after a submit |
| POST | `/api/checklist` | `ChecklistResult` — 422 bad facts, 429 rate limited, 503 model unavailable |
| POST | `/api/confirm` | Confirmation entry — 403 bad Origin, 404 unknown `result_id` |
| GET | `/audit` | Audit log viewer, HTML |
| GET | `/api/audit` | Audit entries as JSON, optional `result_id` filter |
| GET | `/health` | `{"status":"ok","model":"<GEMINI_MODEL>"}` |

---

## Rule ids — fixed at Prompt 4, referenced by the tests

Expected `rules_evaluated`: **MD 8 · DC 9 · VA 8** (federal always counts).

**federal.yaml** (all jurisdictions) — `fed_lead_paint` · `fin_fha_appraisal` ·
`fin_va_wdi` · `prop_multi_family_review`

**dc.yaml** — `dc_sellers_disclosure` · `dc_topa` · `dc_condo_resale` ·
`dc_hoa_disclosure` · `dc_underground_tank`

**md.yaml** — `md_residential_disclosure` · `md_condo_resale` ·
`md_hoa_disclosure` · `md_lead_registration`

**va.yaml** — `va_rpda` · `va_condo_resale` · `va_poa_packet` · `va_septic_well`

Tier `review` maps to the `broker_review` bucket. A `required`-tier rule that
carries a `review_note` appears in **both** `required` and `broker_review` — that
duplication is the product, not a bug. Do not deduplicate it.

---

## Environment

| Bucket | Var | Note |
|---|---|---|
| REQUIRED | `GEMINI_MODEL` | Never a hardcoded model id |
| REQUIRED | `APP_URL` | Origin allowed to POST `/api/confirm` |
| REQUIRED | `AUDIT_LOG_PATH` | Default `./audit.jsonl` |
| FEATURE | `GOOGLE_API_KEY` | Unset = offline mode. Not an error, not a stub |
| OPTIONAL | `RATE_LIMIT_PER_MINUTE` | Default 10 |
| OPTIONAL | `MAX_MODEL_CALLS_PER_DAY` | Default 200 |

---

## This machine

Windows 11 on **ARM64**. Python 3.12.10 via `py -3.12`.

```
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

`scripts/*.sh` are bash — run them from Git Bash. Deployment is **deferred**;
this build targets localhost. Never build a container image locally for Cloud
Run from this machine: it would be arm64, and Cloud Run runs linux/amd64 only.

---

## Where things stand

Build plan: `BUILD.md`, eleven prompts. Progress: `BUILD_STATUS.md`.
Spec: `SPEC.md` — the authority, including its "Resolved during build planning"
section.
