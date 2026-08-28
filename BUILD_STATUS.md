# BUILD_STATUS

**Current phase: Prompt 10 — Demo fixtures, smoke script, end-to-end verification, README.**

Target: **localhost**. Deployment deferred 2026-08-28.
Mode: `GOOGLE_API_KEY` unset → offline mode. Nothing before Prompt 7 needs it.

| # | Prompt | Status |
|---|---|---|
| 1 | Spec validation and standing rules | ✅ done — Checkpoint 1 passed |
| 2 | Project scaffold, config, and secret hygiene | ✅ done — Checkpoint 2 passed 7/7 |
| 3 | Pydantic schemas, the shared spine | ✅ done — Checkpoint 3 passed 9/9 |
| 4 | Rule data files and loader | ✅ done — Checkpoint 4 passed 7/7 |
| 5 | Deterministic engine and the rule tests | ✅ done — Checkpoint 5 passed 7/7 |
| 6 | Append-only audit log | ✅ done — Checkpoint 6 passed 8/8 |
| 7 | ADK agent, model wiring, and cost control | ✅ done — Checkpoint 7 passed 10/10 (live provider path UNVERIFIED) |
| 8 | FastAPI routes | ✅ done — Checkpoint 8 passed 8/8 |
| 9 | Templates, the disclaimer, and the confirm button | ✅ done — Checkpoint 9 passed 9/9 |
| 10 | Demo fixtures, smoke script, and end-to-end verification | ⬜ next (+ README, folded in from P11) |
| 11 | Cloud Run deploy and README | ⏸ deferred — run **item 5 only** (README) during Prompt 10 |

## Spot checks

| After prompt | Check | Status |
|---|---|---|
| 2 | Environment and secrets, incl. scanner canary | ✅ canary-verified both directions |
| 2 | Connection pooling | ⏭ skipped — no database |
| 5 | Determinism | ✅ 3 canaries; suite proven able to fail |
| 7 | Metered API controls | ✅ 3 canaries; key-leak check clean |
| 7 | Payment integration | ⏭ skipped — no payments |
| 8 | Data access | ✅ verified by request |

## Prompt 1 record

Five consistency checks run against `SPEC.md`:

1. Routes, structure comment vs agent flow — **PASS** (agent flow is a lifecycle
   narrative, not a route inventory; no contradiction)
2. Six fields identical in input table and fixtures — **FAIL, accepted**. The
   fixtures are positional prose; values and ordering match the table exactly.
   Prompt 5 pins them as explicit JSON. Recorded in `SPEC.md` under "Known
   imprecision in the spec above, accepted rather than edited"
3. Rules in test expectations exist in seed rules — **PASS**
4. Tier values consistent — **PASS** (`review` → `broker_review` bucket by design)
5. Disclaimer appears exactly once — **PASS**, `SPEC.md:216`

Produced: `CLAUDE.md` (17 rules, disclaimer verified byte-identical to `SPEC.md`),
`SPEC.md` "Resolved during build planning" (5 decisions), this file.

## Open before demo

- Verify every citation against current statute. `dc_underground_tank` and
  `md_lead_registration` are the least certain. Not a code task.
- Get a Gemini key if the live agent is to be demoed. Offline mode covers the
  build but shows a rules engine, not an ADK agent.
- Ask whoever owns Entry 1's deploy script whether a GCP project already exists.
- README must state that the audit log is on an ephemeral filesystem and does not
  survive an instance restart. Captured in app/audit.py's docstring; goes in the
  README during the Prompt 10 session.
