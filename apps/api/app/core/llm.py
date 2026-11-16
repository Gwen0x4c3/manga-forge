from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
import instructor
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _build_openai_client() -> AsyncOpenAI:
    # httpx's default trust_env=True crashes when no_proxy contains bare IPv6
    # literals (e.g. "::1"); build the transport explicitly instead.
    base_url = _normalize_openai_base_url(settings.OPENAI_BASE_URL)
    return AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=base_url,
        http_client=httpx.AsyncClient(trust_env=False, timeout=600.0),
    )


@lru_cache
def get_llm_client() -> instructor.Instructor:
    config_error = get_llm_config_error()
    if config_error:
        raise RuntimeError(config_error)
    return instructor.from_openai(_build_openai_client())


def embeddings_configured() -> bool:
    return bool((settings.OPENAI_EMBEDDING_MODEL or "").strip())


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Return embedding vectors, or an empty list when no model is configured.

    Callers treat [] as "embeddings unavailable" and degrade gracefully
    (skip vectorization, fall back to keyword retrieval).
    """
    if not embeddings_configured():
        logger.warning("OPENAI_EMBEDDING_MODEL is not set — embeddings disabled, RAG falls back to keyword search")
        return []
    config_error = get_llm_config_error()
    if config_error:
        raise RuntimeError(config_error)
    client = _build_openai_client()
    try:
        response = await client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=texts,
        )
    except Exception as e:
        _raise_llm_error(e)
    return [item.embedding for item in response.data]


def _normalize_openai_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    normalized = base_url.strip()
    parsed = urlparse(normalized)
    if parsed.scheme:
        return normalized
    return f"https://{normalized.lstrip('/')}"


def get_llm_config_error() -> str | None:
    if settings.LLM_BACKEND != "openai":
        return None
    api_key = (settings.OPENAI_API_KEY or "").strip()
    if not api_key or api_key == "sk-xxx":
        return "LLM 未配置：请在 .env 中设置有效的 OPENAI_API_KEY"
    base_url = (settings.OPENAI_BASE_URL or "").strip()
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https", ""):
            return "LLM 配置错误：OPENAI_BASE_URL 必须以 http:// 或 https:// 开头"
    return None


def ensure_llm_configured() -> None:
    config_error = get_llm_config_error()
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
