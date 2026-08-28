#!/usr/bin/env bash
# End-to-end smoke test against a running server.
#
# Usage: scripts/smoke.sh [base-url]        default http://localhost:8080
#
# Exit 0 = everything passed, 1 = an assertion failed, 2 = the server is
# unreachable. Exit 2 exists so "server down" can never read as "tests passed".
#
# Every assertion holds identically in offline and live mode, because bucket
# membership does not depend on the model. The script is green with no API key.

set -uo pipefail

BASE="${1:-http://localhost:8080}"
cd "$(dirname "$0")/.." || { echo "ERROR: cannot reach project root"; exit 2; }

if ! curl -sf --max-time 10 "$BASE/health" >/dev/null 2>&1; then
  echo "ERROR: $BASE/health is unreachable. The server is not running."
  echo "Refusing to report a pass on a server that never answered."
  exit 2
fi

if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then PY="python3"
else PY="python"; fi

"$PY" - "$BASE" <<'PYCHECK'
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/")
ORIGIN = BASE
failures = 0


def post(path, body, headers=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data, method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return r.status, json.loads(r.read())


def report(label, ok, detail=""):
    global failures
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")


FIXTURES = {
    "md_1970_sfh": dict(jurisdiction="MD", property_type="single_family", year_built=1970,
                        has_association=False, seller_occupancy="owner_occupied",
                        financing="conventional"),
    "md_1985_sfh": dict(jurisdiction="MD", property_type="single_family", year_built=1985,
                        has_association=False, seller_occupancy="owner_occupied",
                        financing="conventional"),
    "dc_condo_tenant": dict(jurisdiction="DC", property_type="condo", year_built=2005,
                            has_association=True, seller_occupancy="tenant_occupied",
                            financing="cash"),
    "va_townhome_hoa": dict(jurisdiction="VA", property_type="townhome_hoa", year_built=1995,
                            has_association=True, seller_occupancy="owner_occupied",
                            financing="va"),
}

EXPECTED = {
    "md_1970_sfh": ({"fed_lead_paint", "md_residential_disclosure"}, set(), 8),
    "md_1985_sfh": ({"md_residential_disclosure"}, set(), 8),
    "dc_condo_tenant": ({"dc_sellers_disclosure", "dc_topa", "dc_condo_resale"},
                        {"dc_topa", "dc_underground_tank"}, 9),
    "va_townhome_hoa": ({"va_rpda", "va_poa_packet"},
                        {"fin_va_wdi", "va_septic_well"}, 8),
}


def ids(result, bucket):
    return {item["rule_id"] for item in result[bucket]}


print("--- fixtures ---")
results = {}
for name, facts in FIXTURES.items():
    status, body = post("/api/checklist", facts)
    if status != 200:
        report(name, False, f"HTTP {status}")
        continue
    results[name] = body
    want_req, want_rev, want_count = EXPECTED[name]
    got_req, got_rev = ids(body, "required"), ids(body, "broker_review")
    ok = got_req == want_req and got_rev == want_rev and body["rules_evaluated"] == want_count
    detail = f"[mode={body['mode']}, evaluated={body['rules_evaluated']}]"
    if not ok:
        detail += f"\n      required  want {sorted(want_req)}\n                got  {sorted(got_req)}"
        detail += f"\n      review    want {sorted(want_rev)}\n                got  {sorted(got_rev)}"
    report(name, ok, detail)

print("\n--- demo beats ---")

if "md_1985_sfh" in results and "md_1970_sfh" in results:
    report(
        "beat 1: lead paint appears only below 1978",
        "fed_lead_paint" not in ids(results["md_1985_sfh"], "required")
        and "fed_lead_paint" in ids(results["md_1970_sfh"], "required"),
    )

owner = dict(FIXTURES["dc_condo_tenant"], seller_occupancy="owner_occupied")
status, owner_body = post("/api/checklist", owner)
if status == 200 and "dc_condo_tenant" in results:
    tenant = results["dc_condo_tenant"]
    report(
        "beat 2: TOPA appears on tenancy, in both buckets",
        "dc_topa" not in ids(owner_body, "required")
        and "dc_topa" in ids(tenant, "required")
        and "dc_topa" in ids(tenant, "broker_review"),
    )

if "dc_condo_tenant" in results:
    rid = results["dc_condo_tenant"]["result_id"]
    status, _ = post("/api/confirm", {"result_id": rid, "confirmed_by": "Smoke Test"},
                     headers={"Origin": ORIGIN})
    _, log = get(f"/api/audit?result_id={rid}")
    kinds = {}
    for entry in log["entries"]:
        kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1
    report(
        "beat 3: confirmation recorded with every rule evaluated",
        status == 200 and kinds.get("confirmation", 0) >= 1 and kinds.get("rule_evaluated") == 9,
        f"[{kinds}]",
    )

print()
if failures:
    print(f"FAILED - {failures} assertion(s).")
    sys.exit(1)
print("PASSED - all fixtures and demo beats.")
PYCHECK
