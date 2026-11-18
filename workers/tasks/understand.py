from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.understand.summarize_episode")
def summarize_episode(self, run_id: str, episode_id: str):
    asyncio.run(_summarize_episode(self, run_id, episode_id))


@celery_app.task(bind=True, name="workers.tasks.understand.understand_branch_sequential")
def understand_branch_sequential(
    self,
    project_id: str,
    branch_id: str,
    episode_ids: list[str] | None = None,
    force: bool = False,
):
    asyncio.run(_understand_branch_sequential(self, project_id, branch_id, episode_ids, force))


async def _summarize_episode_with_db(db, self_task, run_id: str, episode_id: str) -> dict:
    from app.models.episode import Episode
    from app.models.episode_page import EpisodePage
    from app.models.generation_run import GenerationRun
    from app.services import understanding_service

    result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id).limit(1))
    run = result.scalar_one_or_none()
    if run:
        run.status = "running"
        await db.commit()

    try:
        result = await db.execute(select(Episode).where(Episode.id == episode_id).limit(1))
        episode = result.scalar_one_or_none()
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")

        result = await db.execute(
            select(EpisodePage).where(EpisodePage.episode_id == episode_id).order_by(EpisodePage.page_index)
        )
        pages = result.scalars().all()
        page_refs = [(page.page_index + 1, page.image_path) for page in pages]

        understanding = await understanding_service.run_multimodal_understanding(db, episode, page_refs)

        if run:
            run.status = "succeeded"
            run.finished_at = datetime.now()
            await db.commit()

        if self_task:
            self_task.update_state(
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
        return understanding

    except Exception as e:
        logger.exception("Episode understanding failed for episode %s", episode_id)
        if run:
            run.status = "failed"
            run.error = str(e)
            run.finished_at = datetime.now()
            await db.commit()
        raise


async def _summarize_episode(self, run_id: str, episode_id: str):
    from app.database import worker_session

    async with worker_session() as db:
        await _summarize_episode_with_db(db, self, run_id, episode_id)


async def _understand_branch_sequential(
    self,
    project_id: str,
    branch_id: str,
    episode_ids: list[str] | None,
    force: bool,
):
    """Sequentially understand serialized manga chapters in strict ascending Episode.number order
    so characters, items, world rules, main plotline, and pits carry forward accurately."""
    from app.database import worker_session
    from app.models.episode import Episode
    from app.services import generation_service

    async with worker_session() as db:
        stmt = select(Episode).where(
            Episode.project_id == project_id,
            Episode.branch_id == branch_id,
        )
        if episode_ids:
            stmt = stmt.where(Episode.id.in_(episode_ids))
        elif not force:
            stmt = stmt.where(Episode.status == "imported")
        stmt = stmt.order_by(Episode.number.asc())
        episodes = list((await db.execute(stmt)).scalars().all())

        total = len(episodes)
        completed = 0
        failed_ids: list[str] = []

        for ep in episodes:
            if await generation_service.has_active_run(db, ep.id, "understand"):
                continue
            run = await generation_service.create_generation_run(
                db,
                episode_id=ep.id,
                stage="understand",
                backend="openai",
                commit_message=f"Batch sequential understand ({completed + 1}/{total})",
            )
            if self:
                self.update_state(
                    state="RUNNING",
                    meta={
                        "project_id": project_id,
                        "branch_id": branch_id,
                        "current_episode_id": ep.id,
                        "current_label": ep.label or str(ep.number),
                        "completed": completed,
                        "total": total,
                    },
                )
            try:
                await _summarize_episode_with_db(db, None, str(run.id), ep.id)
                completed += 1
            except Exception:
                failed_ids.append(ep.id)
                logger.warning("Sequential understand skipped failed episode %s, continuing series", ep.id)

        if self:
            self.update_state(
                state="SUCCESS",
                meta={
                    "project_id": project_id,
                    "branch_id": branch_id,
                    "completed": completed,
                    "failed": len(failed_ids),
                    "total": total,
                },
            )
