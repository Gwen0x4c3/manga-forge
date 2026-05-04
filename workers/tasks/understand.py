from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.tasks.understand.summarize_episode")
def summarize_episode(self, episode_id: str):
    self.update_state(state="RUNNING", meta={"episode_id": episode_id, "progress": 0})
    # TODO: Implement episode understanding
    # 1. Load episode pages from MinIO
    # 2. Call LLM to generate summary, events, state_changes
    # 3. Save results to episode_memories table
    # 4. Update episode status to "understood"
    return {"episode_id": episode_id, "status": "completed"}
