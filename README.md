# Disclosure Checklist Agent

DevFest DC 2026 Build-a-thon — Entry 3.

**Live:** <https://disclosure-checklist-agent.vercel.app>
**Source:** <https://github.com/user2922/disclosure-checklist-agent>

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
Test:   pytest -q                     86 tests, no API key needed
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

## Deployment

Vercel, as a Python serverless function (`api/index.py` re-exports the same ASGI
app; `vercel.json` rewrites every path to it).

**The audit log does not use the local file backend in production, and it must
not.** Vercel's filesystem is read-only except `/tmp`, and `/tmp` is per-instance
and ephemeral — a checklist generated on one instance and confirmed on another
would 404, and `/audit` would show nothing. Since the audit log is the entire
claim of this product, that is a correctness failure, not a cosmetic one.

Setting `BLOB_READ_WRITE_TOKEN` switches `app/audit.py` to a Vercel Blob backend
(`app/blobstore.py`). The design keeps the guarantees the file backend had:

- One blob per request, written once under a key no other write will choose.
  No read-modify-write anywhere, so concurrent requests cannot lose each other's
  entries — which a single growing object would.
- The result id is in the pathname, so `result_exists()` and per-result filtering
  are one list call with no content fetch.
- Entries are buffered for the life of a request and flushed in a `finally`, so a
  request that fails still records what it did before failing.

Deploy: `vercel deploy --prod`. Environment variables are set on the project;
`BLOB_READ_WRITE_TOKEN` is injected automatically by the linked store.

### Running the live agent instead of offline mode

The deployment has no `GOOGLE_API_KEY`, so it runs in offline mode and says so on
every result. To switch it on:

```
vercel env add GOOGLE_API_KEY production     # paste the key when prompted
vercel deploy --prod
```

## Limitations

Say these out loud rather than letting someone infer otherwise.

- **Audit durability depends on the backend.** In production the log is in
  Vercel Blob and is shared across instances and durable. Run locally with no
  `BLOB_READ_WRITE_TOKEN` and it is a local file that does not survive deleting
  it — which the demo run order does deliberately, to start clean.
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
  wrong for a multi-instance deployment, which would need shared state. On
  Vercel each lambda therefore enforces its own limit and keeps its own cache,
  so the effective ceilings are per-instance rather than global. The audit log
  is shared; these are not.
- **The deployed instance runs in offline mode** unless a `GOOGLE_API_KEY` is
  added, so what it demonstrates is the deterministic rules engine and the audit
  trail, not the ADK agent writing prose.

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
tests/         86 tests, offline
scripts/       smoke.sh, scan-secrets.sh
```

Build documents: `SPEC.md` (the authority), `BUILD.md` (the eleven prompts),
`CLAUDE.md` (standing rules), `BUILD_STATUS.md` (progress).
