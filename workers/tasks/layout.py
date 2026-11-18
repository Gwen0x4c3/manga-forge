from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import datetime

from sqlalchemy import delete, select

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.layout.layout_episode")
def layout_episode(
    self,
    run_id: str,
    episode_id: str,
    template_override: dict | None = None,
    trigger_writeback: bool = True,
):
    asyncio.run(_layout_episode(self, run_id, episode_id, template_override, trigger_writeback=trigger_writeback))


async def _layout_episode_with_db(
    db,
    self_task,
    run_id: str,
    episode_id: str,
    template_override: dict | None,
    trigger_writeback: bool = True,
) -> list[dict]:
    from app.config import settings
    from app.core.layout_engine import LayoutEngine, PanelImage
    from app.models.episode import Episode
    from app.models.episode_memory import EpisodeMemory
    from app.models.generation_run import GenerationRun
    from app.services import generation_service, storage_service
    from PIL import Image as PILImage
    from PIL import ImageDraw

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
        project_id = episode.project_id

        result = await db.execute(
            select(EpisodeMemory)
            .where(EpisodeMemory.episode_id == episode_id, EpisodeMemory.type == "storyboard_json")
            .order_by(EpisodeMemory.created_at.desc())
            .limit(1)
        )
        storyboard_memory = result.scalar_one_or_none()
        if not storyboard_memory:
            raise ValueError(f"No storyboard found for episode {episode_id}")

        storyboard = storyboard_memory.content
        pages = storyboard.get("pages", [])

        generated_images = await generation_service.get_generated_images(db, episode_id)
        image_map: dict[str, str] = {gi.panel_id: gi.image_path for gi in generated_images if gi.panel_id}

        engine = LayoutEngine()
        composed_pages_data: list[dict] = []

        for page_data in pages:
            page_number = page_data.get("page_number", 1)
            layout = page_data.get("layout", "2x2")
            if template_override:
                override = template_override.get(page_number) or template_override.get(str(page_number))
                if override:
                    layout = override

            panels = page_data.get("panels", [])
            panel_images: list[PanelImage] = []

            for panel in panels:
                panel_id = panel.get("panel_id", "")
                image_path = image_map.get(panel_id)
                image_data = storage_service.get_object_bytes(settings.MINIO_BUCKET, image_path) if image_path else None
                if not image_data:
                    img = PILImage.new("RGB", (1024, 1024), color=(235, 236, 240))
                    draw = ImageDraw.Draw(img)
                    draw.rectangle([8, 8, 1016, 1016], outline=(80, 80, 90), width=4)
                    draw.text((28, 28), f"Missing Panel: {panel_id}", fill=(40, 40, 50))
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    image_data = buf.getvalue()

                dialogues = [
                    {
                        "speaker": d.get("speaker", ""),
                        "text": d.get("text", ""),
                        "type": d.get("type", "speech"),
                        "speaker_position": d.get("speaker_position", ""),
                    }
                    for d in panel.get("dialogue", [])
                ]

                panel_images.append(
                    PanelImage(
                        image_data=image_data,
                        panel_id=panel_id,
                        dialogues=dialogues,
                        position_hint=panel.get("position_hint", "center"),
                        face_zones=panel.get("face_zones", []),
                    )
                )

            composed = engine.compose_page(layout, panel_images, page_number)

            object_key = storage_service.generate_object_key(f"layout/{episode_id}", f"page_{page_number}.png")
            storage_service.upload_file(
                settings.MINIO_BUCKET, object_key, composed.image_data, content_type="image/png"
            )

            composed_pages_data.append(
                {
                    "page_number": page_number,
                    "layout": layout,
                    "image_path": object_key,
                }
            )

        await db.execute(
            delete(EpisodeMemory).where(
                EpisodeMemory.episode_id == episode_id,
                EpisodeMemory.type == "layout_result",
            )
        )
        layout_memory = EpisodeMemory(
            id=str(uuid.uuid4()),
            episode_id=episode_id,
            type="layout_result",
            content={"pages": composed_pages_data},
        )
        db.add(layout_memory)
        await db.commit()

        await generation_service.update_episode_status(db, episode_id, "published")

        if run:
            run.status = "succeeded"
            run.finished_at = datetime.now()
            await db.commit()

        if self_task:
            self_task.update_state(
                state="SUCCESS",
                meta={"episode_id": episode_id, "run_id": run_id, "page_count": len(composed_pages_data)},
            )

        # Trigger standalone writeback ONLY when requested AND episode has not been understood yet
        if trigger_writeback:
            has_summary = (
                await db.execute(
                    select(EpisodeMemory.id)
                    .where(EpisodeMemory.episode_id == episode_id, EpisodeMemory.type == "summary")
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not has_summary:
                try:
                    from workers.pipelines.writeback_pipeline import run_writeback

                    run_writeback.delay(episode_id=episode_id, project_id=project_id)
                except Exception:
                    logger.debug("Celery broker unavailable for async writeback dispatch", exc_info=True)

        return composed_pages_data

    except Exception as e:
        logger.exception("Episode layout failed")
        if run:
            run.status = "failed"
            run.error = str(e)
            run.finished_at = datetime.now()
            await db.commit()
        raise


async def _layout_episode(
    self,
    run_id: str,
    episode_id: str,
    template_override: dict | None,
    trigger_writeback: bool = True,
):
    from app.database import worker_session

    async with worker_session() as db:
        await _layout_episode_with_db(
            db, self, run_id, episode_id, template_override, trigger_writeback=trigger_writeback
        )
