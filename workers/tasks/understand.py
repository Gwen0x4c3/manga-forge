from __future__ import annotations

import logging

from sqlalchemy import select

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.understand.summarize_episode")
def summarize_episode(self, run_id: str, episode_id: str):
    import asyncio
    asyncio.run(_summarize_episode(self, run_id, episode_id))


async def _summarize_episode(self, run_id: str, episode_id: str):
    from app.database import async_session
    from app.models.episode import Episode
    from app.models.episode_page import EpisodePage
    from app.models.generation_run import GenerationRun
    from app.services import understanding_service

    async with async_session() as db:
        result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = "running"
            await db.commit()

        try:
            result = await db.execute(select(Episode).where(Episode.id == episode_id))
            episode = result.scalar_one_or_none()
            if not episode:
                raise ValueError(f"Episode {episode_id} not found")

            result = await db.execute(
                select(EpisodePage).where(EpisodePage.episode_id == episode_id).order_by(EpisodePage.page_index)
            )
            pages = result.scalars().all()
            page_refs = [(page.page_index + 1, page.image_path) for page in pages]

            understanding = await understanding_service.run_multimodal_understanding(
                db, episode, page_refs
            )

            if run:
                run.status = "succeeded"
                await db.commit()

            self.update_state(
                state="SUCCESS",
                meta={
                    "episode_id": episode_id,
                    "run_id": run_id,
                    "summary": understanding.get("summary", ""),
                    "characters": [c.get("name") for c in understanding.get("characters", [])],
                    "new_pits": len(understanding.get("pit_discoveries", [])),
                    "resolved_pits": len(understanding.get("resolved_pits", [])),
                },
            )

        except Exception as e:
            logger.exception("Episode understanding failed")
            if run:
                run.status = "failed"
                run.error = str(e)
                await db.commit()
            raise
