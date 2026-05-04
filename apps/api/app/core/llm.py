from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import instructor
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.config import settings

if TYPE_CHECKING:
    pass


@lru_cache
def get_llm_client() -> instructor.Instructor:
    openai_client = AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )
    return instructor.from_openai(openai_client)


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    client = AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )
    try:
        response = await client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=texts,
        )
    except Exception as e:
        _raise_llm_error(e)
    return [item.embedding for item in response.data]


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
