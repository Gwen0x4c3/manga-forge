from __future__ import annotations

import json
import logging
import re
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import embeddings_configured, get_embeddings
from app.core.vector_store import vector_store
from app.models.asset import Asset
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.pit import Pit
from app.models.project import Project

logger = logging.getLogger(__name__)

async def get_canon_rules(db: AsyncSession, project_id: str) -> dict | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    return project.canon_rules if project else None


async def update_canon_rules(db: AsyncSession, project_id: str, canon_rules: dict) -> dict | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return None
    project.canon_rules = canon_rules
    await db.commit()
    await db.refresh(project)
    return project.canon_rules


async def get_long_summary(db: AsyncSession, project_id: str) -> str | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    return project.long_summary if project else None


async def update_long_summary(db: AsyncSession, project_id: str, summary: str) -> str | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return None
    project.long_summary = summary
    await db.commit()
    await db.refresh(project)
    return project.long_summary


# Append the next episode, then LLM-compress once the rolling summary outgrows
# the budget. Without this the field either grows unbounded or (worse) loses
# all history older than the latest episode.
_SUMMARY_COMPRESS_THRESHOLD = 6000
_SUMMARY_COMPRESS_TARGET = 3000
_SUMMARY_TRUNCATE_KEEP = 4000


async def append_episode_summary(
    db: AsyncSession,
    project_id: str,
    episode_number,
    summary: str,
) -> str | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project or not summary.strip():
        return project.long_summary if project else None

    entry = summary.strip()
    text = project.long_summary or ""
    text = f"{text}\n第{episode_number}话：{entry}" if text else f"第{episode_number}话：{entry}"

    if len(text) > _SUMMARY_COMPRESS_THRESHOLD:
        text = await _compress_long_summary(text) or text[-_SUMMARY_TRUNCATE_KEEP:]

    project.long_summary = text
    await db.commit()
    await db.refresh(project)
    return project.long_summary


async def _compress_long_summary(text: str) -> str | None:
    """LLM-compress the rolling summary; None means the caller should truncate instead."""
    from app.config import settings
    from app.core.llm import get_llm_client

    system = (
        "You are a manga story archivist. Compress the episode-by-episode story "
        "history into a compact rolling summary.\n"
        "Preserve, in order of importance: the main plotline and its current state, "
        "character relationships and persistent state changes (injuries, possessions, "
        "knowledge), key items/locations, and ALL unresolved foreshadowing.\n"
        "Drop scene-level detail and dialogue. Write in the same language as the input. "
        f"Keep it under {_SUMMARY_COMPRESS_TARGET} characters. Output the summary only."
    )
    try:
        client = get_llm_client()
        from pydantic import BaseModel

        class Compressed(BaseModel):
            summary: str

        result = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            response_model=Compressed,
            max_retries=1,
        )
        compressed = result.summary.strip()
        return compressed if len(compressed) >= 50 else None
    except Exception:
        logger.warning("Long summary compression failed, truncating instead", exc_info=True)
        return None


async def get_recent_window(
    db: AsyncSession,
    project_id: str,
    branch_id: str,
    window_size: int = 5,
) -> list[dict]:
    query = (
        select(Episode)
        .where(Episode.project_id == project_id, Episode.branch_id == branch_id)
        .order_by(Episode.number.desc())
        .limit(window_size)
    )
    result = await db.execute(query)
    episodes = result.scalars().all()
    episodes = list(reversed(episodes))

    window = []
    for ep in episodes:
        mem_result = await db.execute(
            select(EpisodeMemory).where(
                EpisodeMemory.episode_id == ep.id,
                EpisodeMemory.type == "summary",
            )
        )
        memory = mem_result.scalar_one_or_none()
        window.append({
            "episode_id": ep.id,
            "number": ep.number,
            "title": ep.title,
            "summary": memory.content if memory else None,
        })
    return window


async def search_rag(db: AsyncSession, project_id: str, query: str, top_k: int = 5) -> list[dict]:
    """Semantic search over episode memories.

    Vector search when an embedding model is configured; otherwise (or on
    vector-store failure) falls back to keyword search over recent memories.
    """
    if embeddings_configured():
        try:
            query_vectors = await get_embeddings([query])
            if query_vectors:
                results = await vector_store.search(
                    query_vector=query_vectors[0],
                    limit=top_k,
                    project_id=project_id,
                )
                if results:
                    return results
        except Exception:
            logger.warning("Vector RAG search failed, falling back to keyword search", exc_info=True)
    return await _keyword_search(db, project_id, query, top_k)


