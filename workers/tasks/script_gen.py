from __future__ import annotations

import json
import logging
from decimal import Decimal

from jinja2 import Template

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="workers.tasks.script_gen.generate_script")
def generate_script(
    self,
    run_id: str,
    episode_id: str,
    branch_id: str,
    base_episode_number: float,
    tone: str = "main",
    custom_instructions: str | None = None,
):
    import asyncio
    asyncio.run(_generate_script(self, run_id, episode_id, branch_id, base_episode_number, tone, custom_instructions))


def _latest_character_states(recent_episodes: list[dict]) -> list[dict]:
    """Collapse recent state changes into the latest known state per character."""
    states: dict[str, str] = {}
    for ep in recent_episodes:  # oldest → newest
        for change in ep.get("state_changes", []):
            name = change.get("character", "")
            if not name:
                continue
            after = change.get("after", "")
            attribute = change.get("attribute", "")
            entry = f"{attribute}={after}" if attribute else after
            if after:
                states[name] = f"{states[name]}; {entry}" if name in states else entry
    return [{"name": n, "description": d} for n, d in states.items()]


async def _generate_script_with_feedback(
    client,
    system_prompt: str,
    user_prompt: str,
    feedback: str | None,
):
    from app.config import settings
    from app.schemas.storyboard import Storyboard

    prompt = user_prompt
    if feedback:
        prompt += (
            "\n\n## IMPORTANT — Fix these consistency issues from your previous draft:\n"
            f"{feedback}\n"
            "Regenerate the storyboard resolving every issue listed above."
        )
    return await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        response_model=Storyboard,
        max_retries=2,
    )


async def _check_consistency(client, context: dict, storyboard_dict: dict):
    from app.config import settings
    from app.prompts.consistency_check import (
        CONSISTENCY_CHECK_SYSTEM_PROMPT,
        CONSISTENCY_CHECK_USER_TEMPLATE,
    )
    from app.schemas.consistency import ConsistencyReport

    user_prompt = CONSISTENCY_CHECK_USER_TEMPLATE.render(
        canon_rules=context["canon_rules"],
        long_summary=context["long_summary"],
        recent_episodes=context["recent_episodes"],
        character_states=_latest_character_states(context["recent_episodes"]),
        open_pits=context["active_pits"],
        storyboard_json=json.dumps(storyboard_dict, ensure_ascii=False, indent=2),
    )
    return await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": CONSISTENCY_CHECK_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_model=ConsistencyReport,
        max_retries=1,
    )


async def _generate_script(
    self,
    run_id: str,
    episode_id: str,
    branch_id: str,
    base_episode_number: float,
    tone: str,
    custom_instructions: str | None,
):
    from sqlalchemy import select
    from app.core.llm import get_llm_client
    from app.database import async_session
    from app.models.episode import Episode
    from app.models.episode_memory import EpisodeMemory
    from app.models.generation_run import GenerationRun
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
                db, episode.project_id, branch_id, Decimal(str(base_episode_number))
            )

            if run:
                # Decimals (episode numbers) are not JSON-serializable for MySQL
                run.retrieved_context = json.loads(json.dumps(context, default=str))
                await db.commit()

            user_prompt = Template(SCRIPT_GENERATE_USER_PROMPT).render(
                canon_rules=context["canon_rules"],
                long_summary=context["long_summary"],
                recent_episodes=context["recent_episodes"],
                rag_memories=context.get("rag_memories", []),
                active_pits=context["active_pits"],
                assets=context["assets"],
                episode_number=int(base_episode_number) + 1,
                tone=tone,
                custom_instructions=custom_instructions or "",
            )

            client = get_llm_client()
            storyboard = await _generate_script_with_feedback(client, SCRIPT_GENERATE_SYSTEM_PROMPT, user_prompt, None)

            # Consistency check + one auto-fix retry on critical issues
            report = await _check_consistency(client, context, storyboard.model_dump())
            critical = [i for i in report.issues if i.severity == "critical"]
            if critical:
                feedback = "\n".join(
                    f"- [{i.category}] {i.location}: {i.description}"
                    + (f" → {i.suggestion}" if i.suggestion else "")
                    for i in critical
                )
                logger.info("Consistency check found %d critical issues, regenerating", len(critical))
                storyboard = await _generate_script_with_feedback(
                    client, SCRIPT_GENERATE_SYSTEM_PROMPT, user_prompt, feedback
                )
                report = await _check_consistency(client, context, storyboard.model_dump())

            storyboard_dict = storyboard.model_dump()

            await generation_service.save_storyboard(db, episode_id, storyboard_dict)
            db.add(
                EpisodeMemory(
                    episode_id=episode_id,
                    type="consistency_report",
                    content=report.model_dump(),
                )
            )
            await db.commit()
            await generation_service.update_episode_status(db, episode_id, "scripted")

            if run:
                run.status = "succeeded"
                await db.commit()

            self.update_state(
                state="SUCCESS",
                meta={
                    "episode_id": episode_id,
                    "run_id": run_id,
                    "title": storyboard_dict.get("title", ""),
                    "consistency": {"overall": report.overall, "issue_count": len(report.issues)},
                },
            )

        except Exception as e:
            logger.exception("Script generation failed")
            if run:
                run.status = "failed"
                run.error = str(e)
                await db.commit()
            raise
