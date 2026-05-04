from __future__ import annotations

import json
import logging

from jinja2 import Template

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.script_gen.generate_script")
def generate_script(
    self,
    run_id: str,
    episode_id: str,
    branch_id: str,
    base_episode_number: int,
    tone: str = "main",
    custom_instructions: str | None = None,
):
    import asyncio
    asyncio.run(_generate_script(self, run_id, episode_id, branch_id, base_episode_number, tone, custom_instructions))


async def _generate_script(
    self,
    run_id: str,
    episode_id: str,
    branch_id: str,
    base_episode_number: int,
    tone: str,
    custom_instructions: str | None,
):
    from sqlalchemy import select
    from app.config import settings
    from app.core.llm import get_llm_client
    from app.database import async_session
    from app.models.episode import Episode
    from app.models.generation_run import GenerationRun
    from app.schemas.storyboard import Storyboard
    from app.prompts.script_generate import SCRIPT_GENERATE_SYSTEM_PROMPT, SCRIPT_GENERATE_USER_PROMPT
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

            context = await memory_service.build_context_for_generation(
                db, episode.project_id, branch_id, base_episode_number
            )

            if run:
                run.retrieved_context = context
                await db.commit()

            user_prompt = Template(SCRIPT_GENERATE_USER_PROMPT).render(
                canon_rules=context["canon_rules"],
                long_summary=context["long_summary"],
                recent_episodes=context["recent_episodes"],
                rag_memories=[],
                active_pits=context["active_pits"],
                assets=context["assets"],
                episode_number=base_episode_number + 1,
                tone=tone,
                custom_instructions=custom_instructions or "",
            )

            client = get_llm_client()
            storyboard = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SCRIPT_GENERATE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=Storyboard,
                max_retries=2,
            )

            storyboard_dict = storyboard.model_dump()

            await generation_service.save_storyboard(db, episode_id, storyboard_dict)
            await generation_service.update_episode_status(db, episode_id, "scripted")

            if run:
                run.status = "succeeded"
                await db.commit()

            self.update_state(state="SUCCESS", meta={"episode_id": episode_id, "run_id": run_id})

        except Exception as e:
            logger.exception("Script generation failed")
            if run:
                run.status = "failed"
                run.error = str(e)
                await db.commit()
            self.update_state(state="FAILURE", meta={"error": str(e)})
            raise
