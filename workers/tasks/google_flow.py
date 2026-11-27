import asyncio

from app.database import worker_session
from app.services import flow_video

from workers.celery_app import celery_app


@celery_app.task(name="workers.tasks.google_flow.generate", acks_late=True, reject_on_worker_lost=True)
def generate(run_id: str):
    async def work():
        async with worker_session() as db:
            await flow_video.execute(db, run_id)

    asyncio.run(work())
