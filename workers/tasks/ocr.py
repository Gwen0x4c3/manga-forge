from workers.celery_app import celery_app


@celery_app.task(bind=True, name="workers.tasks.ocr.extract_text")
def extract_text(self, episode_id: str):
    self.update_state(state="RUNNING", meta={"episode_id": episode_id, "progress": 0})
    # TODO: Implement OCR
    # 1. Load episode pages
    # 2. Run OCR on each page
    # 3. Save results to panels.ocr_text and episode_memories
    return {"episode_id": episode_id, "status": "completed"}
