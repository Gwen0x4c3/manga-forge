from __future__ import annotations

from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.pipelines.generate_pipeline.run_generation")
def run_generation(
    self,
    episode_id: str,
    branch_id: str,
    base_episode_number: float,
    tone: str = "main",
    custom_instructions: str | None = None,
):
    from workers.tasks.script_gen import generate_script
    generate_script.delay(
        episode_id=episode_id,
        branch_id=branch_id,
        base_episode_number=base_episode_number,
        tone=tone,
        custom_instructions=custom_instructions,
    )
