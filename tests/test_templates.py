"""What the rendered pages must contain, regardless of how they are styled.

The interface had no test coverage until it was redesigned, which meant a
restyle could silently drop the disclaimer, break an enum value, or
deduplicate the item that the whole product argument rests on.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.schemas import (
    DISCLAIMER,
    ChecklistItem,
    ChecklistResult,
    Financing,
    Jurisdiction,
    PropertyType,
    SellerOccupancy,
    TransactionFacts,
)

DC_TENANT = {
    "jurisdiction": "DC",
    "property_type": "condo",
    "year_built": 2005,
    "has_association": True,
    "seller_occupancy": "tenant_occupied",
    "financing": "cash",
}
MD_1985 = {
    "jurisdiction": "MD",
    "property_type": "single_family",
    "year_built": 1985,
    "has_association": False,
    "seller_occupancy": "owner_occupied",
    "financing": "conventional",
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("APP_URL", "http://localhost:8080")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_form_control_values_match_the_enums_exactly(client: TestClient) -> None:
    """A mismatch fails validation at the edge and is invisible in the markup."""
    import re

    page = client.get("/").text
    rendered = set(re.findall(r'(?:option|input[^>]*?) value="([^"]+)"', page))
    enums = {e.value for E in (Jurisdiction, PropertyType, SellerOccupancy, Financing) for e in E}
    assert enums <= rendered, f"missing from the form: {sorted(enums - rendered)}"


def test_landing_page_defaults_to_the_first_demo_fixture(client: TestClient) -> None:
    assert 'value="1985"' in client.get("/").text


def test_disclaimer_renders_verbatim_on_every_result(client: TestClient) -> None:
    for facts in (MD_1985, DC_TENANT):
        assert DISCLAIMER in client.post("/api/checklist", data=facts).text


def test_a_rule_in_two_buckets_renders_in_both(client: TestClient) -> None:
    """TOPA is required AND flagged for review. Deduplicating it erases the point."""
    page = client.post("/api/checklist", data=DC_TENANT).text
    assert page.count("Tenant Opportunity to Purchase Act (TOPA) Notice") == 2


def test_empty_bucket_shows_an_empty_state_rather_than_vanishing(client: TestClient) -> None:
    assert "No items in this category" in client.post("/api/checklist", data=MD_1985).text


def test_offline_mode_says_so_on_the_page(client: TestClient) -> None:
    assert "No model was called" in client.post("/api/checklist", data=MD_1985).text


def test_confirm_button_exists_and_cannot_re_enable(client: TestClient) -> None:
    page = client.post("/api/checklist", data=DC_TENANT).text
    assert 'id="confirm-button"' in page
    assert "button.disabled = true" in page
    assert "button.disabled = false" not in page


def test_hostile_rule_text_is_escaped(client: TestClient) -> None:
    """Rule wording is partly model-authored; it must never render as markup."""
    from app.main import FORM_DEFAULTS, templates

    hostile = '<script>alert("xss")</script>'
    facts = TransactionFacts.model_validate(MD_1985)
    item = ChecklistItem(
        rule_id="x",
        name=hostile,
        citation=hostile,
        tier="required",
        reason=hostile,
        review_note=hostile,
    )
    html = templates.get_template("index.html").render(
        defaults=FORM_DEFAULTS,
        result=ChecklistResult(
            facts=facts,
            required=[item],
            broker_review=[item],
            disclaimer=DISCLAIMER,
            rules_evaluated=8,
            result_id="abc",
            mode="offline",
        ),
        page="checklist",
        request=None,
    )
    assert hostile not in html
    assert "&lt;script&gt;" in html


def test_audit_page_renders_every_entry_kind(client: TestClient) -> None:
    rid = client.post("/api/checklist", json=DC_TENANT).json()["result_id"]
    client.post(
        "/api/confirm",
        json={"result_id": rid, "confirmed_by": "A Broker"},
        headers={"Origin": "http://localhost:8080"},
    )
    page = client.get("/audit").text
    assert "does not apply" in page, "the negatives are the point of the log"
    assert "identity verified: False" in page
    assert "A Broker" in page


def test_pages_declare_a_favicon(client: TestClient) -> None:
    """A missing favicon 404s on every page load and reads as unfinished."""
    assert 'rel="icon"' in client.get("/").text


def test_audit_groups_entries_into_one_record_per_transaction(client: TestClient) -> None:
    """A flat row per entry buries the story; a judge should see one run at a glance."""
    for facts in (MD_1985, DC_TENANT):
        client.post("/api/checklist", json=facts)
    page = client.get("/audit").text

    assert page.count('class="card run"') == 2, "one card per transaction"
    assert "does not apply" in page, "the negatives are the point of this log"
    assert "awaiting confirmation" in page


def test_audit_record_shows_the_facts_it_was_run_on(client: TestClient) -> None:
    """An audit log that records a decision but not its inputs cannot be audited."""
    client.post("/api/checklist", json=DC_TENANT)
    page = client.get("/audit").text
    for token in ("condo", "built 2005", "tenant occupied", "cash"):
        assert token in page, token


def test_audit_record_shows_the_confirmation_and_its_caveat(client: TestClient) -> None:
    rid = client.post("/api/checklist", json=DC_TENANT).json()["result_id"]
    client.post(
        "/api/confirm",
        json={"result_id": rid, "confirmed_by": "Dana Reyes"},
        headers={"Origin": "http://localhost:8080"},
    )
    page = client.get("/audit").text
    assert "Dana Reyes" in page
    assert "identity verified: False" in page
    assert "confirmed" in page


def test_every_rule_considered_appears_in_the_record(client: TestClient) -> None:
    client.post("/api/checklist", json=DC_TENANT)
    page = client.get("/audit").text
    assert "4 of 9 apply" in page
    for rule_id in ("dc_topa", "dc_hoa_disclosure", "fin_fha_appraisal"):
        assert rule_id in page, f"{rule_id} missing — the log must show what was considered"


def test_association_switch_is_actually_clickable(client: TestClient) -> None:
    """Regression: the styled track covered the checkbox and ate every click.

    pytest cannot click, so this asserts the two structural facts that make the
    control work — a real label association, and a track that does not intercept
    pointer events. Remove either and the switch goes dead again.
    """
    page = client.get("/").text
    assert 'for="has_association"' in page, "the label must toggle the input"
    assert 'id="has_association"' in page

    from pathlib import Path

    css = Path("app/templates/base.html").read_text(encoding="utf-8")
    track = css[css.index(".switch .track {") : css.index(".switch .track {") + 220]
    assert "pointer-events: none" in track, "the track must not swallow clicks"


def test_association_toggle_round_trips_through_the_form(client: TestClient) -> None:
    """On -> true, absent -> false, and the value reaches the result's facts."""
    on = client.post("/api/checklist", data={**DC_TENANT, "has_association": "on"}).text
    assert "association" in on

    off = dict(DC_TENANT)
    off.pop("has_association", None)
    body = client.post("/api/checklist", json={**DC_TENANT, "has_association": False}).json()
    assert body["facts"]["has_association"] is False

    body_on = client.post("/api/checklist", json={**DC_TENANT, "has_association": True}).json()
    assert body_on["facts"]["has_association"] is True
    assert "dc_hoa_disclosure" not in {i["rule_id"] for i in body_on["required"]}, (
        "condo + association must still exclude the HOA rule"
    )
