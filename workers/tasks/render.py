from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.tasks.render.render_panel")
def render_panel(self, episode_id: str, panel_data: dict):
    self.update_state(state="RUNNING", meta={"episode_id": episode_id, "progress": 0})
    # TODO: Implement panel rendering
    # 1. Call Image Backend (ComfyUI) to generate panel image
    # 2. Save result to MinIO
    # 3. Create generated_images record
    return {"episode_id": episode_id, "status": "completed"}


@celery_app.task(bind=True, name="workers.tasks.render.render_episode")
def render_episode(self, episode_id: str):
    self.update_state(state="RUNNING", meta={"episode_id": episode_id, "progress": 0})
    # TODO: Implement batch episode rendering
    # 1. Load storyboard JSON
    # 2. For each panel, dispatch render_panel task
    # 3. Wait for all panels to complete
    return {"episode_id": episode_id, "status": "completed"}
