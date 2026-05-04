from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.episode import Episode
from app.models.generation_run import GenerationRun
from app.schemas.generation import (
    GenerationRunResponse,
    ScriptGenerateRequest,
    ScriptGenerateResponse,
    UnderstandRequest,
    UnderstandResponse,
)
from app.services import generation_service

router = APIRouter()


@router.post("/understand", response_model=UnderstandResponse)
async def trigger_understand(request: UnderstandRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Episode).where(Episode.id == request.episode_id))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    run = await generation_service.create_generation_run(
        db, episode_id=episode.id, stage="understand", backend="openai"
    )
    try:
        from workers.tasks.understand import summarize_episode
        task = summarize_episode.delay(str(run.id), episode.id)
    except Exception:
        task = None
    return UnderstandResponse(
        task_id=task.id if task else str(run.id),
        episode_id=episode.id,
        status="queued",
    )


@router.post("/script", response_model=ScriptGenerateResponse)
async def trigger_script_generation(request: ScriptGenerateRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Episode).where(Episode.id == request.episode_id))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    run = await generation_service.create_generation_run(
        db,
        episode_id=episode.id,
        stage="script",
        backend="openai",
        params={"tone": request.tone, "base_episode_number": request.base_episode_number},
    )
    try:
        from workers.tasks.script_gen import generate_script
        task = generate_script.delay(
            str(run.id),
            episode.id,
            request.branch_id,
            request.base_episode_number,
            request.tone,
            request.custom_instructions,
        )
    except Exception:
        task = None
    return ScriptGenerateResponse(
        task_id=task.id if task else str(run.id),
        episode_id=episode.id,
        status="queued",
    )


@router.get("/runs/{run_id}", response_model=GenerationRunResponse)
async def get_generation_run(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Generation run not found")
    return GenerationRunResponse(
        id=run.id,
        episode_id=run.episode_id,
        stage=run.stage,
        status=run.status,
        error=run.error,
        created_at=run.created_at.isoformat() if run.created_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
    )


@router.get("/episodes/{episode_id}/runs")
async def list_episode_runs(episode_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GenerationRun).where(GenerationRun.episode_id == episode_id))
    runs = result.scalars().all()
    return {"items": [GenerationRunResponse(
        id=r.id,
        episode_id=r.episode_id,
        stage=r.stage,
        status=r.status,
        error=r.error,
        created_at=r.created_at.isoformat() if r.created_at else None,
        finished_at=r.finished_at.isoformat() if r.finished_at else None,
    ) for r in runs]}