async def _keyword_search(db: AsyncSession, project_id: str, query: str, top_k: int) -> list[dict]:
    terms = [t for t in re.split(r"[\s,，。、；;:：!？?（）()\[\]\"']+", query) if len(t) >= 2][:20]
    if not terms:
        return []
    stmt = (
        select(EpisodeMemory, Episode.number)
        .join(Episode, EpisodeMemory.episode_id == Episode.id)
        .where(Episode.project_id == project_id, EpisodeMemory.type.in_(("summary", "events")))
        .order_by(Episode.number.desc())
        .limit(200)
    )
    rows = (await db.execute(stmt)).all()

    scored: list[tuple[float, Decimal, EpisodeMemory, str]] = []
    for memory, number in rows:
        if memory.type == "summary" and isinstance(memory.content, dict):
            text = memory.content.get("summary", "")
        elif memory.type == "events" and isinstance(memory.content, dict):
            events = memory.content.get("data", [])
            text = " ".join(
                e.get("description", "") if isinstance(e, dict) else str(e) for e in events
            )
        else:
            text = json.dumps(memory.content, ensure_ascii=False)
        hits = sum(1 for t in terms if t.lower() in text.lower())
        if hits:
            scored.append((hits / len(terms), number, memory, text))
    scored.sort(key=lambda x: (-x[0], -x[1]))

    return [
        {
            "id": memory.id,
            "score": score,
            "payload": {
                "content": text,
                "episode_id": memory.episode_id,
                "episode_number": number,
                "type": memory.type,
            },
        }
        for score, number, memory, text in scored[:top_k]
    ]


async def build_context_for_generation(
    db: AsyncSession,
    project_id: str,
    branch_id: str,
    base_episode_number: Decimal,
) -> dict:
    canon = await get_canon_rules(db, project_id)
    long_summary = await get_long_summary(db, project_id)
    recent_window = await get_recent_window(db, project_id, branch_id, window_size=5)

    pit_result = await db.execute(
        select(Pit).where(Pit.project_id == project_id, Pit.status == "open")
    )
    active_pits = pit_result.scalars().all()

    asset_result = await db.execute(
        select(Asset).where(Asset.project_id == project_id)
    )
    assets = asset_result.scalars().all()

    # RAG: retrieve relevant older memories. The query combines the latest
    # episode summary with open pit descriptions so both continuity threads
    # and foreshadowing pull in distant-context fragments.
    rag_query_parts = [ep["summary"].get("summary", "") for ep in recent_window if ep["summary"]]
    rag_query_parts.extend(pit.description or "" for pit in active_pits)
    rag_query = " ".join(p for p in rag_query_parts if p)
    rag_memories = await search_rag(db, project_id, rag_query, top_k=5) if rag_query else []

    return {
        "canon_rules": json.dumps(canon, ensure_ascii=False) if canon else "",
        "long_summary": long_summary or "",
        "recent_episodes": [
            {
                "number": ep["number"],
                "title": ep["title"],
                "summary": ep["summary"].get("summary", "") if ep["summary"] else "",
                "state_changes": ep["summary"].get("state_changes", []) if ep["summary"] else [],
            }
            for ep in recent_window
        ],
        "rag_memories": [
            {
                "content": m["payload"].get("content", ""),
                "episode_number": m["payload"].get("episode_number"),
                "type": m["payload"].get("type", ""),
            }
            for m in rag_memories
        ],
        "active_pits": [
            {
                "description": pit.description,
                "priority": pit.priority,
                "trigger_hint": pit.trigger_hint,
            }
            for pit in active_pits
        ],
        "assets": [
            {
                "type": asset.type,
                "name": asset.name,
                "description": asset.description or "",
            }
            for asset in assets
        ],
    }


async def vectorize_and_store_episode_memory(
    db: AsyncSession,
    project_id: str,
    episode_id: str,
    episode_number: int,
    understanding: dict,
) -> None:
    texts = []
    payloads = []

    summary_text = understanding.get("summary", "")
    if summary_text:
        texts.append(summary_text)
        payloads.append({
            "project_id": project_id,
            "episode_id": episode_id,
            "episode_number": episode_number,
            "type": "summary",
            "content": summary_text,
        })

    for event in understanding.get("events", []):
        event_text = event.get("description", "")
        if event_text:
            texts.append(event_text)
            payloads.append({
                "project_id": project_id,
                "episode_id": episode_id,
                "episode_number": episode_number,
                "type": "event",
                "content": event_text,
            })

    for change in understanding.get("state_changes", []):
        change_text = f"{change.get('character', '')}: {change.get('attribute', '')} -> {change.get('after', '')}"
        if change_text.strip("-> "):
            texts.append(change_text)
            payloads.append({
                "project_id": project_id,
                "episode_id": episode_id,
                "episode_number": episode_number,
                "type": "state_change",
                "content": change_text,
            })

    if not texts or not embeddings_configured():
        if not embeddings_configured():
            logger.info("Embedding model not configured — skipping vectorization of episode %s", episode_id)
        return

    vectors = await get_embeddings(texts)
    if not vectors:
        return

    points = []
    for i, (vector, payload) in enumerate(zip(vectors, payloads)):
        points.append({
            "id": str(uuid.uuid4()),
            "vector": vector,
            "payload": payload,
        })
    await vector_store.upsert_vectors(points)
