from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.writeback.writeback_episode")
def writeback_episode(self, episode_id: str, project_id: str):
    import asyncio
    asyncio.run(_writeback_episode(self, episode_id, project_id))


async def _writeback_episode(self, episode_id: str, project_id: str):
    from app.database import async_session
    from app.models.episode import Episode
    from app.models.episode_memory import EpisodeMemory
    from app.models.generation_run import GenerationRun
    from app.services import understanding_service

    async with async_session() as db:
        run = GenerationRun(
            id=str(uuid.uuid4()),
            episode_id=episode_id,
            stage="writeback",
            status="running",
        )
        db.add(run)
        await db.commit()

        try:
            result = await db.execute(select(Episode).where(Episode.id == episode_id))
            episode = result.scalar_one_or_none()
            if not episode:
                raise ValueError(f"Episode {episode_id} not found")

            # Prefer understanding the actually rendered pages (multimodal);
            # fall back to the storyboard text when images are unavailable.
            result = await db.execute(
                select(EpisodeMemory).where(
                    EpisodeMemory.episode_id == episode_id,
                    EpisodeMemory.type == "layout_result",
                ).order_by(EpisodeMemory.created_at.desc())
            )
            layout_memory = result.scalar_one_or_none()

            page_refs: list[tuple[int, str]] = []
            if layout_memory and layout_memory.content:
                for page in layout_memory.content.get("pages", []):
                    image_path = page.get("image_path") or ""
                    if image_path:
                        page_refs.append((page.get("page_number", len(page_refs) + 1), image_path))

            fallback_text = ""
            if not page_refs:
                result = await db.execute(
                    select(EpisodeMemory).where(
                        EpisodeMemory.episode_id == episode_id,
                        EpisodeMemory.type == "storyboard_json",
                    ).order_by(EpisodeMemory.created_at.desc())
                )
                storyboard_memory = result.scalar_one_or_none()
                if storyboard_memory and storyboard_memory.content:
                    fallback_text = json.dumps(storyboard_memory.content, ensure_ascii=False, indent=2)

            understanding = await understanding_service.run_multimodal_understanding(
                db,
                episode,
                page_refs,
                fallback_text=fallback_text,
                target_status=None,  # keep the generated episode's rendered status
            )

            run.status = "succeeded"
            await db.commit()

            self.update_state(
                state="SUCCESS",
                meta={
                    "episode_id": episode_id,
                    "project_id": project_id,
                    "summary": understanding.get("summary", ""),
                    "new_pits": len(understanding.get("pit_discoveries", [])),
                    "resolved_pits": len(understanding.get("resolved_pits", [])),
                },
            )

        except Exception as e:
            logger.exception("Episode writeback failed")
            run.status = "failed"
            run.error = str(e)
            await db.commit()
            raise
