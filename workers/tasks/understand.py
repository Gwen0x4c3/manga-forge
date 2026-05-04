from __future__ import annotations

import json
import logging

from jinja2 import Template

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.understand.summarize_episode")
def summarize_episode(self, run_id: str, episode_id: str):
    import asyncio
    asyncio.run(_summarize_episode(self, run_id, episode_id))


async def _summarize_episode(self, run_id: str, episode_id: str):
    from sqlalchemy import select
    from app.config import settings
    from app.core.llm import get_llm_client
    from app.database import async_session
    from app.models.episode import Episode
    from app.models.episode_memory import EpisodeMemory
    from app.models.episode_page import EpisodePage
    from app.models.generation_run import GenerationRun
    from app.models.project import Project
    from app.schemas.understanding import EpisodeUnderstanding
    from app.prompts.summarize import SUMMARIZE_SYSTEM_PROMPT, SUMMARIZE_USER_PROMPT
    from app.services import generation_service, memory_service

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

            result = await db.execute(select(Project).where(Project.id == episode.project_id))
            project = result.scalar_one_or_none()

            result = await db.execute(
                select(EpisodeMemory).where(
                    EpisodeMemory.episode_id == episode_id,
                    EpisodeMemory.type == "ocr_dump",
                )
            )
            ocr_memory = result.scalar_one_or_none()
            ocr_text = ocr_memory.content.get("text", "") if ocr_memory else ""

            result = await db.execute(
                select(EpisodePage).where(EpisodePage.episode_id == episode_id).order_by(EpisodePage.page_index)
            )
            pages = result.scalars().all()

            page_descriptions = []
            for page in pages:
                page_descriptions.append({
                    "page_number": page.page_index + 1,
                    "panels": [{"description": f"Page {page.page_index + 1} image at {page.image_path}"}],
                })

            previous_summary = ""
            if project and project.long_summary:
                previous_summary = project.long_summary[-2000:]

            user_prompt = Template(SUMMARIZE_USER_PROMPT).render(
                episode_number=episode.number,
                episode_title=episode.title or "",
                previous_summary=previous_summary,
                ocr_text=ocr_text,
                page_descriptions=page_descriptions,
                raw_text="",
            )

            client = get_llm_client()
            understanding = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=EpisodeUnderstanding,
                max_retries=2,
            )

            understanding_dict = understanding.model_dump()

            await generation_service.save_episode_understanding(db, episode_id, understanding_dict)

            await memory_service.vectorize_and_store_episode_memory(
                db, episode.project_id, episode_id, episode.number, understanding_dict
            )

            summary_text = understanding_dict.get("summary", "")
            if summary_text and project:
                await memory_service.update_long_summary(db, project.id, summary_text)

            await generation_service.update_episode_status(db, episode_id, "understood")

            if run:
                run.status = "succeeded"
                await db.commit()

            self.update_state(state="SUCCESS", meta={"episode_id": episode_id, "run_id": run_id})

        except Exception as e:
            logger.exception("Episode understanding failed")
            if run:
                run.status = "failed"
                run.error = str(e)
                await db.commit()
            self.update_state(state="FAILURE", meta={"error": str(e)})
            raise
