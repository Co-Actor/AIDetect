from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from aidetect.config import Settings
from aidetect.services.signals import llm_judge as llm_judge_module
from aidetect.services.signals.llm_judge import compute_llm_judge


def _settings(**overrides: Any) -> Settings:
    base = dict(
        environment="development",
        api_host="0.0.0.0",
        api_port=8010,
        api_cors_origins="http://localhost:9000",
        aidetect_internal_token="test-token-12345",
        coactor_database_url=None,
        redis_url=None,
        openrouter_api_key=None,
        openrouter_base_url="https://openrouter.ai/api/v1",
        llm_judge_model_fast="anthropic/claude-haiku-4-5",
        llm_judge_model_balanced="anthropic/claude-haiku-4-5",
        llm_judge_model_thorough="anthropic/claude-sonnet-4-6",
        llm_judge_timeout_sec=20.0,
        max_text_length=100_000,
        default_mode="balanced",
        agg_weight_statistical=0.25,
        agg_weight_patterns=0.35,
        agg_weight_llm_judge=0.40,
        rubric_version="v1",
        model_version="aidetect-0.1.0",
        cache_ttl_result=604800,
        cache_ttl_idempotency=86400,
        data_dir="data",
        feedback_log_path="data/feedback.jsonl",
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_disabled_when_no_key() -> None:
    sig = await compute_llm_judge("Some text.", mode="balanced", settings=_settings())
    assert sig.score == 0.5
    assert sig.error and "OPENROUTER_API_KEY" in sig.error
    assert sig.rubric_scores is None


@pytest.mark.asyncio
async def test_calls_openrouter_and_aggregates(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_call(settings, model, system_prompt, user_prompt, schema):
        captured["model"] = model
        captured["schema_keys"] = list(schema["schema"]["properties"]["scores"]["properties"])
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "scores": {
                                    "opening": {"score": 0.1, "evidence": "Mirror opener."},
                                    "closing": {"score": 0.2, "evidence": "Bookend summary."},
                                    "phrases": {"score": 0.0, "evidence": "Banned cliches."},
                                    "structures": {"score": 0.3, "evidence": "Three-point sermon."},
                                    "specificity": {"score": 0.2, "evidence": "Vague."},
                                    "voice": {"score": 0.4, "evidence": "Robotic."},
                                    "formatting": {"score": 0.5, "evidence": "Mixed."},
                                    "tone": {"score": 0.4, "evidence": "Inspirational close."},
                                },
                                "summary": "Strong AI tells on opener and phrases.",
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(llm_judge_module, "_call_openrouter", fake_call)

    settings = _settings(openrouter_api_key="test-key")
    sig = await compute_llm_judge("Some test text", mode="fast", settings=settings)

    assert captured["model"] == settings.llm_judge_model_fast
    assert "opening" in captured["schema_keys"]
    assert sig.error is None
    assert sig.score > 0.6  # human_score < 0.4 → ai_score > 0.6
    assert sig.summary == "Strong AI tells on opener and phrases."
    assert sig.rubric_scores is not None
    assert "opening" in sig.rubric_scores
    assert sig.rubric_scores["opening"].score == 0.1


@pytest.mark.asyncio
async def test_handles_http_error(monkeypatch) -> None:
    async def fake_call(*_args, **_kwargs):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(429, request=request, text="rate limit")
        raise httpx.HTTPStatusError("rate limit", request=request, response=response)

    monkeypatch.setattr(llm_judge_module, "_call_openrouter", fake_call)
    sig = await compute_llm_judge(
        "Some test text", mode="balanced", settings=_settings(openrouter_api_key="test-key")
    )
    assert sig.score == 0.5
    assert sig.error and "429" in sig.error


@pytest.mark.asyncio
async def test_sentence_level_blends_with_holistic(monkeypatch) -> None:
    holistic_payload = {
        "scores": {
            "opening": {"score": 0.9, "evidence": "Specific scene."},
            "closing": {"score": 0.9, "evidence": "Forward."},
            "phrases": {"score": 0.95, "evidence": "No cliches."},
            "structures": {"score": 0.85, "evidence": "Varied."},
            "specificity": {"score": 0.9, "evidence": "Concrete."},
            "voice": {"score": 0.85, "evidence": "Conversational."},
            "formatting": {"score": 0.95, "evidence": "Clean."},
            "tone": {"score": 0.9, "evidence": "Direct."},
        },
        "summary": "Reads human.",
    }
    sentence_payload = {
        "sentences": [
            {"i": 1, "score": 0.1, "reason": "AI cliche"},
            {"i": 2, "score": 0.1, "reason": "AI signposting"},
            {"i": 3, "score": 0.2, "reason": "AI list pattern"},
            {"i": 4, "score": 0.1, "reason": "Bookend close"},
        ],
    }
    call_count = {"n": 0}

    async def fake_call(settings, model, system_prompt, user_prompt, schema):
        call_count["n"] += 1
        # First call is holistic, second is sentence-level (per orchestrator order).
        payload = holistic_payload if call_count["n"] == 1 else sentence_payload
        return {
            "choices": [{"message": {"content": json.dumps(payload)}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
        }

    monkeypatch.setattr(llm_judge_module, "_call_openrouter", fake_call)

    text = (
        "Wrap it in @media (prefers-color-scheme: dark) and the browser handles the rest. "
        "Here's how it works: a single CSS line, applied uniformly. "
        "The result is fewer assets, faster pages, and zero designer churn. "
        "Do you reach for CSS filters for practical stuff like this?"
    )
    sig = await compute_llm_judge(text, mode="balanced", settings=_settings(openrouter_api_key="k"))

    assert sig.error is None
    assert sig.sentence_scores is not None and len(sig.sentence_scores) == 4
    assert sig.sentence_aggregate is not None
    assert sig.sentence_aggregate["mean"] > 0.7  # 1 - mean(human_scores)
    # Holistic AI 0.10, sentence mean ≈ 0.875, blend ≈ 0.49
    assert 0.4 < sig.score < 0.6
    assert sig.usage and sig.usage["total_tokens"] == 1400  # 700 × 2 calls


@pytest.mark.asyncio
async def test_handles_unparseable_response(monkeypatch) -> None:
    async def fake_call(*_args, **_kwargs):
        return {"choices": [{"message": {"content": "not json at all"}}]}

    monkeypatch.setattr(llm_judge_module, "_call_openrouter", fake_call)
    sig = await compute_llm_judge(
        "Some text.", mode="balanced", settings=_settings(openrouter_api_key="test-key")
    )
    assert sig.score == 0.5
    assert sig.error and "unparsable" in sig.error
