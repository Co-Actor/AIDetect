from __future__ import annotations

import json

import httpx
import pytest

from aidetect.services import rewriter as rewriter_module
from aidetect.services.signals import llm_judge as llm_judge_module


_AI_TEXT = (
    "The reality is that React is highly efficient. What I want to say is that "
    "common bottlenecks fall into three categories. Are we blaming the framework?"
)
_HUMAN_REWRITE = (
    "React is fast. Most slowness comes from how the team wires it: unstable "
    "props, too-global state, no memoisation on big lists. Same framework, "
    "different result."
)


def _holistic_payload(ai_score: float) -> dict:
    """Build a fake holistic-judge response. ai_score=1.0 ⇒ AI, 0.0 ⇒ human."""
    human = 1.0 - ai_score
    return {
        "scores": {
            "opening": {"score": human, "evidence": ""},
            "closing": {"score": human, "evidence": ""},
            "phrases": {"score": human, "evidence": ""},
            "structures": {"score": human, "evidence": ""},
            "specificity": {"score": human, "evidence": ""},
            "voice": {"score": human, "evidence": ""},
            "formatting": {"score": human, "evidence": ""},
            "tone": {"score": human, "evidence": ""},
        },
        "summary": f"holistic summary (ai_score={ai_score})",
    }


def _sentence_payload(ai_scores: list[float]) -> dict:
    """Each value is AI-likeness of a sentence (0 human, 1 AI)."""
    return {
        "sentences": [
            {"i": i + 1, "score": 1.0 - s, "reason": f"sent {i+1}"}
            for i, s in enumerate(ai_scores)
        ]
    }


@pytest.mark.asyncio
async def test_rewrite_skipped_when_already_human(client, auth_headers, monkeypatch) -> None:
    """If detection already returns ai_p <= target, rewrite is a no-op."""
    calls = {"n": 0}

    async def fake_llm_call(settings, model, system_prompt, user_prompt, schema):
        calls["n"] += 1
        is_sentence = "sentences" in schema["name"] or "SENTENCES" in user_prompt
        payload = _sentence_payload([0.05, 0.05, 0.05]) if is_sentence else _holistic_payload(0.05)
        return {
            "choices": [{"message": {"content": json.dumps(payload)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }

    monkeypatch.setattr(llm_judge_module, "_call_openrouter", fake_llm_call)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    from aidetect import config as cfg
    cfg.get_settings.cache_clear()

    resp = await client.post(
        "/v1/rewrite",
        headers=auth_headers,
        json={"text": "Some clearly human casual text.", "mode": "fast"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["target_reached"] is True
    assert body["rewritten_text"] == "Some clearly human casual text."
    assert body["before"]["ai_probability"] == body["after"]["ai_probability"]


@pytest.mark.asyncio
async def test_rewrite_lowers_ai_probability(client, auth_headers, monkeypatch) -> None:
    """Mocked rewriter reduces AI signal; second detection returns below target."""
    state = {"holistic_calls": 0}

    async def fake_judge_call(settings, model, system_prompt, user_prompt, schema):
        is_sentence = "SENTENCES" in user_prompt
        if is_sentence:
            payload = (
                _sentence_payload([0.8, 0.75, 0.7])
                if state["holistic_calls"] <= 1
                else _sentence_payload([0.08, 0.10, 0.05])
            )
            return {
                "choices": [{"message": {"content": json.dumps(payload)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            }
        # holistic: first call = AI-like, subsequent = human-like
        ai_score = 0.85 if state["holistic_calls"] < 1 else 0.10
        state["holistic_calls"] += 1
        return {
            "choices": [{"message": {"content": json.dumps(_holistic_payload(ai_score))}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }

    async def fake_rewriter_call(settings, model, system_prompt, user_prompt):
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "rewritten_text": _HUMAN_REWRITE,
                        "changes": ["removed 'The reality is'", "broke parallel list"],
                        "preserved": "thesis about React perf",
                    })
                }
            }],
            "usage": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
        }

    monkeypatch.setattr(llm_judge_module, "_call_openrouter", fake_judge_call)
    monkeypatch.setattr(rewriter_module, "_call_rewriter", fake_rewriter_call)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    from aidetect import config as cfg
    cfg.get_settings.cache_clear()

    resp = await client.post(
        "/v1/rewrite",
        headers=auth_headers,
        json={
            "text": _AI_TEXT,
            "mode": "fast",
            "options": {"voice": "casual_tech_blog", "max_iterations": 2},
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rewritten_text"] != _AI_TEXT
    assert body["before"]["ai_probability"] >= body["after"]["ai_probability"]
    assert body["changes"], "changes should be populated"
    assert body["voice"] == "casual_tech_blog"


@pytest.mark.asyncio
async def test_rewrite_requires_api_key(client, auth_headers) -> None:
    """Without OPENROUTER_API_KEY the endpoint returns 503."""
    resp = await client.post(
        "/v1/rewrite",
        headers=auth_headers,
        json={"text": "abc", "mode": "fast"},
    )
    assert resp.status_code == 503
    assert "OPENROUTER_API_KEY" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_rewrite_requires_token(client) -> None:
    resp = await client.post("/v1/rewrite", json={"text": "abc"})
    assert resp.status_code == 401
