from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.generation_run import GenerationRun
from app.schemas.generation import (
    ContinueFromEpisodeRequest,
    ContinueFromEpisodeResponse,
    GeneratedImageResponse,
    GenerationRunResponse,
    LayoutRequest,
    LayoutResponse,
    RenderRequest,
    RenderResponse,
    ScriptGenerateRequest,
    ScriptGenerateResponse,
    UnderstandRequest,
    UnderstandResponse,
)
from app.services import generation_service
from app.services import episode_service

router = APIRouter()


@router.post("/continue", response_model=ContinueFromEpisodeResponse)
async def continue_from_episode(request: ContinueFromEpisodeRequest, db: AsyncSession = Depends(get_db)):
    base_episode = await episode_service.find_episode(db, request.project_id, request.branch_id, request.base_episode_number)
    if not base_episode:
        raise HTTPException(status_code=404, detail="Base episode not found")
    new_number = Decimal(int(request.base_episode_number) + 1)
    new_label = str(int(new_number))
    new_episode = Episode(
        project_id=request.project_id,
        branch_id=request.branch_id,
        number=new_number,
        label=new_label,
        title=request.title or f"Episode {new_label}",
        source="generated",
        status="draft",
        category="regular",
        parent_episode_id=str(base_episode.id),
    )
    db.add(new_episode)
    await db.commit()
    await db.refresh(new_episode)
    run = await generation_service.create_generation_run(
        db, episode_id=str(new_episode.id), stage="continue", backend="openai",
    )
    try:
        from workers.pipelines.continue_pipeline import run_continue
        task = run_continue.delay(
            str(new_episode.id),
            request.branch_id,
            float(request.base_episode_number),
            request.tone,
            request.custom_instructions,
            request.image_backend,
            request.image_model,
            request.image_size,
        )
    except Exception:
        task = None
    return ContinueFromEpisodeResponse(
        episode_id=str(new_episode.id),
        episode_number=new_number,
        task_id=task.id if task else str(run.id),
        status="queued",
    )


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
        params={"tone": request.tone, "base_episode_number": float(request.base_episode_number)},
    )
    try:
        from workers.tasks.script_gen import generate_script
        task = generate_script.delay(
            str(run.id),
            episode.id,
            request.branch_id,
            float(request.base_episode_number),
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
        backend=run.backend,
        model=run.model,
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
        backend=r.backend,
        model=r.model,
        error=r.error,
        created_at=r.created_at.isoformat() if r.created_at else None,
        finished_at=r.finished_at.isoformat() if r.finished_at else None,
    ) for r in runs]}


@router.post("/render", response_model=RenderResponse)
async def trigger_render(request: RenderRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Episode).where(Episode.id == request.episode_id))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    storyboard_memory_id = request.storyboard_memory_id
    if storyboard_memory_id:
        mem_result = await db.execute(
            select(EpisodeMemory).where(EpisodeMemory.id == storyboard_memory_id)
        )
        memory = mem_result.scalar_one_or_none()
        if not memory or memory.type != "storyboard_json":
            raise HTTPException(status_code=400, detail="Invalid storyboard memory ID")

    run = await generation_service.create_generation_run(
        db,
        episode_id=episode.id,
        stage="render",
        backend=request.image_backend or "openai",
        model=request.image_model,
        params={"image_size": request.image_size},
    )

    try:
        from workers.tasks.render import render_episode
        task = render_episode.delay(
            str(run.id),
            episode.id,
            request.image_backend,
            request.image_model,
            request.image_size,
        )
    except Exception:
        task = None

    return RenderResponse(
        task_id=task.id if task else str(run.id),
        episode_id=episode.id,
        status="queued",
        panel_count=0,
    )


@router.post("/layout", response_model=LayoutResponse)
async def trigger_layout(request: LayoutRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Episode).where(Episode.id == request.episode_id))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    run = await generation_service.create_generation_run(
        db,
        episode_id=episode.id,
        stage="layout",
    )

    try:
        from workers.tasks.layout import layout_episode
        task = layout_episode.delay(
            str(run.id),
            episode.id,
            request.template_override,
        )
    except Exception:
        task = None

    return LayoutResponse(
        task_id=task.id if task else str(run.id),
        episode_id=episode.id,
        status="queued",
        page_count=0,
    )


@router.get("/episodes/{episode_id}/images")
async def list_generated_images(episode_id: str, db: AsyncSession = Depends(get_db)):
    images = await generation_service.get_generated_images(db, episode_id)
    return {"items": [GeneratedImageResponse(
        id=img.id,
        generation_run_id=img.generation_run_id,
        episode_id=img.episode_id,
        panel_id=img.panel_id,
        image_path=img.image_path,
        meta=img.meta,
        created_at=img.created_at.isoformat() if img.created_at else None,
    ) for img in images]}


@router.get("/episodes/{episode_id}/layout")
async def get_episode_layout(episode_id: str, db: AsyncSession = Depends(get_db)):
    layout = await generation_service.get_layout_result(db, episode_id)
    if not layout:
        raise HTTPException(status_code=404, detail="No layout result found")
    return {"pages": layout.content.get("pages", [])}
