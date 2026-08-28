"""The ADK agent, and the single entry point the HTTP layer calls.

The agent phrases; it does not decide. That is enforced structurally, not by
instruction alone: `compose_buckets` runs on every request and its output is
the authority on bucket membership. If the agent's own view differs, the
difference is written to the audit log as an error and the engine's answer is
the one that ships.

Three modes, all recorded and all displayed:
  live     the model wrote the reason sentences
  cached   identical facts were seen before; no provider call was made
  offline  GOOGLE_API_KEY is unset; reason text is each rule's own summary

Offline is a declared mode, not a stub and not a silent fallback. See standing
Rule 9.
"""

import json
import logging
import time
import uuid
from typing import Any

from app import audit, cache, limits
from app.config import get_settings
from app.engine import Buckets, compose_buckets
from app.errors import ModelOutputError, ModelUnavailable
from app.rules.loader import rules_for
from app.schemas import DISCLAIMER, ChecklistItem, ChecklistResult, Mode, TransactionFacts
from app.tools import evaluate_rule, get_rules

logger = logging.getLogger("disclosure_agent.agent")

AGENT_NAME = "disclosure_checklist_agent"

INSTRUCTION = """
You write one plain-sentence explanation per disclosure rule that applies to a
real estate transaction. You do not decide which rules apply.

Procedure, in order:
1. Call get_rules with the transaction's jurisdiction to list every rule in scope.
2. Call evaluate_rule for EVERY rule id returned. Not a subset. The audit trail
   depends on every rule being evaluated, including the ones that do not apply.
3. For each rule where evaluate_rule returned applies=true, write one sentence
   naming the specific fact that triggered it — the year built, the tenancy, the
   association, the financing type.

Never infer from your own knowledge of law whether a rule applies. evaluate_rule
is the only source of that answer. If your knowledge disagrees with the tool, the
tool is right and you are wrong.

Return ONLY a JSON object, no prose around it, no markdown fence:
{"items": [{"rule_id": "...", "reason": "..."}]}

One entry per applying rule. Each reason is one sentence, under 30 words, plain
English, no legal advice, no recommendation about what the seller should do.
""".strip()


def _build_agent(facts: TransactionFacts) -> Any:
    """Construct the ADK agent with per-request tool closures.

    The tools are bound to this request's facts so the model cannot evaluate a
    rule against facts of its own invention. Imported lazily so that importing
    this module never requires the ADK or an API key.
    """
    from google.adk.agents import Agent

    def list_rules() -> list[dict[str, str]]:
        """List every disclosure rule in scope for this transaction.

        Returns id, name, citation and tier for each. Conditions are not
        included; call evaluate_rule to find out whether a rule applies.
        """
        return get_rules(facts.jurisdiction)

    def check_rule(rule_id: str) -> dict[str, Any]:
        """Determine whether one rule applies to this transaction.

        Args:
            rule_id: A rule id from list_rules.

        Returns:
            applies (bool), tier (str), review_note (str or None).
        """
        return evaluate_rule(rule_id, facts)

    settings = get_settings()
    return Agent(
        name=AGENT_NAME,
        model=settings.GEMINI_MODEL,
        instruction=INSTRUCTION,
        tools=[list_rules, check_rule],
    )


def _facts_prompt(facts: TransactionFacts) -> str:
    return (
        "Transaction facts:\n"
        f"- jurisdiction: {facts.jurisdiction}\n"
        f"- property_type: {facts.property_type}\n"
        f"- year_built: {facts.year_built}\n"
        f"- has_association: {facts.has_association}\n"
        f"- seller_occupancy: {facts.seller_occupancy}\n"
        f"- financing: {facts.financing}\n"
    )


