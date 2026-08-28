"""Agent orchestration: modes, cost controls, and the engine's authority.

No API key and no network. Live mode is exercised with a stubbed _call_model,
which is the only honest way to test it offline — and is why the live path
against a real provider remains unverified until a key exists.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from app import agent as agent_mod
from app import audit, cache, limits
from app.config import get_settings
from app.errors import DailyCeilingExceeded, ModelOutputError, ModelUnavailable, RateLimitExceeded
from app.schemas import DISCLAIMER
from tests.test_rules import load_fixture


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh limiter, fresh cache, and an audit log inside tmp_path."""
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("APP_URL", "http://localhost:8080")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(get_settings, "__wrapped__", get_settings.__wrapped__, raising=False)
    get_settings.cache_clear()
    limits.reset_for_tests()
    cache.clear()
    yield tmp_path / "audit.jsonl"
    get_settings.cache_clear()


def stub_model(reasons: dict[str, str], counter: list[int]) -> Callable[..., dict[str, str]]:
    def _stub(facts, result_id, applied):  # noqa: ANN001, ARG001
        counter.append(1)
        audit.append(
            "model_call", result_id, {"mode": "live", "input_tokens": 10, "output_tokens": 5}
        )
        return dict(reasons)

    return _stub


# ---------------------------------------------------------------- offline mode


def test_offline_mode_uses_rule_summaries_and_calls_no_model(isolated: Path) -> None:
    facts = load_fixture("dc_condo_tenant")
    result = agent_mod.run_checklist(facts)

    assert result.mode == "offline"
    assert result.disclaimer == DISCLAIMER
    assert result.rules_evaluated == 9

    from app.rules.loader import rules_for

    catalogue = rules_for("DC")
    for item in result.required:
        assert item.reason == catalogue[item.rule_id].summary.strip()


def test_offline_mode_is_recorded_not_silent(isolated: Path) -> None:
    agent_mod.run_checklist(load_fixture("md_1970_sfh"))
    entries = audit.read_entries(path=isolated).entries
    calls = [e for e in entries if e.kind == "model_call"]
    assert len(calls) == 1
    assert calls[0].payload["mode"] == "offline"
    assert [e for e in entries if e.kind == "result"][0].payload["mode"] == "offline"


def test_offline_result_matches_the_engine_exactly(isolated: Path) -> None:
    from app.engine import compose_buckets

    facts = load_fixture("va_townhome_hoa")
    result = agent_mod.run_checklist(facts)
    buckets = compose_buckets(facts)

    assert [i.rule_id for i in result.required] == buckets.required
    assert [i.rule_id for i in result.broker_review] == buckets.broker_review


def test_audit_records_every_rule_considered(isolated: Path) -> None:
    agent_mod.run_checklist(load_fixture("dc_condo_tenant"))
    entries = audit.read_entries(path=isolated).entries
    assert len([e for e in entries if e.kind == "rule_evaluated"]) == 9


# ---------------------------------------------------------------- cache


