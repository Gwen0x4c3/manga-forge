from __future__ import annotations

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.models import Episode, GenerationRun
from app.providers.google_flow import FlowError
from app.schemas.google_flow import FlowOptions, FlowPlan, FlowStart
from app.services import flow_video
from app.services.flow_plan import build_plan

router = APIRouter(prefix="/episodes/{episode_id}")
celery_client = Celery("mangaforge-api", broker=settings.CELERY_BROKER_URL)


async def get_episode(episode_id: str, db: AsyncSession = Depends(get_db)) -> Episode:
    episode = await db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(404, "未找到本话")
    return episode


@router.post("/plan", response_model=FlowPlan)
async def preview(options: FlowOptions, ep: Episode = Depends(get_episode), db: AsyncSession = Depends(get_db)):
    try:
        return await build_plan(db, ep, options)
    except FlowError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/runs")
async def history(ep: Episode = Depends(get_episode), db: AsyncSession = Depends(get_db)):
    runs = (
        await db.execute(
            select(GenerationRun)
            .where(GenerationRun.episode_id == ep.id, GenerationRun.stage == flow_video.STAGE)
            .order_by(GenerationRun.created_at.desc(), GenerationRun.id.desc())
            .limit(20)
        )
    ).scalars()
    return [flow_video.describe(run) for run in runs]


async def dispatch(db: AsyncSession, run: GenerationRun, enqueue: bool):
    if enqueue:
        try:
            celery_client.send_task("workers.tasks.google_flow.generate", args=[run.id], queue="flow")
        except Exception as exc:
            await flow_video.fail_run(db, run.id, "无法提交到视频队列，请检查 Redis 和 Celery Worker")
            raise HTTPException(503, "无法提交到视频队列，请检查 Redis 和 Celery Worker") from exc
    return flow_video.describe(run)


@router.post("/runs", status_code=202)
async def start(spec: FlowStart, ep: Episode = Depends(get_episode), db: AsyncSession = Depends(get_db)):
    try:
        run, enqueue = await flow_video.start_run(db, ep, spec)
    except FlowError as exc:
        raise HTTPException(409, str(exc)) from exc
    return await dispatch(db, run, enqueue)


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume(
    run_id: str,
    retry_uncertain: bool = False,
    provider_id: str | None = None,
    ep: Episode = Depends(get_episode),
    db: AsyncSession = Depends(get_db),
):
    try:
        run, enqueue = await flow_video.resume_run(db, ep, run_id, retry_uncertain, provider_id)
    except FlowError as exc:
        raise HTTPException(409, str(exc)) from exc
    return await dispatch(db, run, enqueue)
