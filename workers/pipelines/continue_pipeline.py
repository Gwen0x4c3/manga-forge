from __future__ import annotations

import asyncio

from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.pipelines.continue_pipeline.run_continue")
def run_continue(
    self,
    episode_id: str,
    branch_id: str,
    base_episode_number: int,
    tone: str = "main",
    custom_instructions: str | None = None,
    image_backend: str | None = None,
    image_model: str | None = None,
    image_size: str = "1024x1024",
):
    from app.database import async_session
    from app.services import generation_service

    async def _create_runs():
        async with async_session() as db:
            script_run = await generation_service.create_generation_run(db, episode_id=episode_id, stage="script", backend="openai")
            render_run = await generation_service.create_generation_run(db, episode_id=episode_id, stage="render", backend=image_backend or "openai")
            layout_run = await generation_service.create_generation_run(db, episode_id=episode_id, stage="layout")
            return str(script_run.id), str(render_run.id), str(layout_run.id)

    script_run_id, render_run_id, layout_run_id = asyncio.run(_create_runs())

    from workers.tasks.script_gen import _generate_script
    asyncio.run(_generate_script(
        self, script_run_id, episode_id, branch_id, base_episode_number, tone, custom_instructions,
    ))

    from workers.tasks.render import _render_episode
    asyncio.run(_render_episode(
        self, render_run_id, episode_id, image_backend, image_model, image_size,
    ))

    from workers.tasks.layout import _layout_episode
    asyncio.run(_layout_episode(
        self, layout_run_id, episode_id, None,
    ))
