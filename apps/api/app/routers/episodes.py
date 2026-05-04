from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.episode import (
    EpisodeImport,
    EpisodeMemoryResponse,
    EpisodePageResponse,
    EpisodeResponse,
    EpisodeUpdate,
)
from app.services import episode_service, storage_service

router = APIRouter()


@router.get("/{project_id}/episodes", response_model=dict)
async def list_episodes(
    project_id: str,
    branch_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await episode_service.list_episodes(
        db, project_id, branch_id=branch_id, page=page, page_size=page_size
    )
    return {"items": [EpisodeResponse.model_validate(e) for e in items], "total": total}


@router.post("/{project_id}/episodes/import", response_model=EpisodeResponse, status_code=201)
async def import_episode(
    project_id: str,
    data: EpisodeImport,
    db: AsyncSession = Depends(get_db),
):
    episode = await episode_service.create_episode(db, project_id, data)
    return EpisodeResponse.model_validate(episode)


@router.post("/{project_id}/episodes/import-files", response_model=EpisodeResponse, status_code=201)
async def import_episode_files(
    project_id: str,
    branch_id: str,
    number: int,
    title: str | None = None,
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
):
    episode_data = EpisodeImport(branch_id=branch_id, number=number, title=title, source="import_local")
    episode = await episode_service.create_episode(db, project_id, episode_data)
    for idx, file in enumerate(files):
        content = await file.read()
        object_key = storage_service.generate_object_key(f"episodes/{episode.id}", file.filename or f"page_{idx}")
        storage_service.upload_file("mangaforge", object_key, content, content_type=file.content_type or "image/png")
        from app.models.episode_page import EpisodePage
        page = EpisodePage(episode_id=episode.id, page_index=idx, image_path=object_key)
        db.add(page)
    await db.commit()
    await db.refresh(episode)
    return EpisodeResponse.model_validate(episode)


@router.get("/episodes/{episode_id}", response_model=EpisodeResponse)
async def get_episode(episode_id: str, db: AsyncSession = Depends(get_db)):
    episode = await episode_service.get_episode(db, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return EpisodeResponse.model_validate(episode)


@router.put("/episodes/{episode_id}", response_model=EpisodeResponse)
async def update_episode(episode_id: str, data: EpisodeUpdate, db: AsyncSession = Depends(get_db)):
    episode = await episode_service.get_episode(db, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    episode = await episode_service.update_episode(db, episode, data)
    return EpisodeResponse.model_validate(episode)


@router.get("/episodes/{episode_id}/pages", response_model=list[EpisodePageResponse])
async def get_episode_pages(episode_id: str, db: AsyncSession = Depends(get_db)):
    pages = await episode_service.get_episode_pages(db, episode_id)
    return [EpisodePageResponse.model_validate(p) for p in pages]


@router.get("/episodes/{episode_id}/memories", response_model=list[EpisodeMemoryResponse])
async def get_episode_memories(episode_id: str, db: AsyncSession = Depends(get_db)):
    memories = await episode_service.get_episode_memories(db, episode_id)
    return [EpisodeMemoryResponse.model_validate(m) for m in memories]


@router.post("/episodes/{episode_id}/understand", response_model=dict)
async def trigger_understand(episode_id: str, db: AsyncSession = Depends(get_db)):
    episode = await episode_service.get_episode(db, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    from app.services import generation_service
    run = await generation_service.create_generation_run(
        db, episode_id=episode.id, stage="understand", backend="openai"
    )
    task_id = None
    try:
        from workers.tasks.understand import summarize_episode
        task = summarize_episode.delay(str(run.id), episode.id)
        task_id = task.id
    except Exception:
        task_id = str(run.id)
    return {"task_id": task_id, "run_id": str(run.id), "episode_id": episode_id}
