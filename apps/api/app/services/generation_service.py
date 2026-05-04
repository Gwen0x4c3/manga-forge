from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.generation_run import GenerationRun
from app.models.project import Project


async def create_generation_run(
    db: AsyncSession,
    episode_id: str,
    stage: str,
    backend: str | None = None,
    model: str | None = None,
    params: dict | None = None,
    prompt: str | None = None,
    retrieved_context: dict | None = None,
) -> GenerationRun:
    run = GenerationRun(
        id=str(uuid.uuid4()),
        episode_id=episode_id,
        stage=stage,
        backend=backend,
        model=model,
        params=params,
        prompt=prompt,
        retrieved_context=retrieved_context,
        status="queued",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def update_generation_run(
    db: AsyncSession,
    run_id: str,
    status: str,
    error: str | None = None,
) -> GenerationRun | None:
    result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return None
    run.status = status
    run.error = error
    if status in ("succeeded", "failed"):
        run.finished_at = datetime.now()
    await db.commit()
    await db.refresh(run)
    return run


async def save_episode_understanding(
    db: AsyncSession,
    episode_id: str,
    understanding: dict,
) -> list[EpisodeMemory]:
    memories = []
    type_mapping = {
        "summary": "summary",
        "events": "events",
        "state_changes": "state_snapshot",
    }
    for key, memory_type in type_mapping.items():
        if key in understanding and understanding[key]:
            memory = EpisodeMemory(
                id=str(uuid.uuid4()),
                episode_id=episode_id,
                type=memory_type,
                content=understanding[key] if isinstance(understanding[key], dict) else {"data": understanding[key]},
            )
            db.add(memory)
            memories.append(memory)

    if understanding.get("new_assets"):
        memory = EpisodeMemory(
            id=str(uuid.uuid4()),
            episode_id=episode_id,
            type="summary",
            content={"new_assets": understanding["new_assets"]},
        )
        db.add(memory)
        memories.append(memory)

    await db.commit()
    return memories


async def save_storyboard(
    db: AsyncSession,
    episode_id: str,
    storyboard: dict,
) -> EpisodeMemory:
    memory = EpisodeMemory(
        id=str(uuid.uuid4()),
        episode_id=episode_id,
        type="storyboard_json",
        content=storyboard,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


async def update_episode_status(
    db: AsyncSession,
    episode_id: str,
    status: str,
) -> Episode | None:
    result = await db.execute(select(Episode).where(Episode.id == episode_id))
    episode = result.scalar_one_or_none()
    if not episode:
        return None
    episode.status = status
    await db.commit()
    await db.refresh(episode)
    return episode


async def update_project_long_summary(
    db: AsyncSession,
    project_id: str,
    new_episode_summary: str,
) -> str | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return None
    existing = project.long_summary or ""
    if existing:
        project.long_summary = existing + "\n\n" + new_episode_summary
    else:
        project.long_summary = new_episode_summary
    await db.commit()
    await db.refresh(project)
    return project.long_summary