def _parse_items(text: str) -> dict[str, str]:
    """Pull the rule_id -> reason mapping out of the model's reply.

    Tolerates a markdown fence around the JSON, which models add despite being
    asked not to. Raises ModelOutputError on anything else — a reply we cannot
    parse is not a reply we should guess at.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        parsed = json.loads(cleaned)
        return {
            str(item["rule_id"]): str(item["reason"]).strip()
            for item in parsed["items"]
            if str(item.get("reason", "")).strip()
        }
    except Exception as exc:
        raise ModelOutputError("model reply was not the expected JSON shape") from exc


def _call_model(facts: TransactionFacts, result_id: str) -> dict[str, str]:
    """Run the agent once and return rule_id -> reason. Raises on failure."""
    try:
        from google.adk.runners import InMemoryRunner
        from google.genai import types
    except Exception as exc:
        raise ModelUnavailable("the ADK is not available in this environment") from exc

    settings = get_settings()
    started = time.monotonic()

    try:
        runner = InMemoryRunner(agent=_build_agent(facts), app_name=AGENT_NAME)
        session = runner.session_service.create_session_sync(app_name=AGENT_NAME, user_id="web")
        message = types.Content(
            role="user", parts=[types.Part.from_text(text=_facts_prompt(facts))]
        )

        reply = ""
        usage = {"input_tokens": 0, "output_tokens": 0}
        for event in runner.run(user_id="web", session_id=session.id, new_message=message):
            meta = getattr(event, "usage_metadata", None)
            if meta is not None:
                usage["input_tokens"] += getattr(meta, "prompt_token_count", 0) or 0
                usage["output_tokens"] += getattr(meta, "candidates_token_count", 0) or 0
            if event.is_final_response() and getattr(event, "content", None):
                for part in event.content.parts or []:
                    if getattr(part, "text", None):
                        reply += part.text
    except Exception as exc:
        raise ModelUnavailable(f"model {settings.GEMINI_MODEL!r} could not be reached") from exc

    limits.record_model_call()
    latency_ms = int((time.monotonic() - started) * 1000)
    audit.append(
        "model_call",
        result_id,
        {"mode": "live", "model": settings.GEMINI_MODEL, "latency_ms": latency_ms, **usage},
    )
    return _parse_items(reply)


def _offline_reasons(facts: TransactionFacts, applied: list[str]) -> dict[str, str]:
    """Reason text taken verbatim from each rule's own summary. Nothing invented."""
    catalogue = rules_for(facts.jurisdiction)
    return {rule_id: catalogue[rule_id].summary.strip() for rule_id in applied}


def _assemble(
    facts: TransactionFacts,
    buckets: Buckets,
    reasons: dict[str, str],
    result_id: str,
    mode: Mode,
) -> ChecklistResult:
    """Build the result from the engine's buckets and the model's prose.

    Membership comes from `buckets`, never from `reasons`. A rule the model
    forgot to describe still appears, with its summary as the fallback text,
    because omitting an obligation is the one failure this product cannot have.
    """
    catalogue = rules_for(facts.jurisdiction)

    def item(rule_id: str, *, as_review: bool) -> ChecklistItem:
        rule = catalogue[rule_id]
        return ChecklistItem(
            rule_id=rule_id,
            name=rule.name,
            citation=rule.citation,
            tier="review" if as_review else rule.tier,
            reason=reasons.get(rule_id) or rule.summary.strip(),
            review_note=rule.review_note if as_review else None,
        )

    return ChecklistResult(
        facts=facts,
        required=[item(r, as_review=False) for r in buckets.required],
        likely=[item(r, as_review=False) for r in buckets.likely],
        broker_review=[item(r, as_review=True) for r in buckets.broker_review],
        disclaimer=DISCLAIMER,
        rules_evaluated=buckets.rules_evaluated,
        result_id=result_id,
        mode=mode,
    )


