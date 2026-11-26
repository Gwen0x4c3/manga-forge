from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core.image_backend import get_image_backend
from app.core.telemetry import (
    extract_llm_usage,
    instrument_openai_client,
    set_usage_test_sink,
    usage_context,
)
from app.services.usage_service import _calc_cache_hit_rate


def test_extract_llm_usage_openai_cached_tokens():
    resp = SimpleNamespace(
        model="gpt-4o-2024-11-20",
        usage=SimpleNamespace(
            prompt_tokens=10000,
            completion_tokens=1500,
            total_tokens=11500,
            prompt_tokens_details=SimpleNamespace(cached_tokens=7500),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=400),
        ),
    )
    parsed = extract_llm_usage(resp)
    assert parsed["model"] == "gpt-4o-2024-11-20"
    assert parsed["input_tokens"] == 10000
    assert parsed["output_tokens"] == 1500
    assert parsed["cache_read_tokens"] == 7500
    assert parsed["cache_write_tokens"] == 0
    assert parsed["total_tokens"] == 11500
    assert parsed["reasoning_tokens"] == 400
    assert _calc_cache_hit_rate(parsed["cache_read_tokens"], parsed["input_tokens"]) == 75.0


def test_extract_llm_usage_anthropic_cache_read_and_write():
    resp = SimpleNamespace(
        model="claude-sonnet-4-5",
        usage={
            "input_tokens": 2000,
            "output_tokens": 800,
            "cache_read_input_tokens": 6000,
            "cache_creation_input_tokens": 2000,
        },
    )
    parsed = extract_llm_usage(resp)
    assert parsed["input_tokens"] == 10000
    assert parsed["output_tokens"] == 800
    assert parsed["cache_read_tokens"] == 6000
    assert parsed["cache_write_tokens"] == 2000
    assert parsed["total_tokens"] == 10800
    assert _calc_cache_hit_rate(parsed["cache_read_tokens"], parsed["input_tokens"]) == 60.0


@pytest.mark.asyncio
async def test_instrumented_openai_client_captures_tokens_and_context():
    captured: list[dict] = []
    set_usage_test_sink(lambda payload: captured.append(payload))
    try:
        async def fake_create(**kwargs):
            return SimpleNamespace(
                model=kwargs["model"],
                usage=SimpleNamespace(
                    prompt_tokens=5000,
                    completion_tokens=600,
                    total_tokens=5600,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=4000),
                ),
            )

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
        instrument_openai_client(fake_client, provider="openai")

        with usage_context(project_id="proj-1", episode_id="ep-2", operation="story_qa"):
            await fake_client.chat.completions.create(model="test-model", messages=[])

        assert len(captured) == 1
        rec = captured[0]
        assert rec["kind"] == "llm"
        assert rec["project_id"] == "proj-1"
        assert rec["episode_id"] == "ep-2"
        assert rec["operation"] == "story_qa"
        assert rec["model"] == "test-model"
        assert rec["input_tokens"] == 5000
        assert rec["output_tokens"] == 600
        assert rec["cache_read_tokens"] == 4000
        assert rec["duration_ms"] >= 0
        assert rec["status"] == "succeeded"
    finally:
        set_usage_test_sink(None)


@pytest.mark.asyncio
async def test_instrumented_image_backend_captures_generation_record():
    captured: list[dict] = []
    set_usage_test_sink(lambda payload: captured.append(payload))
    try:
        backend = get_image_backend(backend_name="mock")
        with usage_context(project_id="proj-9", episode_id="ep-5", generation_run_id="run-7", panel_id="P1-2"):
            res = await backend.generate(prompt="manga hero panel", size=(1024, 1536))
        assert res.image_data
        assert len(captured) == 1
        rec = captured[0]
        assert rec["kind"] == "image"
        assert rec["operation"] == "image_generate"
        assert rec["provider"] == "mock"
        assert rec["project_id"] == "proj-9"
        assert rec["episode_id"] == "ep-5"
        assert rec["generation_run_id"] == "run-7"
        assert rec["image_count"] == 1
        assert rec["image_size"] == "1024x1536"
        assert rec["meta"]["panel_id"] == "P1-2"
        assert rec["status"] == "succeeded"
    finally:
        set_usage_test_sink(None)
