from __future__ import annotations

import logging

from jinja2 import Template

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.writeback.writeback_episode")
def writeback_episode(self, episode_id: str, project_id: str):
    import asyncio
    asyncio.run(_writeback_episode(self, episode_id, project_id))


async def _writeback_episode(self, episode_id: str, project_id: str):
    from sqlalchemy import select
    from app.config import settings
    from app.core.llm import get_llm_client
    from app.database import async_session
    from app.models.episode import Episode
    from app.models.episode_memory import EpisodeMemory
    from app.models.generation_run import GenerationRun
    from app.models.project import Project
    from app.schemas.understanding import EpisodeUnderstanding
    from app.prompts.summarize import SUMMARIZE_SYSTEM_PROMPT, SUMMARIZE_USER_PROMPT
    from app.services import generation_service, memory_service

    async with async_session() as db:
        run = GenerationRun(
            id=str(__import__("uuid").uuid4()),
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

            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()

            result = await db.execute(
                select(EpisodeMemory).where(
                    EpisodeMemory.episode_id == episode_id,
                    EpisodeMemory.type == "storyboard_json",
                ).order_by(EpisodeMemory.created_at.desc())
            )
            storyboard_memory = result.scalar_one_or_none()
            storyboard_content = storyboard_memory.content if storyboard_memory else {}

            result = await db.execute(
                select(EpisodeMemory).where(
                    EpisodeMemory.episode_id == episode_id,
                    EpisodeMemory.type == "layout_result",
                ).order_by(EpisodeMemory.created_at.desc())
            )
            layout_memory = result.scalar_one_or_none()

            page_descriptions = []
            if layout_memory and layout_memory.content:
                for page in layout_memory.content.get("pages", []):
                    page_descriptions.append({
                        "page_number": page.get("page_number", 1),
                        "panels": [{"description": f"Page {page.get('page_number', 1)} image at {page.get('image_path', '')}"}],
                    })

            if storyboard_content:
                for page in storyboard_content.get("pages", []):
                    for panel in page.get("panels", []):
                        for pd in page_descriptions:
                            if pd["page_number"] == page.get("page_number", 1):
                                dialogue_texts = []
                                for d in panel.get("dialogue", []):
                                    dialogue_texts.append(f"{d.get('speaker', '')}: {d.get('text', '')}")
                                if dialogue_texts:
                                    pd["panels"].append({"description": panel.get("description", ""), "ocr_text": "\n".join(dialogue_texts)})

            storyboard_text = ""
            if storyboard_content:
                import json
                storyboard_text = json.dumps(storyboard_content, ensure_ascii=False, indent=2)

            previous_summary = ""
            if project and project.long_summary:
                previous_summary = project.long_summary[-2000:]

            user_prompt = Template(SUMMARIZE_USER_PROMPT).render(
                episode_number=episode.number,
                episode_title=episode.title or "",
                previous_summary=previous_summary,
                ocr_text=storyboard_text,
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
                db, project_id, episode_id, episode.number, understanding_dict
            )

            summary_text = understanding_dict.get("summary", "")
            if summary_text and project:
                await memory_service.update_long_summary(db, project.id, summary_text)

            if understanding_dict.get("new_assets"):
                await generation_service.auto_discover_assets(
                    db, project_id, episode_id, understanding_dict["new_assets"]
                )

            if understanding_dict.get("pit_discoveries"):
                await generation_service.auto_discover_pits(
                    db, project_id, episode_id, understanding_dict["pit_discoveries"]
                )

            run.status = "succeeded"
            await db.commit()

            self.update_state(state="SUCCESS", meta={"episode_id": episode_id, "project_id": project_id})

        except Exception as e:
            logger.exception("Episode writeback failed")
            run.status = "failed"
            run.error = str(e)
            await db.commit()
            raise
