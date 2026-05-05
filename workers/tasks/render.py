from __future__ import annotations

import asyncio
import logging
import uuid

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="workers.tasks.render.render_panel",
    max_retries=3,
    default_retry_delay=30,
)
def render_panel(
    self,
    run_id: str,
    episode_id: str,
    panel_data: dict,
    image_backend_name: str | None = None,
    image_model: str | None = None,
    image_size: str = "1024x1024",
):
    try:
        return asyncio.run(_render_panel(self, run_id, episode_id, panel_data, image_backend_name, image_model, image_size))
    except Exception as exc:
        logger.exception("Panel render failed, retrying...")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, name="workers.tasks.render.render_episode")
def render_episode(
    self,
    run_id: str,
    episode_id: str,
    image_backend_name: str | None = None,
    image_model: str | None = None,
    image_size: str = "1024x1024",
):
    asyncio.run(_render_episode(self, run_id, episode_id, image_backend_name, image_model, image_size))


async def _render_panel(
    self,
    run_id: str,
    episode_id: str,
    panel_data: dict,
    image_backend_name: str | None,
    image_model: str | None,
    image_size: str,
):

    from app.config import settings
    from app.core.image_backend import get_image_backend
    from app.database import async_session
    from app.models.generated_image import GeneratedImage
    from app.services import storage_service

    original_backend = settings.IMAGE_BACKEND
    original_model = settings.IMAGE_MODEL
    if image_backend_name:
        settings.IMAGE_BACKEND = image_backend_name
    if image_model:
        settings.IMAGE_MODEL = image_model

    try:
        backend = get_image_backend()

        prompt = panel_data.get("prompt", "")
        negative_prompt = panel_data.get("negative_prompt")
        size_parts = image_size.split("x")
        size = (int(size_parts[0]), int(size_parts[1]))

        result = await backend.generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            size=size,
        )

        object_key = storage_service.generate_object_key(
            f"generated/{episode_id}",
            f"{panel_data.get('panel_id', 'panel')}.png",
        )
        storage_service.upload_file(
            settings.MINIO_BUCKET,
            object_key,
            result.image_data,
            content_type="image/png",
        )

        async with async_session() as db:
            gen_image = GeneratedImage(
                id=str(uuid.uuid4()),
                generation_run_id=run_id,
                episode_id=episode_id,
                panel_id=panel_data.get("panel_id"),
                image_path=object_key,
                meta={
                    "model": result.meta.get("model", ""),
                    "size": image_size,
                    "prompt": prompt,
                    "seed": result.seed,
                },
            )
            db.add(gen_image)
            await db.commit()

        return {
            "episode_id": episode_id,
            "panel_id": panel_data.get("panel_id"),
            "image_path": object_key,
            "status": "completed",
        }
    finally:
        settings.IMAGE_BACKEND = original_backend
        settings.IMAGE_MODEL = original_model


async def _render_episode(
    self,
    run_id: str,
    episode_id: str,
    image_backend_name: str | None,
    image_model: str | None,
    image_size: str,
):
    from sqlalchemy import select

    from app.database import async_session
    from app.models.episode_memory import EpisodeMemory
    from app.models.generation_run import GenerationRun

    async with async_session() as db:
        result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = "running"
            await db.commit()

        try:
            result = await db.execute(
                select(EpisodeMemory)
                .where(
                    EpisodeMemory.episode_id == episode_id,
                    EpisodeMemory.type == "storyboard_json",
                )
                .order_by(EpisodeMemory.created_at.desc())
            )
            storyboard_memory = result.scalar_one_or_none()
            if not storyboard_memory:
                raise ValueError(f"No storyboard found for episode {episode_id}")

            storyboard = storyboard_memory.content
            pages = storyboard.get("pages", [])

            all_panels = []
            for page in pages:
                for panel in page.get("panels", []):
                    all_panels.append(panel)

            total = len(all_panels)
            completed = 0

            for panel in all_panels:
                try:
                    await _render_panel(self, run_id, episode_id, panel, image_backend_name, image_model, image_size)
                    completed += 1
                    progress = int(completed / total * 100) if total > 0 else 100
                    self.update_state(
                        state="RUNNING",
                        meta={"episode_id": episode_id, "progress": progress, "completed": completed, "total": total},
                    )
                except Exception as e:
                    logger.warning(f"Failed to render panel {panel.get('panel_id')}: {e}")
                    completed += 1

            from app.services import generation_service

            await generation_service.update_episode_status(db, episode_id, "rendered")

            if run:
                run.status = "succeeded"
                await db.commit()

            self.update_state(
                state="SUCCESS",
                meta={"episode_id": episode_id, "run_id": run_id, "completed": completed, "total": total},
            )

        except Exception as e:
            logger.exception("Episode rendering failed")
            if run:
                run.status = "failed"
                run.error = str(e)
                await db.commit()
            raise
