from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.pipelines.generate_pipeline")
def generate_pipeline(self, episode_id: str, config: dict | None = None):
    self.update_state(state="RUNNING", meta={"episode_id": episode_id, "progress": 0})
    # TODO: Implement generation pipeline
    # 1. Build context (memory + assets + pits)
    # 2. Generate script
    # 3. Consistency check
    # 4. Render panels
    # 5. Layout + bubbles
    # 6. Write back memory
    return {"episode_id": episode_id, "status": "completed"}
