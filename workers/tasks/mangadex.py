from __future__ import annotations

import asyncio
import logging

from app.logging_utils import get_mangadex_logger
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)
trace_logger = get_mangadex_logger()


@celery_app.task(bind=True, name="workers.tasks.mangadex.run_mangadex_import")
def run_mangadex_import(self, job_id: str, request_headers: dict[str, str] | None = None):
    asyncio.run(_run_mangadex_import(self, job_id, request_headers))


async def _run_mangadex_import(self, job_id: str, request_headers: dict[str, str] | None = None):
    from sqlalchemy import select

    from app.config import settings
    from app.database import async_session
    from app.models.import_job import ImportJob
    from app.models.import_job_item import ImportJobItem
    from app.providers.mangadex import build_page_request_headers, fetch_chapter_image_urls, summarize_request_headers
    from app.services import generation_service, import_service

    async with async_session() as db:
        result = await db.execute(select(ImportJob).where(ImportJob.id == job_id).limit(1))
        job = result.scalar_one_or_none()
        if job is None:
            raise ValueError(f"Import job {job_id} not found")

        current_job = await import_service.begin_job_run(db, job_id)
        if current_job.status == "paused":
            return
        config = job.config or {}
        only_missing = bool(config.get("only_missing", True))
        auto_understand = bool(config.get("auto_understand", False))
        use_data_saver = bool(config.get("use_data_saver", True))
        page_delay = max(settings.MANGADEX_PAGE_DELAY_MS, 0) / 1000
        req_delay = max(settings.MANGADEX_REQUEST_INTERVAL_MS, 0) / 1000

        try:
            logger.info(
                "MangaDex import worker start job_id=%s project_id=%s headers=%s",
                job_id,
                job.project_id,
                summarize_request_headers(request_headers),
            )
            trace_logger.info(
                "import worker start job_id=%s project_id=%s headers=%s",
                job_id,
                job.project_id,
                summarize_request_headers(request_headers),
            )
            items = await import_service.get_job_items_for_execution(db, job_id, only_missing=only_missing)
            imported_count = 0
            failed_count = 0
            for item in items:
                current_job = await import_service.get_import_job(db, job.project_id, job_id)
                if current_job and current_job.status == "paused":
                    break

                await import_service.set_item_running(db, item.id)
                await asyncio.sleep(req_delay)

                try:
                    logger.info(
                        "MangaDex import item start job_id=%s item_id=%s chapter_id=%s chapter=%s",
                        job_id,
                        item.id,
                        item.external_chapter_id,
                        item.chapter_number,
                    )
                    trace_logger.info(
                        "import item start job_id=%s item_id=%s chapter_id=%s chapter=%s",
                        job_id,
                        item.id,
                        item.external_chapter_id,
                        item.chapter_number,
                    )
                    image_urls = await fetch_chapter_image_urls(
                        item.external_chapter_id,
                        use_data_saver=use_data_saver,
                        request_headers=request_headers,
                    )
                    page_payloads = []
                    import httpx

                    async with httpx.AsyncClient() as client:
                        for idx, page_url in enumerate(image_urls, start=1):
                            response = await client.get(
                                page_url,
                                headers=build_page_request_headers(request_headers),
                                timeout=30.0,
                            )
                            response.raise_for_status()
                            ext = page_url.rsplit(".", 1)[-1].lower() if "." in page_url else "jpg"
                            content_type = f"image/{'jpeg' if ext == 'jpg' else ext}"
                            page_payloads.append((f"{idx}.{ext}", response.content, content_type))
                            await asyncio.sleep(page_delay)

                    refreshed = await db.execute(select(ImportJobItem).where(ImportJobItem.id == item.id).limit(1))
                    latest_item = refreshed.scalar_one_or_none()
                    if latest_item is None:
                        raise ValueError("Import item lost during execution")

                    episode = await import_service.create_episode_from_remote_pages(
                        db=db,
                        project_id=job.project_id,
                        branch_id=job.branch_id,
                        external_series_id=job.external_series_id or "",
                        item=latest_item,
                        page_payloads=page_payloads,
                    )
                    imported_count += 1
                    if auto_understand:
                        run = await generation_service.create_generation_run(
                            db, episode_id=episode.id, stage="understand", backend="openai"
                        )
                        from workers.tasks.understand import summarize_episode

                        summarize_episode.delay(str(run.id), episode.id)
                    logger.info(
                        "MangaDex import item done job_id=%s item_id=%s episode_id=%s page_count=%s",
                        job_id,
                        item.id,
                        episode.id,
                        len(page_payloads),
                    )
                    trace_logger.info(
                        "import item done job_id=%s item_id=%s episode_id=%s page_count=%s",
                        job_id,
                        item.id,
                        episode.id,
                        len(page_payloads),
                    )
                except Exception as item_error:  # noqa: BLE001
                    failed_count += 1
                    await import_service.set_item_failed(db, item.id, str(item_error))
                    logger.exception("Import chapter failed for item=%s", item.id)
                    trace_logger.exception("import item failed job_id=%s item_id=%s", job_id, item.id)

            if failed_count > 0 and imported_count > 0:
                await import_service.complete_job_run(db, job_id, status="partial_succeeded", error=None)
            elif failed_count > 0:
                await import_service.complete_job_run(db, job_id, status="failed", error="全部导入失败")
            else:
                maybe_paused = await import_service.get_import_job(db, job.project_id, job_id)
                status = "paused" if maybe_paused and maybe_paused.status == "paused" else "succeeded"
                await import_service.complete_job_run(db, job_id, status=status, error=None)
            logger.info("MangaDex import worker finished job_id=%s imported=%s failed=%s", job_id, imported_count, failed_count)
            trace_logger.info("import worker finished job_id=%s imported=%s failed=%s", job_id, imported_count, failed_count)
        except Exception as exc:  # noqa: BLE001
            await import_service.complete_job_run(db, job_id, status="failed", error=str(exc))
            trace_logger.exception("import worker failed job_id=%s", job_id)
            raise
