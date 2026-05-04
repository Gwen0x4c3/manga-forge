from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.tasks.script_gen.generate_script")
def generate_script(self, episode_id: str, config: dict | None = None):
    self.update_state(state="RUNNING", meta={"episode_id": episode_id, "progress": 0})
    # TODO: Implement script generation
    # 1. Build context from memory (canon + long_summary + recent_window + RAG)
    # 2. Call LLM to generate storyboard JSON
    # 3. Validate against JSON Schema
    # 4. Run consistency checks
    # 5. Save to episode_memories
    return {"episode_id": episode_id, "status": "completed"}
