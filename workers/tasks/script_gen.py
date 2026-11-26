from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from decimal import Decimal

from jinja2 import Template
from sqlalchemy import delete, select

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
    context_profile: str | None = None,
):
    asyncio.run(
        _generate_script(
            self,
            run_id,
            episode_id,
            branch_id,
            base_episode_number,
            tone,
            custom_instructions,
            context_profile,
        )
    )


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
            "Regenerate the complete Storyboard resolving every issue listed above."
        )
    return await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        response_model=Storyboard,
        max_tokens=settings.OPENAI_MAX_TOKENS,
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
        story_bible=context.get("story_bible") or {},
        canon_rules=context.get("canon_rules", ""),
        long_summary=context.get("long_summary", ""),
        previous_bridge=context.get("previous_bridge"),
        recent_episodes=context.get("recent_episodes", []),
        character_states=context.get("character_dossier", []),
        unavailable_characters=context.get("unavailable_characters", []),
        world_assets=context.get("world_assets", []),
        open_pits=context.get("active_pits", []),
        storyboard_json=json.dumps(storyboard_dict, ensure_ascii=False, indent=2),
    )
    return await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": CONSISTENCY_CHECK_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_model=ConsistencyReport,
        max_tokens=settings.OPENAI_MAX_TOKENS,
        max_retries=1,
    )


async def _generate_script_with_db(
    db,
    self_task,
    run_id: str,
    episode_id: str,
    branch_id: str,
    base_episode_number: float,
    tone: str,
    custom_instructions: str | None,
    context_profile: str | None = None,
) -> dict:
    from app.config import settings
    from app.core.llm import get_llm_client
    from app.models.episode import Episode
    from app.models.episode_memory import EpisodeMemory
    from app.models.generation_run import GenerationRun
    from app.prompts.script_generate import SCRIPT_GENERATE_SYSTEM_PROMPT, SCRIPT_GENERATE_USER_PROMPT
    from app.services import generation_service, memory_service

    result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id).limit(1))
    run = result.scalar_one_or_none()
    if run:
        run.status = "running"
        run.model = settings.OPENAI_MODEL
        await db.commit()

    try:
        result = await db.execute(select(Episode).where(Episode.id == episode_id).limit(1))
        episode = result.scalar_one_or_none()
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")

        # Ensure base_episode_number never exceeds episode.number - epsilon when generating for an episode
        cutoff = Decimal(str(base_episode_number))
        if episode.number and cutoff >= episode.number and episode.source == "generated":
            cutoff = episode.number - Decimal("0.01")

        context = await memory_service.build_context_for_generation(
            db,
            episode.project_id,
            branch_id,
            cutoff,
            custom_instructions=custom_instructions,
            context_profile=context_profile,
        )

        target_ep_label = episode.label or str(
            int(episode.number) if episode.number == int(episode.number) else episode.number
        )

        user_prompt = Template(SCRIPT_GENERATE_USER_PROMPT).render(
            project_title=context.get("project_title", ""),
            language_label=context.get("language_label", "简体中文"),
            art_style=context.get("art_style", ""),
            story_bible=context.get("story_bible") or {},
            canon_rules=context["canon_rules"],
            long_summary=context["long_summary"],
            previous_bridge=context.get("previous_bridge"),
            recent_episodes=context["recent_episodes"],
            character_dossier=context.get("character_dossier", []),
            unavailable_characters=context.get("unavailable_characters", []),
            world_assets=context.get("world_assets", []),
            rag_memories=context.get("rag_memories", []),
            active_pits=context["active_pits"],
            assets=context["assets"],
            episode_number=target_ep_label,
            tone=tone,
            custom_instructions=custom_instructions or "",
        )

        if run:
            run.retrieved_context = json.loads(json.dumps(context, default=str))
            run.prompt = user_prompt[:16000]
            await db.commit()

        from app.core.telemetry import usage_context

        client = get_llm_client()
        with usage_context(
            project_id=episode.project_id,
            episode_id=episode_id,
            generation_run_id=run_id,
            operation="script",
        ):
            storyboard = await _generate_script_with_feedback(client, SCRIPT_GENERATE_SYSTEM_PROMPT, user_prompt, None)

        # Consistency check + one auto-fix retry on critical issues
        with usage_context(
            project_id=episode.project_id,
            episode_id=episode_id,
            generation_run_id=run_id,
            operation="consistency_check",
        ):
            report = await _check_consistency(client, context, storyboard.model_dump())
        critical = [i for i in report.issues if i.severity == "critical"]
        if critical:
            feedback = "\n".join(
                f"- [{i.category}] {i.location}: {i.description}" + (f" → {i.suggestion}" if i.suggestion else "")
                for i in critical
            )
            logger.info("Consistency check found %d critical issues, regenerating", len(critical))
            with usage_context(
                project_id=episode.project_id,
                episode_id=episode_id,
                generation_run_id=run_id,
                operation="script_retry",
            ):
                storyboard = await _generate_script_with_feedback(
                    client, SCRIPT_GENERATE_SYSTEM_PROMPT, user_prompt, feedback
                )
            with usage_context(
                project_id=episode.project_id,
                episode_id=episode_id,
                generation_run_id=run_id,
                operation="consistency_check",
            ):
                report = await _check_consistency(client, context, storyboard.model_dump())

        storyboard_dict = storyboard.model_dump()

        await generation_service.save_storyboard(db, episode_id, storyboard_dict)
        await db.execute(
            delete(EpisodeMemory).where(
                EpisodeMemory.episode_id == episode_id,
                EpisodeMemory.type == "consistency_report",
            )
        )
        db.add(
            EpisodeMemory(
                id=str(uuid.uuid4()),
                episode_id=episode_id,
                type="consistency_report",
                content=report.model_dump(),
            )
        )

        # Update episode title if it was empty or auto-placeholder
        new_title = (storyboard_dict.get("title") or "").strip()
        if new_title and (not episode.title or episode.title.startswith("Episode ")):
            episode.title = new_title[:255]

        episode.status = "scripted"
        if run:
            run.status = "succeeded"
            run.finished_at = datetime.now()
        await db.commit()

        if self_task:
            self_task.update_state(
                state="SUCCESS",
                meta={
                    "episode_id": episode_id,
                    "run_id": run_id,
                    "title": storyboard_dict.get("title", ""),
                    "consistency": {"overall": report.overall, "issue_count": len(report.issues)},
                },
            )
        return storyboard_dict

    except Exception as e:
        logger.exception("Script generation failed")
        if run:
            run.status = "failed"
            run.error = str(e)
            run.finished_at = datetime.now()
            await db.commit()
        raise


async def _generate_script(
    self,
    run_id: str,
    episode_id: str,
    branch_id: str,
    base_episode_number: float,
    tone: str,
    custom_instructions: str | None,
    context_profile: str | None = None,
):
    from app.database import worker_session

    async with worker_session() as db:
        await _generate_script_with_db(
            db,
            self,
            run_id,
            episode_id,
            branch_id,
            base_episode_number,
            tone,
            custom_instructions,
            context_profile=context_profile,
        )
