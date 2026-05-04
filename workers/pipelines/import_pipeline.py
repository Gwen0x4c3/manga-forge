from __future__ import annotations

from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.pipelines.import_pipeline.run_import")
def run_import(self, project_id: str, episode_ids: list[str]):
    from workers.tasks.understand import summarize_episode
    for episode_id in episode_ids:
        summarize_episode.delay(episode_id=episode_id)
