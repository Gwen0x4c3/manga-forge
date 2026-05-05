import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "api"))

import os

from celery import Celery

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery(
    "mangaforge",
    broker=broker_url,
    backend=result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

import workers.tasks.understand  # noqa: E402, F401
import workers.tasks.script_gen  # noqa: E402, F401
import workers.tasks.render  # noqa: E402, F401
import workers.tasks.layout  # noqa: E402, F401
import workers.tasks.writeback  # noqa: E402, F401
import workers.tasks.ocr  # noqa: E402, F401
import workers.pipelines.continue_pipeline  # noqa: E402, F401