def test_identical_facts_call_the_model_once(isolated: Path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    get_settings.cache_clear()
    calls: list[int] = []
    monkeypatch.setattr(agent_mod, "_call_model", stub_model({"va_rpda": "because VA"}, calls))

    facts = load_fixture("va_townhome_hoa")
    first = agent_mod.run_checklist(facts)
    second = agent_mod.run_checklist(facts)

    assert len(calls) == 1, "second identical request must not reach the provider"
    assert first.mode == "live"
    assert second.mode == "cached"


def test_different_facts_do_not_share_a_cache_entry(isolated: Path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    get_settings.cache_clear()
    calls: list[int] = []
    monkeypatch.setattr(agent_mod, "_call_model", stub_model({}, calls))

    agent_mod.run_checklist(load_fixture("md_1970_sfh"))
    agent_mod.run_checklist(load_fixture("md_1985_sfh"))
    assert len(calls) == 2


# ---------------------------------------------------------------- limits


def test_rate_limiter_allows_under_the_limit_and_blocks_over_it(
    isolated: Path, monkeypatch
) -> None:
    """Both directions. Testing only the block half is the common miss."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    calls: list[int] = []
    monkeypatch.setattr(agent_mod, "_call_model", stub_model({}, calls))

    agent_mod.run_checklist(load_fixture("md_1970_sfh"), caller="1.2.3.4")
    agent_mod.run_checklist(load_fixture("md_1985_sfh"), caller="1.2.3.4")
    assert len(calls) == 2, "requests under the limit must be allowed"

    with pytest.raises(RateLimitExceeded):
        agent_mod.run_checklist(load_fixture("dc_condo_tenant"), caller="1.2.3.4")
    assert len(calls) == 2, "the blocked request must not reach the provider"


def test_rate_limiter_fails_closed_when_it_malfunctions(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("clock exploded")

    monkeypatch.setattr(limits.time, "monotonic", boom)
    with pytest.raises(RateLimitExceeded):
        limits.check_rate_limit("1.2.3.4", 10)


def test_daily_ceiling_blocks_the_second_uncached_request(isolated: Path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("MAX_MODEL_CALLS_PER_DAY", "1")
    get_settings.cache_clear()
    calls: list[int] = []

    def _stub(facts, result_id, applied):  # noqa: ANN001, ARG001
        calls.append(1)
        limits.record_model_call()
        return {}

    monkeypatch.setattr(agent_mod, "_call_model", _stub)

    agent_mod.run_checklist(load_fixture("md_1970_sfh"))
    with pytest.raises(DailyCeilingExceeded):
        agent_mod.run_checklist(load_fixture("md_1985_sfh"))
    assert len(calls) == 1


def test_ceiling_check_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(limits, "_today", lambda: (_ for _ in ()).throw(RuntimeError("nope")))
    with pytest.raises(DailyCeilingExceeded):
        limits.check_daily_ceiling(100)


# ---------------------------------------------------------------- failure paths


def test_retry_once_then_raise_model_output_error(isolated: Path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    get_settings.cache_clear()
    calls: list[int] = []
    monkeypatch.setattr(agent_mod, "_call_model", stub_model({}, calls))
    monkeypatch.setattr(
        agent_mod, "_assemble", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
    )

    with pytest.raises(ModelOutputError):
        agent_mod.run_checklist(load_fixture("md_1970_sfh"))
    assert len(calls) == 2, "exactly one retry, not zero and not two"


def test_offline_mode_never_retries(isolated: Path, monkeypatch) -> None:
    """Offline text is ours. A failure there is a rule-data bug, not a model fault."""
    calls: list[int] = []
    monkeypatch.setattr(agent_mod, "_call_model", stub_model({}, calls))
    monkeypatch.setattr(
        agent_mod, "_assemble", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
    )

    with pytest.raises(ModelOutputError):
        agent_mod.run_checklist(load_fixture("md_1970_sfh"))
    assert calls == [], "offline mode must never call the model, even on failure"


def test_model_unavailable_names_the_model_id(isolated: Path, monkeypatch) -> None:
    """_call_model still raises and names the id — that is the unit-level contract.

    run_checklist now catches this and degrades (see the degraded-mode tests);
    the error type and its message are what the audit log records, so they still
    have to be right.
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "no-such-model-xyz")
    get_settings.cache_clear()

    import google.adk.runners as runners

    monkeypatch.setattr(
        runners, "InMemoryRunner", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("404"))
    )
    with pytest.raises(ModelUnavailable) as excinfo:
        agent_mod._call_model(load_fixture("md_1970_sfh"), "rid", ["fed_lead_paint"])
    assert "no-such-model-xyz" in str(excinfo.value)


