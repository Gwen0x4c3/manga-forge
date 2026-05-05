from __future__ import annotations

import asyncio
import logging
import uuid

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.layout.layout_episode")
def layout_episode(self, run_id: str, episode_id: str, template_override: dict | None = None):
    asyncio.run(_layout_episode(self, run_id, episode_id, template_override))


async def _layout_episode(self, run_id: str, episode_id: str, template_override: dict | None):
    from sqlalchemy import select
    from app.config import settings
    from app.core.layout_engine import LayoutEngine, PanelImage
    from app.database import async_session
    from app.models.episode import Episode
    from app.models.episode_memory import EpisodeMemory
    from app.models.generated_image import GeneratedImage
    from app.models.generation_run import GenerationRun
    from app.services import storage_service, generation_service

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
            project_id = episode.project_id
            result = await db.execute(
                select(EpisodeMemory)
                .where(EpisodeMemory.episode_id == episode_id, EpisodeMemory.type == "storyboard_json")
                .order_by(EpisodeMemory.created_at.desc())
            )
            storyboard_memory = result.scalar_one_or_none()
            if not storyboard_memory:
                raise ValueError(f"No storyboard found for episode {episode_id}")

            storyboard = storyboard_memory.content
            pages = storyboard.get("pages", [])

            result = await db.execute(
                select(GeneratedImage).where(GeneratedImage.episode_id == episode_id)
            )
            generated_images = result.scalars().all()

            image_map: dict[str, str] = {}
            for gi in generated_images:
                if gi.panel_id:
                    image_map[gi.panel_id] = gi.image_path

            engine = LayoutEngine()
            composed_pages_data: list[dict] = []

            for page_data in pages:
                page_number = page_data.get("page_number", 1)
                layout = page_data.get("layout", "2x2")
                if template_override and page_number in template_override:
                    layout = template_override[page_number]

                panels = page_data.get("panels", [])
                panel_images: list[PanelImage] = []

                for panel in panels:
                    panel_id = panel.get("panel_id", "")
                    image_path = image_map.get(panel_id)

                    if image_path:
                        client = storage_service.get_minio_client()
                        response = client.get_object(settings.MINIO_BUCKET, image_path)
                        try:
                            image_data = response.read()
                        finally:
                            response.close()
                            response.release_conn()
                    else:
                        from PIL import Image as PILImage, ImageDraw
                        import io

                        img = PILImage.new("RGB", (1024, 1024), color=(200, 200, 200))
                        draw = ImageDraw.Draw(img)
                        draw.text((10, 10), f"Missing: {panel_id}", fill=(0, 0, 0))
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        image_data = buf.getvalue()

                    dialogues: list[dict] = []
                    for d in panel.get("dialogue", []):
                        dialogues.append({
                            "speaker": d.get("speaker", ""),
                            "text": d.get("text", ""),
                            "type": d.get("type", "speech"),
                            "speaker_position": d.get("speaker_position", "center"),
                        })

                    face_zones = panel.get("face_zones", [])

                    panel_images.append(PanelImage(
                        image_data=image_data,
                        panel_id=panel_id,
                        dialogues=dialogues,
                        position_hint=panel.get("position_hint", "center"),
                        face_zones=face_zones,
                    ))

                composed = engine.compose_page(layout, panel_images, page_number)

                object_key = storage_service.generate_object_key(
                    f"layout/{episode_id}", f"page_{page_number}.png"
                )
                storage_service.upload_file(
                    settings.MINIO_BUCKET, object_key, composed.image_data, content_type="image/png"
                )

                composed_pages_data.append({
                    "page_number": page_number,
                    "layout": layout,
                    "image_path": object_key,
                })

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
                await db.commit()

            self.update_state(
                state="SUCCESS",
                meta={"episode_id": episode_id, "run_id": run_id, "page_count": len(composed_pages_data)},
            )

            from workers.pipelines.writeback_pipeline import run_writeback
            run_writeback.delay(episode_id=episode_id, project_id=project_id)

        except Exception as e:
            logger.exception("Episode layout failed")
            if run:
                run.status = "failed"
                run.error = str(e)
                await db.commit()
            raise
