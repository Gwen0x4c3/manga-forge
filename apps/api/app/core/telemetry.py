from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageAttribution:
    project_id: str | None = None
    episode_id: str | None = None
    generation_run_id: str | None = None
    operation: str | None = None
    panel_id: str | None = None


_usage_ctx: ContextVar[UsageAttribution] = ContextVar("manga_forge_usage_ctx", default=UsageAttribution())

# Optional test hook for unit tests to capture usage payloads without requiring a DB round-trip
_test_sink: Callable[[dict[str, Any]], Coroutine[Any, Any, None] | None] | None = None


def set_usage_test_sink(
    sink: Callable[[dict[str, Any]], Coroutine[Any, Any, None] | None] | None,
) -> None:
    global _test_sink
    _test_sink = sink


@contextmanager
def usage_context(
    *,
    project_id: str | None = None,
    episode_id: str | None = None,
    generation_run_id: str | None = None,
    operation: str | None = None,
    panel_id: str | None = None,
):
    """Attach project/episode/run/operation metadata to all downstream LLM & image calls."""
    cur = _usage_ctx.get()
    nxt = replace(
        cur,
        project_id=project_id if project_id is not None else cur.project_id,
        episode_id=episode_id if episode_id is not None else cur.episode_id,
        generation_run_id=generation_run_id if generation_run_id is not None else cur.generation_run_id,
        operation=operation if operation is not None else cur.operation,
        panel_id=panel_id if panel_id is not None else cur.panel_id,
    )
    token = _usage_ctx.set(nxt)
    try:
        yield nxt
    finally:
        _usage_ctx.reset(token)


def get_usage_context() -> UsageAttribution:
    return _usage_ctx.get()


def _read_attr(obj: Any, *names: str) -> Any:
    if obj is None:
        return None
    for name in names:
        if isinstance(obj, dict):
            val = obj.get(name)
        else:
            val = getattr(obj, name, None)
        if val is not None:
            return val
    return None


def _as_int(val: Any) -> int:
    try:
        return max(0, int(val)) if val is not None else 0
    except (TypeError, ValueError):
        return 0


def extract_llm_usage(response: Any, fallback_model: str = "unknown") -> dict[str, Any]:
    """Normalize token usage across OpenAI, GLM, DeepSeek, Gemini, and Anthropic-compatible gateways."""
    usage = _read_attr(response, "usage")
    model = str(_read_attr(response, "model") or fallback_model or "unknown")

    if usage is None:
        return {
            "model": model,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 0,
            "reasoning_tokens": 0,
        }

    prompt_details = _read_attr(usage, "prompt_tokens_details", "input_tokens_details")
    completion_details = _read_attr(usage, "completion_tokens_details", "output_tokens_details")

    prompt_tokens_raw = _read_attr(usage, "prompt_tokens")
    input_tokens_raw = _read_attr(usage, "input_tokens")
    output_tokens = _as_int(_read_attr(usage, "completion_tokens", "output_tokens"))

    cache_read_tokens = _as_int(
        _read_attr(prompt_details, "cached_tokens", "cache_read_tokens")
        or _read_attr(usage, "cache_read_input_tokens", "prompt_cache_hit_tokens", "cached_tokens")
    )
    cache_write_tokens = _as_int(
        _read_attr(prompt_details, "cache_creation_tokens", "cache_write_tokens")
        or _read_attr(usage, "cache_creation_input_tokens", "cache_write_tokens")
    )
    reasoning_tokens = _as_int(
        _read_attr(completion_details, "reasoning_tokens")
        or _read_attr(usage, "reasoning_tokens")
    )

    # OpenAI/GLM/DeepSeek: prompt_tokens already includes cached_tokens.
    # Anthropic-style: input_tokens excludes cache_read_input_tokens & cache_creation_input_tokens.
    if prompt_tokens_raw is not None:
        input_tokens = _as_int(prompt_tokens_raw)
        if cache_read_tokens > input_tokens:
            input_tokens = cache_read_tokens
    else:
        base_in = _as_int(input_tokens_raw)
        if _read_attr(usage, "cache_read_input_tokens", "cache_creation_input_tokens") is not None:
            input_tokens = base_in + cache_read_tokens + cache_write_tokens
        else:
            input_tokens = max(base_in, cache_read_tokens)

    raw_total = _as_int(_read_attr(usage, "total_tokens"))
    total_tokens = max(raw_total, input_tokens + output_tokens)

    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


