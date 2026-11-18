from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select

from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.pipelines.continue_pipeline.run_continue")
def run_continue(
    self,
    run_id: str,
    episode_id: str,
    branch_id: str,
    base_episode_number: float,
    tone: str = "main",
    custom_instructions: str | None = None,
    image_backend: str | None = None,
    image_model: str | None = None,
    image_size: str = "1024x1024",
):
    asyncio.run(
        _run_continue(
            self,
            run_id,
            episode_id,
            branch_id,
            base_episode_number,
            tone,
            custom_instructions,
            image_backend,
            image_model,
            image_size,
        )
    )


async def _run_continue(
    self,
    run_id: str,
    episode_id: str,
    branch_id: str,
    base_episode_number: float,
    tone: str,
    custom_instructions: str | None,
    image_backend: str | None,
    image_model: str | None,
    image_size: str,
):
    """Execute script -> consistency check -> render -> layout -> writeback in a single event loop."""
    from app.config import settings
    from app.database import worker_session
    from app.models.episode import Episode
    from app.models.generation_run import GenerationRun
    from app.services import generation_service

    from workers.tasks.layout import _layout_episode_with_db
    from workers.tasks.render import _render_episode_with_db
    from workers.tasks.script_gen import _generate_script_with_db
    from workers.tasks.writeback import _writeback_episode_with_db

    async with worker_session() as db:
        continue_run = await db.get(GenerationRun, run_id)
        if continue_run:
            continue_run.status = "running"
            await db.commit()

        try:
            episode = (await db.execute(select(Episode).where(Episode.id == episode_id).limit(1))).scalar_one()
            project_id = str(episode.project_id)

            script_run = await generation_service.create_generation_run(
                db, episode_id=episode_id, stage="script", backend="openai", model=settings.OPENAI_MODEL
            )
            render_run = await generation_service.create_generation_run(
                db,
                episode_id=episode_id,
                stage="render",
                backend=image_backend or settings.IMAGE_BACKEND,
                model=image_model or settings.IMAGE_MODEL,
            )
            layout_run = await generation_service.create_generation_run(db, episode_id=episode_id, stage="layout")

            await _generate_script_with_db(
                db, self, str(script_run.id), episode_id, branch_id, base_episode_number, tone, custom_instructions
            )
            await _render_episode_with_db(
                db, self, str(render_run.id), episode_id, image_backend, image_model, image_size
            )
            # Pass trigger_writeback=False because we run writeback inline right below!
            await _layout_episode_with_db(db, self, str(layout_run.id), episode_id, None, trigger_writeback=False)
            await _writeback_episode_with_db(db, self, episode_id, project_id)

            continue_run = await db.get(GenerationRun, run_id)
            if continue_run:
                continue_run.status = "succeeded"
                continue_run.finished_at = datetime.now()
                await db.commit()

        except Exception as exc:
            continue_run = await db.get(GenerationRun, run_id)
            if continue_run:
                continue_run.status = "failed"
                continue_run.error = str(exc)
                continue_run.finished_at = datetime.now()
                await db.commit()
            raise
