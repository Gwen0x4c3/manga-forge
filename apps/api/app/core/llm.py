from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
import instructor
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.core.provider_runtime import ResolvedModelConfig, normalize_base_url, resolve_role_config
from app.core.telemetry import extract_llm_usage, instrument_openai_client, record_usage_event

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def get_active_llm_config(role: str = "main_llm") -> ResolvedModelConfig:
    return resolve_role_config(role)


def get_active_model(role: str = "main_llm") -> str:
    return resolve_role_config(role).model


def _build_openai_client(role: str = "main_llm") -> AsyncOpenAI:
    # httpx's default trust_env=True crashes when no_proxy contains bare IPv6
    # literals (e.g. "::1"); build the transport explicitly instead.
    cfg = resolve_role_config(role)
    base_url = _normalize_openai_base_url(cfg.base_url)
    extra_headers = dict(cfg.extra_headers or {})
    if cfg.provider_key == "anthropic" and cfg.api_key:
        extra_headers.setdefault("anthropic-version", "2023-06-01")
    client = AsyncOpenAI(
        api_key=cfg.api_key or "no-key",
        base_url=base_url,
        default_headers=extra_headers or None,
        http_client=httpx.AsyncClient(trust_env=False, timeout=600.0),
    )
    return instrument_openai_client(client, provider=cfg.provider_key or "openai")


def get_llm_client(role: str = "main_llm") -> instructor.Instructor:
    config_error = get_llm_config_error(role=role)
    if config_error:
        raise RuntimeError(config_error)
    return instructor.from_openai(_build_openai_client(role=role))


def get_raw_openai_client(role: str = "main_llm") -> AsyncOpenAI:
    """Raw chat-completions client (no instructor) for multi-turn tool-calling loops."""
    config_error = get_llm_config_error(role=role)
    if config_error:
        raise RuntimeError(config_error)
    return _build_openai_client(role=role)


def embeddings_configured() -> bool:
    cfg = resolve_role_config("embedding")
    return bool((cfg.model or "").strip())


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Return embedding vectors, or an empty list when no model is configured.

    Callers treat [] as "embeddings unavailable" and degrade gracefully
    (skip vectorization, fall back to keyword retrieval).
    """
    if not embeddings_configured():
        logger.warning("Embedding model is not configured — embeddings disabled, RAG falls back to keyword search")
        return []
    cfg = resolve_role_config("embedding")
    config_error = get_llm_config_error(role="embedding")
    if config_error:
        raise RuntimeError(config_error)
    client = _build_openai_client(role="embedding")
    t0 = time.perf_counter()
    try:
        response = await client.embeddings.create(
            model=cfg.model,
            input=texts,
        )
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        await record_usage_event(
            kind="embedding",
            operation="embedding",
            provider=cfg.provider_key or "openai",
            model=cfg.model,
            duration_ms=elapsed_ms,
            status="failed",
            error=f"{type(e).__name__}: {e}",
            meta={"batch_size": len(texts)},
        )
        _raise_llm_error(e)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    parsed = extract_llm_usage(response, fallback_model=cfg.model)
    await record_usage_event(
        kind="embedding",
        operation="embedding",
        provider=cfg.provider_key or "openai",
        model=parsed["model"],
        input_tokens=parsed["input_tokens"],
        output_tokens=0,
        cache_read_tokens=parsed["cache_read_tokens"],
        cache_write_tokens=parsed["cache_write_tokens"],
        total_tokens=parsed["total_tokens"],
        duration_ms=elapsed_ms,
        status="succeeded",
        meta={"batch_size": len(texts)},
    )
    return [item.embedding for item in response.data]


def _normalize_openai_base_url(base_url: str | None) -> str | None:
    return normalize_base_url(base_url)


def get_llm_config_error(role: str = "main_llm") -> str | None:
    cfg = resolve_role_config(role)
    if cfg.provider_key not in ("custom", "ollama", "comfyui", "mock"):
        api_key = (cfg.api_key or "").strip()
        if not api_key or api_key == "sk-xxx":
            return "LLM 未配置：请在「模型与服务商」页面添加 API Key，或在 .env 中设置 OPENAI_API_KEY"
    base_url = (cfg.base_url or "").strip()
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https", ""):
            return "LLM 配置错误：服务商 Base URL 必须以 http:// 或 https:// 开头"
    return None


def ensure_llm_configured(role: str = "main_llm") -> None:
    config_error = get_llm_config_error(role=role)
    if config_error:
        raise HTTPException(status_code=400, detail=config_error)


def _raise_llm_error(exc: Exception):
    error_type = type(exc).__name__
    detail = str(exc)

    if "AuthenticationError" in error_type:
        raise HTTPException(
            status_code=400,
            detail="LLM API Key 未配置或无效，请检查 OPENAI_API_KEY 环境变量",
        )
    elif "RateLimitError" in error_type:
        raise HTTPException(
            status_code=429,
            detail="LLM API 调用频率超限，请稍后重试",
        )
    elif "BadRequestError" in error_type:
        raise HTTPException(
            status_code=400,
            detail=f"LLM 请求参数错误：{detail}",
        )
    else:
        raise HTTPException(
            status_code=500,
            detail=f"LLM 调用失败：{detail}",
        )
