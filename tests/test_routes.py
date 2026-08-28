"""The smoke script's assertions, as pytest, with no server and no API key.

The prose layer is stubbed; compose_buckets runs for real. Bucket membership is
never stubbed — that is the thing under test.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import agent as agent_mod
from app import cache, limits
from app.config import get_settings
from app.schemas import DISCLAIMER

ORIGIN = {"Origin": "http://localhost:8080"}

FIXTURES = {
    "md_1970_sfh": {
        "jurisdiction": "MD",
        "property_type": "single_family",
        "year_built": 1970,
        "has_association": False,
        "seller_occupancy": "owner_occupied",
        "financing": "conventional",
    },
    "md_1985_sfh": {
        "jurisdiction": "MD",
        "property_type": "single_family",
        "year_built": 1985,
        "has_association": False,
        "seller_occupancy": "owner_occupied",
        "financing": "conventional",
    },
    "dc_condo_tenant": {
        "jurisdiction": "DC",
        "property_type": "condo",
        "year_built": 2005,
        "has_association": True,
        "seller_occupancy": "tenant_occupied",
        "financing": "cash",
    },
    "va_townhome_hoa": {
        "jurisdiction": "VA",
        "property_type": "townhome_hoa",
        "year_built": 1995,
        "has_association": True,
        "seller_occupancy": "owner_occupied",
        "financing": "va",
    },
}

EXPECTED = [
    ("md_1970_sfh", {"fed_lead_paint", "md_residential_disclosure"}, set(), 8),
    ("md_1985_sfh", {"md_residential_disclosure"}, set(), 8),
    (
        "dc_condo_tenant",
        {"dc_sellers_disclosure", "dc_topa", "dc_condo_resale"},
        {"dc_topa", "dc_underground_tank"},
        9,
    ),
    ("va_townhome_hoa", {"va_rpda", "va_poa_packet"}, {"fin_va_wdi", "va_septic_well"}, 8),
]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("APP_URL", "http://localhost:8080")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    get_settings.cache_clear()
    limits.reset_for_tests()
    cache.clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def ids(body: dict, bucket: str) -> set[str]:
    return {item["rule_id"] for item in body[bucket]}


@pytest.mark.parametrize(("name", "required", "review", "evaluated"), EXPECTED)
def test_route_returns_exact_rule_sets(
    client: TestClient, name: str, required: set[str], review: set[str], evaluated: int
) -> None:
    body = client.post("/api/checklist", json=FIXTURES[name]).json()
    assert ids(body, "required") == required
    assert ids(body, "broker_review") == review
    assert body["rules_evaluated"] == evaluated
    assert body["disclaimer"] == DISCLAIMER


def test_beat_one_lead_paint_threshold(client: TestClient) -> None:
    old = client.post("/api/checklist", json=FIXTURES["md_1970_sfh"]).json()
    new = client.post("/api/checklist", json=FIXTURES["md_1985_sfh"]).json()
    assert "fed_lead_paint" in ids(old, "required")
    assert "fed_lead_paint" not in ids(new, "required")


def test_beat_two_topa_on_tenancy_in_both_buckets(client: TestClient) -> None:
    owner = client.post(
        "/api/checklist", json={**FIXTURES["dc_condo_tenant"], "seller_occupancy": "owner_occupied"}
    ).json()
    tenant = client.post("/api/checklist", json=FIXTURES["dc_condo_tenant"]).json()
    assert "dc_topa" not in ids(owner, "required")
    assert "dc_topa" in ids(tenant, "required")
    assert "dc_topa" in ids(tenant, "broker_review")


def test_beat_three_confirmation_is_recorded_with_every_rule(client: TestClient) -> None:
    rid = client.post("/api/checklist", json=FIXTURES["dc_condo_tenant"]).json()["result_id"]
    confirmed = client.post(
        "/api/confirm", json={"result_id": rid, "confirmed_by": "Smoke Test"}, headers=ORIGIN
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["identity_verified"] is False

    entries = client.get(f"/api/audit?result_id={rid}").json()["entries"]
    kinds = [e["kind"] for e in entries]
    assert kinds.count("rule_evaluated") == 9
    assert kinds.count("confirmation") == 1
    assert kinds.count("result") == 1


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({**FIXTURES["md_1970_sfh"], "year_built": 1799}, 422),
        ({**FIXTURES["md_1970_sfh"], "year_built": 2027}, 422),
        ({**FIXTURES["md_1970_sfh"], "jurisdiction": "PA"}, 422),
        ({"jurisdiction": "MD"}, 422),
    ],
)
def test_invalid_facts_are_rejected(client: TestClient, payload: dict, status: int) -> None:
    response = client.post("/api/checklist", json=payload)
    assert response.status_code == status
    assert "Traceback" not in response.text


def test_confirm_requires_matching_origin(client: TestClient) -> None:
    rid = client.post("/api/checklist", json=FIXTURES["md_1970_sfh"]).json()["result_id"]
    body = {"result_id": rid, "confirmed_by": "X"}
    assert client.post("/api/confirm", json=body).status_code == 403
    assert (
        client.post("/api/confirm", json=body, headers={"Origin": "https://evil.example"})
    ).status_code == 403
    assert client.post("/api/confirm", json=body, headers=ORIGIN).status_code == 200


def test_unknown_result_id_is_404_not_403(client: TestClient) -> None:
    """A 403 would confirm the id exists, which is itself a disclosure."""
    response = client.post(
        "/api/confirm", json={"result_id": "deadbeef", "confirmed_by": "X"}, headers=ORIGIN
    )
    assert response.status_code == 404


def test_stubbed_live_mode_matches_offline_membership(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the prose changes between modes. Membership must not."""
    offline = client.post("/api/checklist", json=FIXTURES["dc_condo_tenant"]).json()

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        agent_mod, "_call_model", lambda facts, result_id: {"dc_topa": "stubbed prose"}
    )
    live = client.post("/api/checklist", json=FIXTURES["dc_condo_tenant"]).json()

    assert live["mode"] == "live"
    assert ids(live, "required") == ids(offline, "required")
    assert ids(live, "broker_review") == ids(offline, "broker_review")
    assert live["rules_evaluated"] == offline["rules_evaluated"]


def test_health_reports_mode_and_never_the_key(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["mode"] == "offline"
    assert "GOOGLE_API_KEY" not in client.get("/health").text
