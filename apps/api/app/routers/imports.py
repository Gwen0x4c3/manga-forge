import logging

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.logging_utils import get_mangadex_logger
from app.providers.mangadex import (
    extract_headers_from_curl,
    merge_request_headers,
    sanitize_mangadex_input,
    summarize_request_headers,
)
from app.schemas.imports import (
    ImportExecutionResponse,
    ImportJobListResponse,
    ImportJobResponse,
    ImportJobItemResponse,
    ImportSelectionRequest,
    ImportStartRequest,
    MangaDexCreateProjectRequest,
    MangaDexCreateProjectResponse,
    MangaDexDiscoverRequest,
    MangaDexDiscoverResponse,
)
from app.services import import_service, project_service

router = APIRouter()
logger = logging.getLogger(__name__)
trace_logger = get_mangadex_logger()
celery_client = Celery(
    "mangaforge-imports",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)


@router.post("/mangadex/projects/discover", response_model=MangaDexCreateProjectResponse, status_code=201)
async def create_project_from_mangadex(
    data: MangaDexCreateProjectRequest,
    db: AsyncSession = Depends(get_db),
):
    project, job, items = await import_service.create_project_and_discover(
        db=db,
        source_url=data.source_url,
        request_curl=data.request_curl,
        languages=data.languages,
        group_ids=data.group_ids,
        fill_project_metadata=data.fill_project_metadata,
        overwrite_project_metadata=data.overwrite_project_metadata,
    )
    return {
        "project": project,
        "job": job,
        "items": items,
    }


@router.post("/projects/{project_id}/mangadex/discover", response_model=MangaDexDiscoverResponse, status_code=201)
async def discover_mangadex_for_project(
    project_id: str,
    data: MangaDexDiscoverRequest,
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        "MangaDex discover request project_id=%s branch_id=%s source_url=%s headers=%s languages=%s",
        project_id,
        data.branch_id,
        sanitize_mangadex_input(data.source_url),
        summarize_request_headers(merge_request_headers(extract_headers_from_curl(data.request_curl)) or None),
        data.languages or [],
    )
    trace_logger.info(
        "discover request project_id=%s branch_id=%s source_url=%s headers=%s languages=%s",
        project_id,
        data.branch_id,
        sanitize_mangadex_input(data.source_url),
        summarize_request_headers(merge_request_headers(extract_headers_from_curl(data.request_curl)) or None),
        data.languages or [],
    )
    try:
        project, job, items = await import_service.discover_mangadex_for_project(
            db=db,
            project_id=project_id,
            branch_id=data.branch_id,
            source_url=data.source_url,
            request_curl=data.request_curl,
            languages=data.languages,
            group_ids=data.group_ids,
            fill_project_metadata=data.fill_project_metadata,
            overwrite_project_metadata=data.overwrite_project_metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "project": project,
        "job": job,
        "items": items,
    }


@router.get("/projects/{project_id}/jobs", response_model=ImportJobListResponse)
async def list_project_import_jobs(project_id: str, db: AsyncSession = Depends(get_db)):
    items, total = await import_service.list_import_jobs(db, project_id)
    return {"items": items, "total": total}


@router.get("/projects/{project_id}/jobs/{job_id}", response_model=ImportJobResponse)
async def get_project_import_job(project_id: str, job_id: str, db: AsyncSession = Depends(get_db)):
    job = await import_service.get_import_job(db, project_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


@router.get("/projects/{project_id}/jobs/{job_id}/items", response_model=list[ImportJobItemResponse])
async def list_project_import_job_items(project_id: str, job_id: str, db: AsyncSession = Depends(get_db)):
    job = await import_service.get_import_job(db, project_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return await import_service.list_import_job_items(db, job_id)


@router.patch("/projects/{project_id}/jobs/{job_id}/selection", response_model=MangaDexDiscoverResponse)
async def update_project_import_selection(
    project_id: str,
    job_id: str,
    data: ImportSelectionRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        job, items = await import_service.update_job_item_selection(
            db=db,
            project_id=project_id,
            job_id=job_id,
            item_ids=data.item_ids,
            action=data.action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project, "job": job, "items": items}


def _dispatch_import_job(job_id: str, request_curl: str | None = None) -> str:
    request_headers = merge_request_headers(extract_headers_from_curl(request_curl)) or None
    logger.info("MangaDex import dispatch job_id=%s headers=%s", job_id, summarize_request_headers(request_headers))
    trace_logger.info("import dispatch job_id=%s headers=%s", job_id, summarize_request_headers(request_headers))
    task = celery_client.send_task("workers.tasks.mangadex.run_mangadex_import", args=(job_id, request_headers))
    return task.id


@router.post("/projects/{project_id}/jobs/{job_id}/start", response_model=ImportExecutionResponse)
async def start_project_import_job(
    project_id: str,
    job_id: str,
    data: ImportStartRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        job = await import_service.prepare_job_for_import(
            db=db,
            project_id=project_id,
            job_id=job_id,
            auto_understand=data.auto_understand,
            only_missing=data.only_missing,
            use_data_saver=data.use_data_saver,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    task_id = _dispatch_import_job(job.id, data.request_curl)
    return {"job": job, "task_id": task_id}


@router.post("/projects/{project_id}/jobs/{job_id}/resume", response_model=ImportExecutionResponse)
async def resume_project_import_job(
    project_id: str,
    job_id: str,
    data: ImportStartRequest,
    db: AsyncSession = Depends(get_db),
):
    existing_job = await import_service.get_import_job(db, project_id, job_id)
    if existing_job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    config = existing_job.config or {}
    try:
        job = await import_service.prepare_job_for_import(
            db=db,
            project_id=project_id,
            job_id=job_id,
            auto_understand=bool(config.get("auto_understand", False)),
            only_missing=bool(config.get("only_missing", True)),
            use_data_saver=bool(config.get("use_data_saver", True)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    task_id = _dispatch_import_job(job.id, data.request_curl)
    return {"job": job, "task_id": task_id}


@router.post("/projects/{project_id}/jobs/{job_id}/pause", response_model=ImportJobResponse)
async def pause_project_import_job(project_id: str, job_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await import_service.mark_job_paused(db, project_id, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
