from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_utils import get_mangadex_logger
from app.models.branch import Branch
from app.models.episode import Episode
from app.models.episode_external_ref import EpisodeExternalRef
from app.models.episode_page import EpisodePage
from app.models.import_job import ImportJob
from app.models.import_job_item import ImportJobItem
from app.models.project import Project
from app.models.source_binding import SourceBinding
from app.providers.mangadex import (
    MangaDexChapterCandidate,
    extract_headers_from_curl,
    fetch_chapter_candidates,
    merge_request_headers,
    fetch_manga_metadata,
    parse_mangadex_title_url,
    parse_sort_number,
    sanitize_mangadex_input,
    summarize_request_headers,
)
from app.schemas.project import ProjectCreate
from app.services.storage_service import generate_object_key, upload_file
from app.services.episode_service import get_episode
from app.services.project_service import create_project, get_project

logger = logging.getLogger(__name__)
trace_logger = get_mangadex_logger()


IMPORT_ACTIVE_STATUSES = {"queued", "running"}


async def get_project_main_branch(db: AsyncSession, project_id: str) -> Branch | None:
    result = await db.execute(
        select(Branch).where(Branch.project_id == project_id, Branch.is_default.is_(True)).limit(1)
    )
    return result.scalar_one_or_none()


async def get_branch(db: AsyncSession, project_id: str, branch_id: str) -> Branch | None:
    result = await db.execute(
        select(Branch).where(Branch.id == branch_id, Branch.project_id == project_id).limit(1)
    )
    return result.scalar_one_or_none()


def _normalize_project_language(language_priority: list[str]) -> str:
    for lang in language_priority:
        if lang in {"zh", "en", "ja"}:
            return lang
        if lang.startswith("zh"):
            return "zh"
    return "zh"


