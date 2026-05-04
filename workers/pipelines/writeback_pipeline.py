from __future__ import annotations

from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.pipelines.writeback_pipeline.run_writeback")
def run_writeback(self, episode_id: str, project_id: str):
    from workers.tasks.writeback import writeback_episode
    writeback_episode.delay(episode_id=episode_id, project_id=project_id)