async def record_usage_event(
    *,
    kind: str,
    operation: str | None = None,
    provider: str = "openai",
    model: str = "unknown",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    total_tokens: int | None = None,
    image_count: int = 0,
    image_size: str | None = None,
    duration_ms: int = 0,
    status: str = "succeeded",
    error: str | None = None,
    meta: dict[str, Any] | None = None,
    project_id: str | None = None,
    episode_id: str | None = None,
    generation_run_id: str | None = None,
) -> None:
    ctx = get_usage_context()
    eff_project_id = project_id if project_id is not None else ctx.project_id
    eff_episode_id = episode_id if episode_id is not None else ctx.episode_id
    eff_run_id = generation_run_id if generation_run_id is not None else ctx.generation_run_id
    eff_operation = operation or ctx.operation or (
        "image_generate" if kind == "image" else "embedding" if kind == "embedding" else "llm_chat"
    )
    eff_total = total_tokens if total_tokens is not None else (input_tokens + output_tokens)
    eff_meta = dict(meta or {})
    if ctx.panel_id and "panel_id" not in eff_meta:
        eff_meta["panel_id"] = ctx.panel_id

    payload = {
        "project_id": eff_project_id,
        "episode_id": eff_episode_id,
        "generation_run_id": eff_run_id,
        "kind": kind,
        "operation": eff_operation,
        "provider": provider or "openai",
        "model": model or "unknown",
        "input_tokens": max(0, int(input_tokens)),
        "output_tokens": max(0, int(output_tokens)),
        "cache_read_tokens": max(0, int(cache_read_tokens)),
        "cache_write_tokens": max(0, int(cache_write_tokens)),
        "total_tokens": max(0, int(eff_total)),
        "image_count": max(0, int(image_count)),
        "image_size": image_size,
        "duration_ms": max(0, int(duration_ms)),
        "status": status,
        "error": error[:2000] if error else None,
        "meta": eff_meta or None,
    }

    if _test_sink is not None:
        res = _test_sink(payload)
        if res is not None:
            await res
        return

    try:
        from app.database import worker_session
        from app.models.usage_record import UsageRecord

        async with worker_session() as db:
            db.add(UsageRecord(**payload))
            await db.commit()
    except Exception:
        logger.debug("Failed to persist usage record (non-fatal)", exc_info=True)


