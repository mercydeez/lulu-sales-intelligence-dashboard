"""Atelier Advisor (Platform Console B3) — honesty-pinning tests.

The advisor maps a plain-language client need onto the customization catalog.
These tests pin the brand rules: the engine label is honest ("rules" whenever no
LLM produced the JSON), suggestions may only reference real FLAG_CATALOG keys,
invalid values are replaced by catalog defaults (and say so), and every gap
carries a ready-to-file bespoke draft. No live LLM/DB required.
"""
import ast
import inspect
import textwrap
from types import SimpleNamespace

from app.services import atelier_advisor as adv
from app.services.customization import FLAG_CATALOG


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# Deterministic fallback: no providers => engine is honestly "rules".
# --------------------------------------------------------------------------

async def test_no_llm_means_rules_engine_and_pos_keywords_map_to_the_pos_flag(monkeypatch):
    monkeypatch.setattr(adv, "get_provider_chain", lambda: [])
    result = await adv.suggest("The client runs tills and wants POS receipts synced nightly")
    assert result["engine"] == "rules"
    assert result["model"] is None
    keys = [s["key"] for s in result["suggestions"]]
    assert "integrations.pos" in keys
    for s in result["suggestions"]:
        assert s["key"] in FLAG_CATALOG      # only real catalog keys, ever
        assert s["available"] is True


async def test_a_provider_error_also_falls_back_to_rules(monkeypatch):
    def _boom():
        raise RuntimeError("provider discovery exploded")
    monkeypatch.setattr(adv, "get_provider_chain", _boom)
    result = await adv.suggest("stock levels and reorder points for every store")
    assert result["engine"] == "rules"
    assert "modules.inventory" in [s["key"] for s in result["suggestions"]]


# --------------------------------------------------------------------------
# LLM path: unknown keys dropped, invalid values replaced by catalog defaults.
# --------------------------------------------------------------------------

async def test_llm_output_is_post_validated_not_trusted(monkeypatch):
    canned = {
        "summary": "Enable forecasting and tune the assistant.",
        "suggestions": [
            {"key": "modules.forecasting", "value": True, "reason": "they asked for demand forecasts"},
            {"key": "modules.unicorn", "value": True, "reason": "fabricated capability"},
            {"key": "assistant.mode", "value": "spaceship", "reason": "surface preference"},
        ],
        "gaps": [],
    }

    async def fake_complete_json(providers, system, user):
        return canned

    monkeypatch.setattr(adv, "get_provider_chain",
                        lambda: [SimpleNamespace(model="fake-llm-1", name="fake")])
    monkeypatch.setattr(adv, "complete_json", fake_complete_json)

    result = await adv.suggest("demand forecasts please")
    assert result["engine"] == "llm"
    assert result["model"] == "fake-llm-1"

    by_key = {s["key"]: s for s in result["suggestions"]}
    assert "modules.unicorn" not in by_key            # unknown key DROPPED
    assert by_key["modules.forecasting"]["value"] is True
    # Invalid enum value replaced by the catalog default, honestly noted.
    mode = by_key["assistant.mode"]
    assert mode["value"] == FLAG_CATALOG["assistant.mode"]["default"]
    assert "invalid" in mode["reason"].lower()
    assert all(s["available"] is True for s in result["suggestions"])


async def test_plan_gating_is_annotated_not_hidden(monkeypatch):
    canned = {
        "summary": "POS sync.",
        "suggestions": [{"key": "integrations.pos", "value": True, "reason": "till sync"}],
        "gaps": [],
    }

    async def fake_complete_json(providers, system, user):
        return canned

    monkeypatch.setattr(adv, "get_provider_chain",
                        lambda: [SimpleNamespace(model="fake-llm-1", name="fake")])
    monkeypatch.setattr(adv, "complete_json", fake_complete_json)

    result = await adv.suggest("pos sync", tenant_context={"plan": "free", "effective": {}})
    (s,) = result["suggestions"]
    assert s["available"] is True                     # available, but…
    assert "requires plan upgrade to growth" in s["reason"]


# --------------------------------------------------------------------------
# Gaps: every one carries a ready-to-file bespoke draft.
# --------------------------------------------------------------------------

async def test_every_gap_carries_a_draft_request_with_the_original_description(monkeypatch):
    monkeypatch.setattr(adv, "get_provider_chain", lambda: [])
    description = "They want a drone fleet dispatch console. Also stock reorder alerts."
    result = await adv.suggest(description)
    assert result["gaps"], "the unmatched clause must surface as an honest gap"
    for gap in result["gaps"]:
        draft = gap["draft_request"]
        assert draft["title"] == gap["title"]
        assert draft["client_description"] == description
        assert draft["priority"] == "medium"


# --------------------------------------------------------------------------
# Route structure: platform-developer gate + input screen BEFORE any engine.
# --------------------------------------------------------------------------

def test_route_is_gated_and_screens_input_before_the_engine_runs():
    from app.routes import atelier_ai

    module_src = inspect.getsource(atelier_ai)
    assert "require_platform_developer" in module_src

    body = _code(atelier_ai.suggest_configuration)
    assert "screen_input" in body
    assert "await suggest" in body
    # The prompt-injection screen must run BEFORE the advisor (and thus before
    # any LLM call) in the route body.
    assert body.index("screen_input") < body.index("await suggest")


# --------------------------------------------------------------------------
# Prompt honesty: the LLM can only pick from the real catalog.
# --------------------------------------------------------------------------

def test_catalog_prompt_block_contains_every_catalog_key():
    block = adv._catalog_prompt_block()
    for key in FLAG_CATALOG:
        assert key in block
    assert len(block.splitlines()) == len(FLAG_CATALOG)
