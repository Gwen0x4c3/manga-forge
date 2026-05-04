from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.generation_run import GenerationRun

router = APIRouter()


@router.get("/runs/{run_id}")
async def get_generation_run(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Generation run not found")
    return {
        "id": run.id,
        "episode_id": run.episode_id,
        "stage": run.stage,
        "status": run.status,
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.get("/episodes/{episode_id}/runs")
async def list_episode_runs(episode_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GenerationRun).where(GenerationRun.episode_id == episode_id))
    runs = result.scalars().all()
    return {"items": [{"id": r.id, "stage": r.stage, "status": r.status} for r in runs]}
