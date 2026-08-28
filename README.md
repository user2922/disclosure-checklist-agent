# Disclosure Checklist Agent

DevFest DC 2026 Build-a-thon — Entry 3.

A DMV real estate agent enters six transaction facts. The app returns the seller
disclosure obligations for that transaction, each citing its governing rule, plus
a separate list of items flagged for licensed-broker review. Every rule the agent
evaluated — whether or not it applied — is written to an append-only audit log,
along with the human confirmation.

**The decision boundary.** The agent never determines compliance: which rules
apply is computed in pure Python by `compose_buckets`, and the model only writes
the one-sentence explanation attached to each item. A single "Confirm checklist"
button, which only a person can press, records the human decision in the audit
log — and records it as a typed name, not a verified identity, because this build
has no authentication.

## Run it

Windows (this machine is ARM64; Python 3.12.10 via `py -3.12`):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8080
```

Then open <http://localhost:8080>.

```
Test:   pytest -q                     82 tests, no API key needed
Lint:   ruff check . ; ruff format .
Smoke:  bash scripts/smoke.sh         needs a running server; 0 pass, 1 fail, 2 unreachable
Secrets: bash scripts/scan-secrets.sh
```

`scripts/*.sh` are bash — run them from Git Bash, not PowerShell.

**Do not use `uvicorn[standard]`** on this machine: it pulls `httptools`, which
has no `win_arm64` wheel and fails to compile. `requirements.txt` pins plain
`uvicorn` and pins `cryptography` at 46.0.3 for the same reason.

## Configuration

| Bucket | Variable | Notes |
|---|---|---|
| REQUIRED | `GEMINI_MODEL` | Model id. Never hardcoded anywhere |
| REQUIRED | `APP_URL` | Origin allowed to POST `/api/confirm`. Must match the URL you browse to |
| REQUIRED | `AUDIT_LOG_PATH` | Default `./audit.jsonl` |
| FEATURE | `GOOGLE_API_KEY` | **Unset is a supported mode**, see below |
| OPTIONAL | `RATE_LIMIT_PER_MINUTE` | Default 10 |
| OPTIONAL | `MAX_MODEL_CALLS_PER_DAY` | Default 200 |

### Offline mode

With `GOOGLE_API_KEY` unset the app runs in **offline mode**: no model is called,
and each item's explanation is that rule's own `summary` text from the YAML. The
result carries `mode: "offline"`, the page says *"No model was called"*, and the
audit log records it. Everything else — which rules apply, the citations, the
tiers, the audit trail, the confirm flow — is identical, because none of it ever
depended on the model.

That makes the whole build runnable and testable with no credentials. It also
means an offline demo shows a deterministic rules engine, not an ADK agent. It is
a safety net, not the plan.

## The six inputs

| Field | Values |
|---|---|
| `jurisdiction` | `DC` · `MD` · `VA` |
| `property_type` | `single_family` · `condo` · `townhome_hoa` · `multi_family` |
| `year_built` | 1800–2026 |
| `has_association` | true / false |
| `seller_occupancy` | `owner_occupied` · `tenant_occupied` · `vacant` |
| `financing` | `conventional` · `fha` · `va` · `cash` |

Rules evaluated per request: **MD 8 · DC 9 · VA 8** (federal rules always count).

## Demo run order

Start the server, delete `audit.jsonl` first so the log tells a clean story.

1. **Open `/`.** The form is pre-filled with a Maryland 1985 single-family home.
   Press **Generate checklist**. Required shows the MD Residential Property
   Disclosure only.
2. **Change Year built to 1970**, submit again. **Lead-Based Paint Disclosure
   appears in Required**, citing 42 U.S.C. § 4852d. One fact, one obligation.
3. **Switch to DC, Condominium, 2005, association on, Seller occupancy →
   Tenant occupied**, submit. **TOPA appears twice**: in Required, and again in
   Broker Review carrying the note that single-family exemptions and
   elderly/disabled carve-outs depend on facts this intake does not capture.
   *This is where the agent stops.*
4. **Type a name and press Confirm checklist.** The button disables and the
   banner records who confirmed and when — explicitly as a typed name, not a
   verified identity.
5. **Open `/audit`.** Nine `rule_evaluated` rows for DC, including the five rules
   that did **not** apply, then the model call, the result, and the confirmation.

## Limitations

Say these out loud rather than letting someone infer otherwise.

- **The audit log is on an ephemeral local filesystem.** It does not survive a
  process restart, and on Cloud Run it does not survive an instance restart. A
  real deployment writes to Firestore or a GCS object.
- **`confirmed_by` is a typed name, not a verified identity.** There is no
  authentication in this build. The audit entry records
  `identity_verified: false` for exactly this reason. The log proves *that*
  someone confirmed and *when*; it does not prove *who*.
- **The seed rules have not been verified against current statute by a licensed
  attorney.** They are starting points. `dc_underground_tank` and
  `md_lead_registration` are the least certain, and `dc_hoa_disclosure` carries
  no statutory citation because none equivalent to the condominium provisions
  was identified. Every rule file says so in its header.
- **Not legal advice.** The fixed disclaimer renders on every result and the
  schema rejects any result whose disclaimer is not byte-identical to it.
- **In-process rate limiting and caching.** Correct for a single instance,
  wrong for a multi-instance deployment, which would need shared state.

## Layout

```
app/
  main.py      routes only; no business logic
  agent.py     ADK agent + run_checklist, the single entry point
  engine.py    compose_buckets — the authority on which rules apply
  tools.py     get_rules, evaluate_rule — pure, model-free
  rules/       the disclosure rules, as YAML data, plus the loader
  audit.py     append-only JSONL log
  schemas.py   every shape used by more than one module
  limits.py    fail-closed rate limit and daily ceiling
  cache.py     bounded response cache keyed on the facts hash
tests/         82 tests, offline
scripts/       smoke.sh, scan-secrets.sh
```

Build documents: `SPEC.md` (the authority), `BUILD.md` (the eleven prompts),
`CLAUDE.md` (standing rules), `BUILD_STATUS.md` (progress).
