from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.understand.summarize_episode")
def summarize_episode(self, run_id: str, episode_id: str, concurrency: int | None = None):
    asyncio.run(_summarize_episode(self, run_id, episode_id, concurrency=concurrency))


@celery_app.task(bind=True, name="workers.tasks.understand.understand_branch_sequential")
def understand_branch_sequential(
    self,
    project_id: str,
    branch_id: str,
    episode_ids: list[str] | None = None,
    force: bool = False,
    concurrency: int | None = None,
):
    asyncio.run(
        _understand_branch_sequential(self, project_id, branch_id, episode_ids, force, concurrency=concurrency)
    )


async def _summarize_episode_with_db(
    db,
    self_task,
    run_id: str,
    episode_id: str,
    *,
    concurrency: int | None = None,
) -> dict:
    from app.models.episode import Episode
    from app.models.episode_page import EpisodePage
    from app.models.generation_run import GenerationRun
    from app.services import understanding_service

    result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id).limit(1))
    run = result.scalar_one_or_none()
    if run:
        run.status = "running"
        params = dict(run.params or {})
        if concurrency is not None:
            params["concurrency"] = int(concurrency)
        params["progress"] = {"phase": "prepare", "label": "准备启动多模态理解", "episode_pct": 2}
        run.params = params
        await db.commit()

    async def _on_progress(prog: dict) -> None:
        if not run:
            return
        params = dict(run.params or {})
        params["progress"] = prog
        if prog.get("concurrency") is not None:
            params["concurrency"] = int(prog["concurrency"])
        run.params = params
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

        understanding = await understanding_service.run_multimodal_understanding(
            db,
            episode,
            page_refs,
            concurrency=concurrency,
            progress_callback=_on_progress,
        )

        if run:
            run.status = "succeeded"
            run.finished_at = datetime.now()
            params = dict(run.params or {})
            params["progress"] = {"phase": "done", "label": "本话理解完成", "episode_pct": 100}
            run.params = params
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


async def _summarize_episode(self, run_id: str, episode_id: str, concurrency: int | None = None):
    from app.database import worker_session

    async with worker_session() as db:
        await _summarize_episode_with_db(db, self, run_id, episode_id, concurrency=concurrency)


async def _understand_branch_sequential(
    self,
    project_id: str,
    branch_id: str,
    episode_ids: list[str] | None,
    force: bool,
    *,
    concurrency: int | None = None,
):
    """Sequentially understand serialized manga chapters in strict ascending Episode.number order
    so characters, items, world rules, main plotline, and pits carry forward accurately."""
    from app.core.llm import get_active_llm_config
    from app.database import worker_session
    from app.models.episode import Episode
    from app.services import generation_service

    vision_cfg = get_active_llm_config("vision_llm")
    eff_conc = max(1, min(8, int(concurrency or getattr(vision_cfg, "concurrency", 1) or 1)))

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

        for ep_idx, ep in enumerate(episodes):
            if await generation_service.has_active_run(db, ep.id, "understand"):
                continue
            remaining_ids = [e.id for e in episodes[ep_idx + 1 :]]
            run = await generation_service.create_generation_run(
                db,
                episode_id=ep.id,
                stage="understand",
                backend=vision_cfg.provider_key,
                model=vision_cfg.model,
                params={
                    "concurrency": eff_conc,
                    "batch": {
                        "index": completed + 1,
                        "completed": completed,
                        "failed": len(failed_ids),
                        "total": total,
                        "queued_episode_ids": remaining_ids,
                    },
                    "progress": {"phase": "prepare", "label": "准备启动本话理解", "episode_pct": 2},
                },
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
                        "concurrency": eff_conc,
                    },
                )
            try:
                await _summarize_episode_with_db(db, None, str(run.id), ep.id, concurrency=eff_conc)
                completed += 1
                if completed % 10 == 0:
                    try:
                        from app.services import memory_service

                        stats = await memory_service.consolidate_project_memory(db, project_id)
                        logger.info("Auto-consolidated project %s after %d episodes: %s", project_id, completed, stats)
                    except Exception:
                        logger.warning("Periodic memory consolidation failed after episode %s", ep.id, exc_info=True)
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
                    "concurrency": eff_conc,
                },
            )