def run_checklist(facts: TransactionFacts, caller: str = "local") -> ChecklistResult:
    """Produce a validated checklist. The only entry point the routes call."""
    settings = get_settings()
    result_id = uuid.uuid4().hex

    # The engine decides membership, always, before anything else happens.
    buckets = compose_buckets(facts)
    audit.append_rule_evaluations(result_id, facts, buckets.evaluations)
    applied = list(dict.fromkeys([*buckets.required, *buckets.likely, *buckets.broker_review]))

    facts_hash = facts.canonical_hash()
    mode: Mode
    reasons: dict[str, str]

    if not settings.GOOGLE_API_KEY:
        mode = "offline"
        reasons = _offline_reasons(facts, applied)
        audit.append(
            "model_call",
            result_id,
            {"mode": "offline", "input_tokens": 0, "output_tokens": 0, "latency_ms": 0},
        )
    elif (cached := cache.get(facts_hash)) is not None:
        mode = "cached"
        reasons = cached
        audit.append(
            "model_call",
            result_id,
            {"mode": "cached", "input_tokens": 0, "output_tokens": 0, "latency_ms": 0},
        )
    else:
        # Rate limit and ceiling are deliberate refusals, not failures. They
        # still raise, and still surface as 429.
        limits.check_rate_limit(caller, settings.RATE_LIMIT_PER_MINUTE)
        limits.check_daily_ceiling(settings.MAX_MODEL_CALLS_PER_DAY)
        try:
            reasons = _call_model(facts, result_id)
            mode = "live"
            _log_disagreement(result_id, applied, reasons)
            cache.put(facts_hash, reasons)
        except (ModelUnavailable, ModelOutputError) as exc:
            # The model writes wording, not answers. If it is unreachable the
            # checklist is still correct, so serve it with the rules' own
            # summaries rather than failing the request. Labelled `degraded`
            # and recorded — never presented as though a model had run.
            mode = "degraded"
            reasons = _offline_reasons(facts, applied)
            logger.warning("model unavailable, degrading to rule summaries: %s", exc)
            audit.append(
                "error",
                result_id,
                {
                    "stage": "model_call",
                    "resolution": "degraded_to_summaries",
                    "error": type(exc).__name__,
                },
            )
            audit.append(
                "model_call",
                result_id,
                {
                    "mode": "degraded",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "latency_ms": 0,
                },
            )

    try:
        result = _assemble(facts, buckets, reasons, result_id, mode)
    except Exception as first_failure:
        if mode != "live":
            # Offline and cached text comes from our own rule files. A failure
            # here is a rule-data bug; retrying the model would not fix it.
            raise ModelOutputError("assembled checklist failed validation") from first_failure
        logger.warning("result validation failed, retrying once: %s", first_failure)
        audit.append("error", result_id, {"stage": "assemble", "attempt": 1})
        reasons = _call_model(facts, result_id)
        try:
            result = _assemble(facts, buckets, reasons, result_id, mode)
        except Exception as second_failure:
            audit.append("error", result_id, {"stage": "assemble", "attempt": 2})
            raise ModelOutputError(
                "assembled checklist failed validation twice"
            ) from second_failure

    audit.append(
        "result",
        result_id,
        {
            "mode": mode,
            "facts_hash": facts_hash,
            "required": buckets.required,
            "likely": buckets.likely,
            "broker_review": buckets.broker_review,
            "rules_evaluated": buckets.rules_evaluated,
        },
    )
    return result


def _log_disagreement(result_id: str, applied: list[str], reasons: dict[str, str]) -> None:
    """Record where the model's view differed from the engine's. The engine wins."""
    model_set, engine_set = set(reasons), set(applied)
    if model_set == engine_set:
        return
    audit.append(
        "error",
        result_id,
        {
            "stage": "agent_disagreement",
            "engine_only": sorted(engine_set - model_set),
            "model_only": sorted(model_set - engine_set),
            "resolution": "engine",
        },
    )
    logger.warning(
        "agent/engine disagreement on %s: engine_only=%s model_only=%s",
        result_id,
        sorted(engine_set - model_set),
        sorted(model_set - engine_set),
    )
