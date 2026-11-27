import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "api"))

from app.config import settings
from celery import Celery

celery_app = Celery(
    "mangaforge",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
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

import workers.pipelines.continue_pipeline  # noqa: E402, F401
import workers.tasks.google_flow  # noqa: E402, F401
import workers.tasks.layout  # noqa: E402, F401
import workers.tasks.mangadex  # noqa: E402, F401
import workers.tasks.render  # noqa: E402, F401
import workers.tasks.script_gen  # noqa: E402, F401
import workers.tasks.understand  # noqa: E402, F401
import workers.tasks.writeback  # noqa: E402, F401