class _TrackedAsyncStream:
    """Async stream wrapper that transparently forwards OpenAI streaming chunks
    while recording accurate token usage & elapsed duration on completion or error."""

    def __init__(
        self,
        inner: Any,
        *,
        provider: str,
        requested_model: str,
        t0: float,
        ctx: UsageAttribution,
    ) -> None:
        self._inner = inner
        self._provider = provider
        self._model = requested_model
        self._t0 = t0
        self._ctx = ctx
        self._last_usage: Any = None
        self._recorded = False

    def __aiter__(self):
        return self

    async def __aenter__(self):
        if hasattr(self._inner, "__aenter__"):
            await self._inner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if hasattr(self._inner, "__aexit__"):
            await self._inner.__aexit__(exc_type, exc, tb)
        if not self._recorded:
            err_msg = f"{exc_type.__name__}: {exc}" if exc else None
            await self._flush(status="failed" if exc else "succeeded", error=err_msg)

    async def aclose(self) -> None:
        if hasattr(self._inner, "aclose"):
            await self._inner.aclose()
        if not self._recorded:
            await self._flush(status="succeeded", error=None)

    async def _flush(self, *, status: str, error: str | None) -> None:
        if self._recorded:
            return
        self._recorded = True
        elapsed_ms = int((time.perf_counter() - self._t0) * 1000)
        if self._last_usage is not None:
            fake_resp = type("_StreamResp", (), {"usage": self._last_usage, "model": self._model})()
            parsed = extract_llm_usage(fake_resp, fallback_model=self._model)
        else:
            parsed = {
                "model": self._model,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 0,
                "reasoning_tokens": 0,
            }
        meta: dict[str, Any] = {"streamed": True}
        if parsed["reasoning_tokens"]:
            meta["reasoning_tokens"] = parsed["reasoning_tokens"]
        await record_usage_event(
            kind="llm",
            operation=self._ctx.operation,
            provider=self._provider,
            model=parsed["model"],
            input_tokens=parsed["input_tokens"],
            output_tokens=parsed["output_tokens"],
            cache_read_tokens=parsed["cache_read_tokens"],
            cache_write_tokens=parsed["cache_write_tokens"],
            total_tokens=parsed["total_tokens"],
            duration_ms=elapsed_ms,
            status=status,
            error=error,
            meta=meta,
            project_id=self._ctx.project_id,
            episode_id=self._ctx.episode_id,
            generation_run_id=self._ctx.generation_run_id,
        )

    async def __anext__(self):
        try:
            chunk = await self._inner.__anext__()
        except StopAsyncIteration:
            await self._flush(status="succeeded", error=None)
            raise
        except Exception as exc:
            await self._flush(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        c_model = _read_attr(chunk, "model")
        if c_model:
            self._model = str(c_model)
        c_usage = _read_attr(chunk, "usage")
        if c_usage is not None:
            self._last_usage = c_usage
        return chunk


def instrument_openai_client(client: AsyncOpenAI, provider: str = "openai") -> AsyncOpenAI:
    """Wrap AsyncOpenAI chat.completions.create so every LLM call (raw, streamed, or instructor) is recorded."""
    completions = client.chat.completions
    if getattr(completions, "_mf_instrumented", False):
        return client

    original_create = completions.create

    async def tracked_create(*args: Any, **kwargs: Any):
        requested_model = str(kwargs.get("model") or "unknown")
        t0 = time.perf_counter()

        if kwargs.get("stream"):
            ctx = get_usage_context()
            call_kw = dict(kwargs)
            injected_opts = "stream_options" not in call_kw
            if injected_opts:
                call_kw["stream_options"] = {"include_usage": True}
            try:
                stream_obj = await original_create(*args, **call_kw)
            except Exception as exc:
                if injected_opts and "stream_options" in str(exc).lower():
                    call_kw.pop("stream_options", None)
                    stream_obj = await original_create(*args, **call_kw)
                else:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    await record_usage_event(
                        kind="llm",
                        operation=ctx.operation,
                        provider=provider,
                        model=requested_model,
                        duration_ms=elapsed_ms,
                        status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                        project_id=ctx.project_id,
                        episode_id=ctx.episode_id,
                        generation_run_id=ctx.generation_run_id,
                    )
                    raise
            if hasattr(stream_obj, "__aiter__"):
                return _TrackedAsyncStream(
                    stream_obj,
                    provider=provider,
                    requested_model=requested_model,
                    t0=t0,
                    ctx=ctx,
                )
            response = stream_obj
        else:
            try:
                response = await original_create(*args, **kwargs)
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                await record_usage_event(
                    kind="llm",
                    provider=provider,
                    model=requested_model,
                    duration_ms=elapsed_ms,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        parsed = extract_llm_usage(response, fallback_model=requested_model)
        meta: dict[str, Any] = {}
        if parsed["reasoning_tokens"]:
            meta["reasoning_tokens"] = parsed["reasoning_tokens"]
        await record_usage_event(
            kind="llm",
            provider=provider,
            model=parsed["model"],
            input_tokens=parsed["input_tokens"],
            output_tokens=parsed["output_tokens"],
            cache_read_tokens=parsed["cache_read_tokens"],
            cache_write_tokens=parsed["cache_write_tokens"],
            total_tokens=parsed["total_tokens"],
            duration_ms=elapsed_ms,
            status="succeeded",
            meta=meta or None,
        )
        return response

    completions.create = tracked_create  # type: ignore[method-assign]
    completions._mf_instrumented = True  # type: ignore[attr-defined]
    return client
