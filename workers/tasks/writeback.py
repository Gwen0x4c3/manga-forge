from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import select

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.writeback.writeback_episode")
def writeback_episode(self, episode_id: str, project_id: str):
    asyncio.run(_writeback_episode(self, episode_id, project_id))


async def _writeback_episode_with_db(db, self_task, episode_id: str, project_id: str) -> dict:
    from app.models.episode import Episode
    from app.models.episode_memory import EpisodeMemory
    from app.models.generation_run import GenerationRun
    from app.services import understanding_service

    run = GenerationRun(
        id=str(uuid.uuid4()),
        episode_id=episode_id,
        stage="writeback",
        status="running",
    )
    db.add(run)
    await db.commit()

    try:
        result = await db.execute(select(Episode).where(Episode.id == episode_id).limit(1))
        episode = result.scalar_one_or_none()
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")

        result = await db.execute(
            select(EpisodeMemory)
            .where(
                EpisodeMemory.episode_id == episode_id,
                EpisodeMemory.type == "layout_result",
            )
            .order_by(EpisodeMemory.created_at.desc())
            .limit(1)
        )
        layout_memory = result.scalar_one_or_none()

        page_refs: list[tuple[int, str]] = []
        if layout_memory and layout_memory.content:
            for page in layout_memory.content.get("pages", []):
                image_path = page.get("image_path") or ""
                if image_path:
                    page_refs.append((page.get("page_number", len(page_refs) + 1), image_path))

        storyboard_memory = (
            await db.execute(
                select(EpisodeMemory)
                .where(
                    EpisodeMemory.episode_id == episode_id,
                    EpisodeMemory.type == "storyboard_json",
                )
                .order_by(EpisodeMemory.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        sb_content = storyboard_memory.content if (storyboard_memory and storyboard_memory.content) else None
        fallback_text = (
            "Authoritative Storyboard Script of this generated episode "
            "(page_dialogues may be left empty as it is already known):\n"
            + json.dumps(sb_content, ensure_ascii=False, indent=2)
            if sb_content
            else ""
        )

        understanding = await understanding_service.run_multimodal_understanding(
            db,
            episode,
            page_refs,
            fallback_text=fallback_text,
            target_status=None,  # keep generated episode's published status
            authoritative_storyboard=sb_content,
        )

        run.status = "succeeded"
        run.finished_at = datetime.now()
        await db.commit()

        if self_task:
            self_task.update_state(
                state="SUCCESS",
                meta={
                    "episode_id": episode_id,
                    "project_id": project_id,
                    "summary": understanding.get("summary", ""),
                    "new_pits": len(understanding.get("pit_discoveries", [])),
                    "resolved_pits": len(understanding.get("resolved_pits", [])),
                },
            )
        return understanding

    except Exception as e:
        logger.exception("Episode writeback failed")
        run.status = "failed"
        run.error = str(e)
        run.finished_at = datetime.now()
        await db.commit()
        raise


async def _writeback_episode(self, episode_id: str, project_id: str):
    from app.database import worker_session

    async with worker_session() as db:
        await _writeback_episode_with_db(db, self, episode_id, project_id)