def test_a_broken_model_never_surfaces_as_an_error_to_the_caller(
    isolated: Path, monkeypatch
) -> None:
    """End to end: the same failure that used to 503 now returns a checklist."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "no-such-model-xyz")
    get_settings.cache_clear()

    import google.adk.runners as runners

    monkeypatch.setattr(
        runners, "InMemoryRunner", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("404"))
    )
    result = agent_mod.run_checklist(load_fixture("md_1970_sfh"))
    assert result.mode == "degraded"
    assert {i.rule_id for i in result.required} == {
        "fed_lead_paint",
        "md_residential_disclosure",
    }


# ---------------------------------------------------------------- parsing & authority


@pytest.mark.parametrize(
    "reply",
    [
        '{"items":[{"rule_id":"r","reason":"because"}]}',
        '```json\n{"items":[{"rule_id":"r","reason":"because"}]}\n```',
        '```\n{"items":[{"rule_id":"r","reason":"because"}]}\n```',
    ],
)
def test_parse_items_tolerates_markdown_fences(reply: str) -> None:
    assert agent_mod._parse_items(reply) == {"r": "because"}


@pytest.mark.parametrize("reply", ["not json", "", '{"wrong":"shape"}', "[]"])
def test_parse_items_rejects_anything_else(reply: str) -> None:
    with pytest.raises(ModelOutputError):
        agent_mod._parse_items(reply)


def test_engine_wins_when_the_model_disagrees(isolated: Path, monkeypatch) -> None:
    """The model omitting a rule must not remove it from the checklist."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    get_settings.cache_clear()
    calls: list[int] = []
    monkeypatch.setattr(
        agent_mod, "_call_model", stub_model({"invented_rule": "not a real rule"}, calls)
    )

    result = agent_mod.run_checklist(load_fixture("md_1970_sfh"))
    ids = {i.rule_id for i in result.required}
    assert ids == {"fed_lead_paint", "md_residential_disclosure"}

    errors = [e for e in audit.read_entries(path=isolated).entries if e.kind == "error"]
    disagreements = [e for e in errors if e.payload.get("stage") == "agent_disagreement"]
    assert len(disagreements) == 1
    assert disagreements[0].payload["resolution"] == "engine"
    assert "invented_rule" in disagreements[0].payload["model_only"]


# ---------------------------------------------------------------- degraded mode


def test_model_failure_degrades_instead_of_failing_the_request(isolated: Path, monkeypatch) -> None:
    """A demo must not 503 because the provider blinked.

    The model writes wording, not answers, so an unreachable model leaves the
    checklist correct. Serve it, label it, record it.
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    get_settings.cache_clear()

    def boom(facts, result_id, applied):  # noqa: ANN001, ARG001
        raise ModelUnavailable("provider down")

    monkeypatch.setattr(agent_mod, "_call_model", boom)

    result = agent_mod.run_checklist(load_fixture("dc_condo_tenant"))

    assert result.mode == "degraded", "must be distinguishable from 'offline'"
    assert result.rules_evaluated == 9
    assert {i.rule_id for i in result.required} == {
        "dc_sellers_disclosure",
        "dc_topa",
        "dc_condo_resale",
    }

    from app.rules.loader import rules_for

    catalogue = rules_for("DC")
    for item in result.required:
        assert item.reason == catalogue[item.rule_id].summary.strip()


def test_degradation_is_recorded_not_silent(isolated: Path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        agent_mod,
        "_call_model",
        lambda f, r, a: (_ for _ in ()).throw(ModelOutputError("garbage")),
    )

    agent_mod.run_checklist(load_fixture("md_1970_sfh"))
    entries = audit.read_entries(path=isolated).entries

    errors = [e for e in entries if e.payload.get("resolution") == "degraded_to_summaries"]
    assert len(errors) == 1
    assert errors[0].payload["error"] == "ModelOutputError"
    assert [e for e in entries if e.kind == "result"][0].payload["mode"] == "degraded"


def test_rate_limit_still_refuses_and_does_not_degrade(isolated: Path, monkeypatch) -> None:
    """Deliberate refusals must stay refusals. Only failures degrade."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    get_settings.cache_clear()
    monkeypatch.setattr(agent_mod, "_call_model", lambda f, r, a: {})

    agent_mod.run_checklist(load_fixture("md_1970_sfh"), caller="9.9.9.9")
    with pytest.raises(RateLimitExceeded):
        agent_mod.run_checklist(load_fixture("md_1985_sfh"), caller="9.9.9.9")
