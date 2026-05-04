from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import instructor
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
    response = await client.embeddings.create(
        model=settings.OPENAI_EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]
