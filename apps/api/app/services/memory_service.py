from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import get_embeddings
from app.core.vector_store import vector_store
from app.models.asset import Asset
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.pit import Pit
from app.models.project import Project


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
    query_vectors = await get_embeddings([query])
    if not query_vectors:
        return []
    results = await vector_store.search(
        query_vector=query_vectors[0],
        limit=top_k,
        project_id=project_id,
    )
    return results


async def build_context_for_generation(
    db: AsyncSession,
    project_id: str,
    branch_id: str,
    base_episode_number: int,
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

    if not texts:
        return

    vectors = await get_embeddings(texts)
    points = []
    for i, (vector, payload) in enumerate(zip(vectors, payloads)):
        points.append({
            "id": str(uuid.uuid4()),
            "vector": vector,
            "payload": payload,
        })
    await vector_store.upsert_vectors(points)
