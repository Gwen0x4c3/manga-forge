from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.tasks.layout.layout_episode")
def layout_episode(self, episode_id: str, template: str = "2x2"):
    self.update_state(state="RUNNING", meta={"episode_id": episode_id, "progress": 0})
    # TODO: Implement layout
    # 1. Load generated panel images
    # 2. Apply layout template
    # 3. Add speech bubbles
    # 4. Export final pages to MinIO
    return {"episode_id": episode_id, "status": "completed"}