async def _upsert_binding(
    db: AsyncSession,
    project_id: str,
    source_url: str,
    external_series_id: str,
    title: str,
    description: str | None,
    language_priority: list[str],
    metadata_json: dict,
) -> SourceBinding:
    result = await db.execute(
        select(SourceBinding).where(
            SourceBinding.project_id == project_id,
            SourceBinding.provider == "mangadex",
            SourceBinding.external_series_id == external_series_id,
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        binding = SourceBinding(
            project_id=project_id,
            provider="mangadex",
            external_series_id=external_series_id,
            source_url=source_url,
            title=title,
            description=description,
            language_priority=language_priority,
            metadata_json=metadata_json,
            last_discovered_at=datetime.now(timezone.utc),
        )
        db.add(binding)
        await db.flush()
        return binding

    binding.source_url = source_url
    binding.title = title
    binding.description = description
    binding.language_priority = language_priority
    binding.metadata_json = metadata_json
    binding.last_discovered_at = datetime.now(timezone.utc)
    await db.flush()
    return binding


async def _fill_project_metadata(
    db: AsyncSession,
    project: Project,
    title: str,
    description: str | None,
    language_priority: list[str],
    fill_project_metadata: bool,
    overwrite_project_metadata: bool,
) -> None:
    if not fill_project_metadata:
        return
    if overwrite_project_metadata or not project.title:
        project.title = title
    if description and (overwrite_project_metadata or not project.description):
        project.description = description
    if overwrite_project_metadata or not project.language:
        project.language = _normalize_project_language(language_priority)
    await db.flush()


async def create_project_and_discover(
    db: AsyncSession,
    source_url: str,
    request_curl: str | None = None,
    languages: list[str] | None = None,
    group_ids: list[str] | None = None,
    fill_project_metadata: bool = True,
    overwrite_project_metadata: bool = False,
) -> tuple[Project, ImportJob, list[ImportJobItem]]:
    source_url = sanitize_mangadex_input(source_url)
    request_curl = sanitize_mangadex_input(request_curl) if request_curl else None
    manga_id = parse_mangadex_title_url(source_url)
    request_headers = merge_request_headers(extract_headers_from_curl(request_curl))
    metadata = await fetch_manga_metadata(
        manga_id, language_priority=languages, request_headers=request_headers or None
    )
    project = await create_project(
        db,
        ProjectCreate(
            title=metadata.title,
            description=metadata.description,
            language=_normalize_project_language(metadata.language_priority),
        ),
    )
    try:
        branch = await get_project_main_branch(db, project.id)
        if branch is None:
            raise ValueError("Project main branch not found")
        return await discover_mangadex_for_project(
            db=db,
            project_id=project.id,
            branch_id=branch.id,
            source_url=source_url,
            request_curl=request_curl,
            languages=languages,
            group_ids=group_ids,
            fill_project_metadata=fill_project_metadata,
            overwrite_project_metadata=overwrite_project_metadata,
        )
    except Exception:
        await db.delete(project)
        await db.commit()
        raise


async def discover_mangadex_for_project(
    db: AsyncSession,
    project_id: str,
    branch_id: str,
    source_url: str,
    request_curl: str | None = None,
    languages: list[str] | None = None,
    group_ids: list[str] | None = None,
    fill_project_metadata: bool = True,
    overwrite_project_metadata: bool = False,
) -> tuple[Project, ImportJob, list[ImportJobItem]]:
    source_url = sanitize_mangadex_input(source_url)
    request_curl = sanitize_mangadex_input(request_curl) if request_curl else None
    project = await get_project(db, project_id)
    if project is None:
        raise ValueError("Project not found")
    branch = await get_branch(db, project_id, branch_id)
    if branch is None:
        raise ValueError("Branch not found")

    manga_id = parse_mangadex_title_url(source_url)
    request_headers = merge_request_headers(extract_headers_from_curl(request_curl))
    logger.info(
        "MangaDex discover start project_id=%s branch_id=%s manga_id=%s source_url=%s headers=%s requested_languages=%s group_ids=%s",
        project_id,
        branch_id,
        manga_id,
        source_url,
        summarize_request_headers(request_headers),
        languages or [],
        group_ids or [],
    )
    trace_logger.info(
        "discover start project_id=%s branch_id=%s manga_id=%s source_url=%s headers=%s requested_languages=%s group_ids=%s",
        project_id,
        branch_id,
        manga_id,
        source_url,
        summarize_request_headers(request_headers),
        languages or [],
        group_ids or [],
    )
    metadata = await fetch_manga_metadata(
        manga_id, language_priority=languages, request_headers=request_headers or None
    )
    candidates = await fetch_chapter_candidates(
        manga_id,
        language_priority=metadata.language_priority,
        groups=group_ids,
        request_headers=request_headers or None,
        metadata=metadata,
    )

    binding = await _upsert_binding(
        db,
        project_id=project_id,
        source_url=source_url,
        external_series_id=manga_id,
        title=metadata.title,
        description=metadata.description,
        language_priority=metadata.language_priority,
        metadata_json={
            "links": metadata.links,
            "tags": metadata.tags,
            "original_language": metadata.original_language,
            "available_languages": metadata.available_languages,
        },
    )

    await _fill_project_metadata(
        db,
        project=project,
        title=metadata.title,
        description=metadata.description,
        language_priority=metadata.language_priority,
        fill_project_metadata=fill_project_metadata,
        overwrite_project_metadata=overwrite_project_metadata,
    )

    job = ImportJob(
        project_id=project_id,
        branch_id=branch_id,
        binding_id=binding.id,
        provider="mangadex",
        job_type="discover",
        status="succeeded",
        source_url=source_url,
        external_series_id=manga_id,
        config={
            "languages": metadata.language_priority,
            "group_ids": group_ids or [],
            "fill_project_metadata": fill_project_metadata,
            "overwrite_project_metadata": overwrite_project_metadata,
        },
        metadata_json={
            "title": metadata.title,
            "description": metadata.description,
            "available_languages": metadata.available_languages,
            "tags": metadata.tags,
        },
        progress={"total": len(candidates), "discovered": len(candidates), "selected": 0},
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()

    items = await _create_job_items(db, job, candidates, manga_id)
    job.progress = _build_job_progress(items)
    await db.commit()
    await db.refresh(project)
    await db.refresh(job)
    reloaded_items = await list_import_job_items(db, job.id)
    logger.info(
        "MangaDex discover done project_id=%s job_id=%s total=%s selected=%s imported=%s missing=%s",
        project_id,
        job.id,
        job.progress.get("total") if isinstance(job.progress, dict) else None,
        job.progress.get("selected") if isinstance(job.progress, dict) else None,
        job.progress.get("imported") if isinstance(job.progress, dict) else None,
        job.progress.get("missing") if isinstance(job.progress, dict) else None,
    )
    trace_logger.info(
        "discover done project_id=%s job_id=%s progress=%s item_ids=%s",
        project_id,
        job.id,
        job.progress,
        [item.id for item in reloaded_items],
    )
    return project, job, reloaded_items


async def _create_job_items(
    db: AsyncSession, job: ImportJob, candidates: list[MangaDexChapterCandidate], manga_id: str
) -> list[ImportJobItem]:
    items: list[ImportJobItem] = []
    existing_refs = await get_existing_episode_refs_map(db, job.project_id, manga_id)

    for index, candidate in enumerate(candidates, start=1):
        existing_ref = existing_refs.get(candidate.chapter_id)
        episode_id = existing_ref.episode_id if existing_ref else None
        import_status = "imported" if episode_id else "pending"
        selection_status = "unselected" if episode_id else "selected"
        external_url = f"https://mangadex.org/chapter/{candidate.chapter_id}"
        item = ImportJobItem(
            job_id=job.id,
            external_chapter_id=candidate.chapter_id,
            chapter_number=candidate.chapter,
            sort_number=parse_sort_number(candidate.chapter, index),
            volume=candidate.volume,
            title=candidate.title,
            translated_language=candidate.translated_language,
            group_ids=candidate.group_ids,
            group_names=candidate.group_names,
            page_count=candidate.pages,
            selection_status=selection_status,
            import_status=import_status,
            episode_id=episode_id,
            external_url=external_url,
            progress={"missing": episode_id is None},
            metadata_json={
                "publish_at": candidate.publish_at,
                "is_unavailable": candidate.is_unavailable,
            },
        )
        db.add(item)
        items.append(item)

    await db.flush()
    return items


def _build_job_progress(items: list[ImportJobItem]) -> dict:
    selected = sum(1 for item in items if item.selection_status == "selected")
    imported = sum(1 for item in items if item.import_status == "imported")
    failed = sum(1 for item in items if item.import_status == "failed")
    return {
        "total": len(items),
        "selected": selected,
        "imported": imported,
        "failed": failed,
        "missing": sum(1 for item in items if item.progress and item.progress.get("missing")),
    }


async def get_existing_episode_refs_map(
    db: AsyncSession, project_id: str, external_series_id: str
) -> dict[str, EpisodeExternalRef]:
    result = await db.execute(
        select(EpisodeExternalRef)
        .join(Episode, Episode.id == EpisodeExternalRef.episode_id)
        .where(
            Episode.project_id == project_id,
            EpisodeExternalRef.provider == "mangadex",
            EpisodeExternalRef.external_series_id == external_series_id,
        )
    )
    refs = result.scalars().all()
    return {ref.external_chapter_id: ref for ref in refs}


async def list_import_jobs(db: AsyncSession, project_id: str) -> tuple[list[ImportJob], int]:
    count = (
        await db.execute(select(func.count()).select_from(ImportJob).where(ImportJob.project_id == project_id))
    ).scalar() or 0
    result = await db.execute(
        select(ImportJob).where(ImportJob.project_id == project_id).order_by(ImportJob.created_at.desc())
    )
    return result.scalars().all(), count


async def get_import_job(db: AsyncSession, project_id: str, job_id: str) -> ImportJob | None:
    result = await db.execute(
        select(ImportJob).where(ImportJob.id == job_id, ImportJob.project_id == project_id).limit(1)
    )
    return result.scalar_one_or_none()


async def list_import_job_items(db: AsyncSession, job_id: str) -> list[ImportJobItem]:
    result = await db.execute(
        select(ImportJobItem).where(ImportJobItem.job_id == job_id).order_by(ImportJobItem.sort_number.asc())
    )
    return result.scalars().all()


async def update_job_item_selection(
    db: AsyncSession, project_id: str, job_id: str, item_ids: list[str], action: str
) -> tuple[ImportJob, list[ImportJobItem]]:
    job = await get_import_job(db, project_id, job_id)
    if job is None:
        raise ValueError("Import job not found")
    items = await list_import_job_items(db, job_id)
    selected_ids = set(item_ids)
    next_status = "selected" if action == "select" else "unselected"
    for item in items:
        if item.id in selected_ids and item.import_status not in {"imported"}:
            item.selection_status = next_status
    job.progress = _build_job_progress(items)
    await db.commit()
    await db.refresh(job)
    return job, items


async def mark_job_paused(db: AsyncSession, project_id: str, job_id: str) -> ImportJob:
    job = await get_import_job(db, project_id, job_id)
    if job is None:
        raise ValueError("Import job not found")
    job.status = "paused"
    await db.commit()
    await db.refresh(job)
    return job


async def prepare_job_for_import(
    db: AsyncSession,
    project_id: str,
    job_id: str,
    auto_understand: bool,
    only_missing: bool,
    use_data_saver: bool,
) -> ImportJob:
    job = await get_import_job(db, project_id, job_id)
    if job is None:
        raise ValueError("Import job not found")
    if job.status in IMPORT_ACTIVE_STATUSES:
        raise RuntimeError("同一个导入任务已在运行中")

    items = await list_import_job_items(db, job_id)
    for item in items:
        if item.import_status == "failed":
            item.import_status = "pending"
            item.error = None
    job.job_type = "import"
    job.status = "queued"
    job.error = None
    job.started_at = datetime.now(timezone.utc)
    job.finished_at = None
    job.config = {
        **(job.config or {}),
        "auto_understand": auto_understand,
        "only_missing": only_missing,
        "use_data_saver": use_data_saver,
    }
    job.progress = _build_job_progress(items)
    await db.commit()
    await db.refresh(job)
    return job


async def begin_job_run(db: AsyncSession, job_id: str) -> ImportJob:
    result = await db.execute(select(ImportJob).where(ImportJob.id == job_id).limit(1))
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError("Import job not found")
    if job.status == "paused":
        await db.refresh(job)
        return job
    job.status = "running"
    job.started_at = job.started_at or datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)
    return job


async def complete_job_run(db: AsyncSession, job_id: str, status: str, error: str | None = None) -> ImportJob:
    result = await db.execute(select(ImportJob).where(ImportJob.id == job_id).limit(1))
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError("Import job not found")
    items = await list_import_job_items(db, job_id)
    job.status = status
    job.error = error
    job.finished_at = datetime.now(timezone.utc)
    job.progress = _build_job_progress(items)
    await db.commit()
    await db.refresh(job)
    return job


async def get_job_items_for_execution(db: AsyncSession, job_id: str, only_missing: bool) -> list[ImportJobItem]:
    items = await list_import_job_items(db, job_id)
    execution_items: list[ImportJobItem] = []
    for item in items:
        if item.selection_status != "selected":
            continue
        if item.import_status == "imported":
            continue
        if only_missing and item.episode_id:
            continue
        execution_items.append(item)
    return execution_items


async def create_episode_from_remote_pages(
    db: AsyncSession,
    project_id: str,
    branch_id: str,
    external_series_id: str,
    item: ImportJobItem,
    page_payloads: list[tuple[str, bytes, str]],
) -> Episode:
    existing_ref = await get_episode_external_ref(db, project_id, item.external_chapter_id)
    if existing_ref:
        episode = await get_episode(db, existing_ref.episode_id)
        if episode is None:
            raise ValueError("Existing external ref episode missing")
        item.episode_id = episode.id
        item.import_status = "imported"
        item.progress = {"missing": False, "reused": True}
        await db.commit()
        return episode

    category = "special" if item.sort_number >= Decimal("10000") else "regular"
    episode = Episode(
        project_id=project_id,
        branch_id=branch_id,
        number=item.sort_number,
        label=item.chapter_number,
        title=item.title,
        source="import_mangadex",
        status="imported",
        category=category,
    )
    db.add(episode)
    await db.flush()

    for page_index, (filename, img_bytes, content_type) in enumerate(page_payloads):
        object_key = generate_object_key(f"episodes/{episode.id}", filename)
        upload_file("mangaforge", object_key, img_bytes, content_type=content_type)
        page = EpisodePage(
            episode_id=episode.id,
            page_index=page_index,
            image_path=object_key,
        )
        db.add(page)

    external_ref = EpisodeExternalRef(
        episode_id=episode.id,
        provider="mangadex",
        external_series_id=external_series_id,
        external_chapter_id=item.external_chapter_id,
        external_url=item.external_url,
        metadata_json={
            "chapter_number": item.chapter_number,
            "volume": item.volume,
            "translated_language": item.translated_language,
            "group_names": item.group_names,
            "page_count": item.page_count,
            "metadata": item.metadata_json,
        },
    )
    db.add(external_ref)

    item.episode_id = episode.id
    item.import_status = "imported"
    item.progress = {"missing": False, "page_count": len(page_payloads)}
    await db.commit()
    await db.refresh(episode)
    return episode


async def get_episode_external_ref(
    db: AsyncSession, project_id: str, external_chapter_id: str
) -> EpisodeExternalRef | None:
    result = await db.execute(
        select(EpisodeExternalRef)
        .join(Episode, Episode.id == EpisodeExternalRef.episode_id)
        .where(
            Episode.project_id == project_id,
            EpisodeExternalRef.provider == "mangadex",
            EpisodeExternalRef.external_chapter_id == external_chapter_id,
        )
    )
    return result.scalar_one_or_none()


async def set_item_running(db: AsyncSession, item_id: str) -> ImportJobItem:
    result = await db.execute(select(ImportJobItem).where(ImportJobItem.id == item_id).limit(1))
    item = result.scalar_one_or_none()
    if item is None:
        raise ValueError("Import item not found")
    item.import_status = "running"
    item.error = None
    await db.commit()
    await db.refresh(item)
    return item


async def set_item_failed(db: AsyncSession, item_id: str, error: str) -> ImportJobItem:
    result = await db.execute(select(ImportJobItem).where(ImportJobItem.id == item_id).limit(1))
    item = result.scalar_one_or_none()
    if item is None:
        raise ValueError("Import item not found")
    item.import_status = "failed"
    item.error = error
    await db.commit()
    await db.refresh(item)
    return item
