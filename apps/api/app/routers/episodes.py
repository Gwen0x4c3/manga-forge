import io
import re
import zipfile
from decimal import Decimal

from celery import Celery
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from PIL import Image as PILImage
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm import get_active_llm_config
from app.dependencies import get_db
from app.schemas.episode import (
    EpisodeImport,
    EpisodeMemoryResponse,
    EpisodePageResponse,
    EpisodeResponse,
    EpisodeUpdate,
)
from app.services import episode_service, generation_service, storage_service

router = APIRouter()


@router.get("/{project_id}/episodes", response_model=dict)
async def list_episodes(
    project_id: str,
    branch_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
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


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".avif"}


def _natural_sort_key(name: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _extract_images_from_zip(zip_bytes: bytes) -> list[tuple[str, bytes, str]]:
    results: list[tuple[str, bytes, str]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        image_files = [
            info
            for info in zf.infolist()
            if not info.is_dir()
            and any(info.filename.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)
            and "__MACOSX" not in info.filename
            and not info.filename.rsplit("/", 1)[-1].startswith("._")
        ]
        image_files.sort(key=lambda info: _natural_sort_key(info.filename))
        for info in image_files:
            filename = info.filename.rsplit("/", 1)[-1]
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
            content_type = f"image/{'jpeg' if ext == 'jpg' else ext}"
            results.append((filename, zf.read(info), content_type))
    return results


def _get_image_size(img_bytes: bytes) -> tuple[int, int] | tuple[None, None]:
    try:
        with PILImage.open(io.BytesIO(img_bytes)) as img:
            return img.size
    except Exception:
        return None, None


@router.post("/{project_id}/episodes/import-files", response_model=EpisodeResponse, status_code=201)
async def import_episode_files(
    project_id: str,
    branch_id: str = Form(...),
    number: Decimal = Form(...),
    label: str = Form(""),
    title: str | None = Form(None),
    category: str = Form("regular"),
    auto_understand: bool = Form(False),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
):
    effective_label = label.strip() or (str(int(number)) if number == int(number) else str(number))
    episode_data = EpisodeImport(
        branch_id=branch_id,
        number=number,
        label=effective_label,
        title=title,
        source="import_local",
        category=category,
    )
    episode = await episode_service.create_episode(db, project_id, episode_data)

    from app.models.episode_page import EpisodePage

    page_index = 0
    # Sort uploaded loose image files naturally by filename so page order matches 1.jpg, 2.jpg, ..., 10.jpg
    file_entries: list[tuple[str, bytes, str | None]] = []
    for file in files:
        content = await file.read()
        file_entries.append((file.filename or f"page_{len(file_entries)}.png", content, file.content_type))

    if len(file_entries) > 1 and not any(zipfile.is_zipfile(io.BytesIO(c)) for _, c, _ in file_entries):
        file_entries.sort(key=lambda entry: _natural_sort_key(entry[0]))

    for filename, content, content_type in file_entries:
        if zipfile.is_zipfile(io.BytesIO(content)):
            extracted = _extract_images_from_zip(content)
            if not extracted:
                raise HTTPException(status_code=400, detail=f"ZIP file '{filename}' contains no image files")
            for img_name, img_bytes, img_ct in extracted:
                object_key = storage_service.generate_object_key(f"episodes/{episode.id}", img_name)
                storage_service.upload_file(settings.MINIO_BUCKET, object_key, img_bytes, content_type=img_ct)
                w, h = _get_image_size(img_bytes)
                page = EpisodePage(
                    episode_id=episode.id, page_index=page_index, image_path=object_key, width=w, height=h
                )
                db.add(page)
                page_index += 1
        elif any(filename.lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
            object_key = storage_service.generate_object_key(f"episodes/{episode.id}", filename)
            storage_service.upload_file(
                settings.MINIO_BUCKET, object_key, content, content_type=content_type or "image/png"
            )
            w, h = _get_image_size(content)
            page = EpisodePage(episode_id=episode.id, page_index=page_index, image_path=object_key, width=w, height=h)
            db.add(page)
            page_index += 1

    await db.commit()
    await db.refresh(episode)

    if auto_understand and page_index > 0:
        vision_cfg = get_active_llm_config("vision_llm")
        run = await generation_service.create_generation_run(
            db,
            episode_id=str(episode.id),
            stage="understand",
            backend=vision_cfg.provider_key,
            model=vision_cfg.model,
        )
        celery_client = Celery("mangaforge-api", broker=settings.CELERY_BROKER_URL)
        try:
            celery_client.send_task("workers.tasks.understand.summarize_episode", args=[str(run.id), str(episode.id)])
        except Exception as exc:
            await generation_service.update_generation_run(db, str(run.id), "failed", error=str(exc))
            raise HTTPException(status_code=500, detail=f"提交理解任务失败: {exc}") from exc

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


@router.delete("/episodes/{episode_id}", status_code=204)
async def delete_episode(episode_id: str, db: AsyncSession = Depends(get_db)):
    episode = await episode_service.get_episode(db, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await episode_service.delete_episode(db, episode)


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
    vision_cfg = get_active_llm_config("vision_llm")
    run = await generation_service.create_generation_run(
        db, episode_id=episode.id, stage="understand", backend=vision_cfg.provider_key, model=vision_cfg.model
    )
    celery_client = Celery("mangaforge-api", broker=settings.CELERY_BROKER_URL)
    task = celery_client.send_task("workers.tasks.understand.summarize_episode", args=[str(run.id), episode.id])
    return {"task_id": task.id, "run_id": str(run.id), "episode_id": episode_id}
