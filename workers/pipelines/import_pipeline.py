from workers.celery_app import celery_app
from workers.tasks.understand import summarize_episode


@celery_app.task(bind=True, name="workers.pipelines.import_pipeline")
def import_pipeline(self, project_id: str, source: str, files: list[str]):
    self.update_state(state="RUNNING", meta={"project_id": project_id, "progress": 0})
    # TODO: Implement import pipeline
    # 1. Parse zip/folder to identify episodes
    # 2. Save images to MinIO
    # 3. Create episode + episode_pages records
    # 4. Trigger understanding tasks
    return {"project_id": project_id, "status": "completed"}
