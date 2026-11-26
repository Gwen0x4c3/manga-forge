from __future__ import annotations

import base64
import io
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape as xml_escape

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm import ensure_llm_configured, get_active_llm_config
from app.core.provider_runtime import resolve_role_config
from app.dependencies import get_db
from app.models.branch import Branch
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.generation_run import GenerationRun
from app.schemas.generation import (
    BatchUnderstandRequest,
    BatchUnderstandResponse,
    ContinueFromEpisodeRequest,
    ContinueFromEpisodeResponse,
    GeneratedImageResponse,
    GenerationRunResponse,
    LayoutRequest,
    LayoutResponse,
    PanelInpaintRequest,
    PanelRerenderRequest,
    RenderRequest,
    RenderResponse,
    ScriptGenerateRequest,
    ScriptGenerateResponse,
    StoryboardUpdateRequest,
    UnderstandRequest,
    UnderstandResponse,
)
from app.services import episode_service, generation_service, render_agent, storage_service

router = APIRouter()
celery_client = Celery(
    "mangaforge-api",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)


def _dispatch_task(task_name: str, *args):
    return celery_client.send_task(task_name, args=args)


def _serialize_run(r: GenerationRun, include_context: bool = False) -> GenerationRunResponse:
    return GenerationRunResponse(
        id=r.id,
        episode_id=r.episode_id,
        stage=r.stage,
        status=r.status,
        backend=r.backend,
        model=r.model,
        params=r.params,
        retrieved_context=r.retrieved_context if include_context else None,
        error=r.error,
        commit_message=r.commit_message,
        created_at=r.created_at.isoformat() if r.created_at else None,
        finished_at=r.finished_at.isoformat() if r.finished_at else None,
    )


@router.post("/continue", response_model=ContinueFromEpisodeResponse)
async def continue_from_episode(request: ContinueFromEpisodeRequest, db: AsyncSession = Depends(get_db)):
    ensure_llm_configured()
    base_episode = await episode_service.find_episode(
        db, request.project_id, request.branch_id, request.base_episode_number
    )
    if not base_episode:
        raise HTTPException(status_code=404, detail="Base episode not found")

    candidate_number = Decimal(int(request.base_episode_number) + 1)
    existing = await episode_service.find_episode(db, request.project_id, request.branch_id, candidate_number)
    new_number = (
        await episode_service.get_next_episode_number(db, request.project_id, request.branch_id)
        if existing
        else candidate_number
    )
    new_label = str(int(new_number)) if new_number == int(new_number) else str(new_number)

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

    main_cfg = get_active_llm_config("main_llm")
    img_cfg = resolve_role_config("image_gen")
    run = await generation_service.create_generation_run(
        db,
        episode_id=str(new_episode.id),
        stage="continue",
        backend=main_cfg.provider_key,
        model=main_cfg.model,
        params={
            "tone": request.tone,
            "base_episode_number": float(request.base_episode_number),
            "image_backend": request.image_backend or img_cfg.provider_key,
            "image_model": request.image_model or img_cfg.model,
            "image_size": request.image_size,
            "context_profile": request.context_profile or settings.DEFAULT_CONTEXT_PROFILE,
        },
    )
    try:
        task = _dispatch_task(
            "workers.pipelines.continue_pipeline.run_continue",
            str(run.id),
            str(new_episode.id),
            request.branch_id,
            float(request.base_episode_number),
            request.tone,
            request.custom_instructions,
            request.image_backend,
            request.image_model,
            request.image_size,
            request.context_profile,
        )
    except Exception as exc:
        await generation_service.update_generation_run(db, str(run.id), "failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"提交 continue 任务失败: {exc}") from exc

    return ContinueFromEpisodeResponse(
        episode_id=str(new_episode.id),
        episode_number=new_number,
        task_id=task.id,
        status="queued",
    )


@router.post("/understand", response_model=UnderstandResponse)
async def trigger_understand(request: UnderstandRequest, db: AsyncSession = Depends(get_db)):
    ensure_llm_configured()
    result = await db.execute(select(Episode).where(Episode.id == request.episode_id).limit(1))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    if await generation_service.has_active_run(db, episode.id, "understand"):
        raise HTTPException(status_code=409, detail="该章节已有正在运行的剧情理解任务")
    vision_cfg = get_active_llm_config("vision_llm")
    run = await generation_service.create_generation_run(
        db, episode_id=episode.id, stage="understand", backend=vision_cfg.provider_key, model=vision_cfg.model
    )
    try:
        task = _dispatch_task("workers.tasks.understand.summarize_episode", str(run.id), episode.id)
    except Exception as exc:
        await generation_service.update_generation_run(db, str(run.id), "failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"提交 understand 任务失败: {exc}") from exc
    return UnderstandResponse(
        task_id=task.id,
        episode_id=episode.id,
        status="queued",
    )


@router.post("/understand-batch", response_model=BatchUnderstandResponse)
async def trigger_batch_understand(request: BatchUnderstandRequest, db: AsyncSession = Depends(get_db)):
    """Understand all episodes in a branch strictly in ascending Episode.number order."""
    ensure_llm_configured()

    branch_id = request.branch_id
    if not branch_id:
        branch = (
            await db.execute(
                select(Branch).where(Branch.project_id == request.project_id, Branch.is_default.is_(True)).limit(1)
            )
        ).scalar_one_or_none()
        if not branch:
            branch = (
                await db.execute(select(Branch).where(Branch.project_id == request.project_id).limit(1))
            ).scalar_one_or_none()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        branch_id = branch.id

    stmt = select(Episode).where(Episode.project_id == request.project_id, Episode.branch_id == branch_id)
    if not request.force:
        stmt = stmt.where(Episode.status == "imported")
    stmt = stmt.order_by(Episode.number.asc())
    episodes = list((await db.execute(stmt)).scalars().all())
    ep_ids = [ep.id for ep in episodes]

    if not ep_ids:
        return BatchUnderstandResponse(
            task_id="",
            project_id=request.project_id,
            branch_id=branch_id,
            episode_ids=[],
            total=0,
            status="empty",
        )

    try:
        task = _dispatch_task(
            "workers.tasks.understand.understand_branch_sequential",
            request.project_id,
            branch_id,
            ep_ids,
            request.force,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"提交批量理解任务失败: {exc}") from exc

    return BatchUnderstandResponse(
        task_id=task.id,
        project_id=request.project_id,
        branch_id=branch_id,
        episode_ids=ep_ids,
        total=len(ep_ids),
        status="queued",
    )


@router.post("/script", response_model=ScriptGenerateResponse)
async def trigger_script_generation(request: ScriptGenerateRequest, db: AsyncSession = Depends(get_db)):
    ensure_llm_configured()
    result = await db.execute(select(Episode).where(Episode.id == request.episode_id).limit(1))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    if await generation_service.has_active_run(db, episode.id, "script"):
        raise HTTPException(status_code=409, detail="该章节已有正在运行的分镜生成任务")
    main_cfg = get_active_llm_config("main_llm")
    run = await generation_service.create_generation_run(
        db,
        episode_id=episode.id,
        stage="script",
        backend=main_cfg.provider_key,
        model=main_cfg.model,
        params={
            "tone": request.tone,
            "base_episode_number": float(request.base_episode_number),
            "context_profile": request.context_profile or settings.DEFAULT_CONTEXT_PROFILE,
        },
    )
    try:
        task = _dispatch_task(
            "workers.tasks.script_gen.generate_script",
            str(run.id),
            episode.id,
            request.branch_id,
            float(request.base_episode_number),
            request.tone,
            request.custom_instructions,
            request.context_profile,
        )
    except Exception as exc:
        await generation_service.update_generation_run(db, str(run.id), "failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"提交 script 任务失败: {exc}") from exc
    return ScriptGenerateResponse(
        task_id=task.id,
        episode_id=episode.id,
        status="queued",
    )


@router.put("/episodes/{episode_id}/storyboard")
async def update_episode_storyboard(
    episode_id: str,
    request: StoryboardUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    episode = await episode_service.get_episode(db, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    memory = await generation_service.save_storyboard(db, episode_id, request.storyboard)
    title = (request.storyboard.get("title") or "").strip()
    if title:
        episode.title = title[:255]
    if episode.status == "draft":
        episode.status = "scripted"
    await db.commit()
    return {"id": memory.id, "episode_id": episode_id, "storyboard": memory.content}


@router.get("/runs/{run_id}", response_model=GenerationRunResponse)
async def get_generation_run(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id).limit(1))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Generation run not found")
    return _serialize_run(run, include_context=True)


@router.get("/episodes/{episode_id}/runs")
async def list_episode_runs(episode_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GenerationRun).where(GenerationRun.episode_id == episode_id).order_by(GenerationRun.created_at.desc())
    )
    runs = result.scalars().all()
    return {"items": [_serialize_run(r, include_context=True) for r in runs]}


@router.post("/render", response_model=RenderResponse)
async def trigger_render(request: RenderRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Episode).where(Episode.id == request.episode_id).limit(1))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    if await generation_service.has_active_run(db, episode.id, "render"):
        raise HTTPException(status_code=409, detail="该章节已有正在运行的生图任务")

    storyboard_memory_id = request.storyboard_memory_id
    if storyboard_memory_id:
        mem_result = await db.execute(select(EpisodeMemory).where(EpisodeMemory.id == storyboard_memory_id).limit(1))
        memory = mem_result.scalar_one_or_none()
        if not memory or memory.type != "storyboard_json":
            raise HTTPException(status_code=400, detail="Invalid storyboard memory ID")

    img_cfg = resolve_role_config("image_gen")
    run = await generation_service.create_generation_run(
        db,
        episode_id=episode.id,
        stage="render",
        backend=request.image_backend or img_cfg.provider_key,
        model=request.image_model or img_cfg.model,
        params={"image_size": request.image_size},
    )

    try:
        task = _dispatch_task(
            "workers.tasks.render.render_episode",
            str(run.id),
            episode.id,
            request.image_backend,
            request.image_model,
            request.image_size or "1024x1024",
        )
    except Exception as exc:
        await generation_service.update_generation_run(db, str(run.id), "failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"提交 render 任务失败: {exc}") from exc

    return RenderResponse(
        task_id=task.id,
        episode_id=episode.id,
        status="queued",
        panel_count=0,
    )


@router.post("/episodes/{episode_id}/panels/{panel_id}/rerender", response_model=GeneratedImageResponse)
async def rerender_single_panel(
    episode_id: str,
    panel_id: str,
    request: PanelRerenderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Synchronously re-render a single panel and keep previous renders as selectable candidates."""
    episode = await episode_service.get_episode(db, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    storyboard_mem = await generation_service.get_latest_storyboard(db, episode_id)
    storyboard = storyboard_mem.content if storyboard_mem else None

    img_cfg = resolve_role_config("image_gen")
    run = await generation_service.create_generation_run(
        db,
        episode_id=episode.id,
        stage="render",
        backend=request.image_backend or img_cfg.provider_key,
        model=request.image_model or img_cfg.model,
        params={"panel_id": panel_id, "single_panel": True, "image_size": request.image_size or "1024x1024"},
    )
    await generation_service.update_generation_run(db, run.id, "running")
    try:
        gen_image = await render_agent.render_single_panel(
            db=db,
            episode=episode,
            storyboard=storyboard,
            run_id=run.id,
            panel_id=panel_id,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            reference_asset_ids=request.reference_asset_ids,
            image_backend_name=request.image_backend,
            image_model=request.image_model,
            image_size=request.image_size or "1024x1024",
        )
        if not gen_image:
            await generation_service.update_generation_run(db, run.id, "failed", error="Single-panel render failed")
            raise HTTPException(status_code=500, detail="Single-panel render failed")
        await generation_service.update_generation_run(
            db, run.id, "succeeded", commit_message=f"Re-rendered panel {panel_id}"
        )
    except HTTPException:
        raise
    except Exception as exc:
        await generation_service.update_generation_run(db, run.id, "failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"单格重绘失败: {exc}") from exc

    return GeneratedImageResponse(
        id=gen_image.id,
        generation_run_id=gen_image.generation_run_id,
        episode_id=gen_image.episode_id,
        panel_id=gen_image.panel_id,
        image_path=gen_image.image_path,
        meta=gen_image.meta,
        created_at=gen_image.created_at.isoformat() if gen_image.created_at else None,
    )


@router.post("/episodes/{episode_id}/panels/{panel_id}/select/{image_id}", response_model=GeneratedImageResponse)
async def select_panel_candidate(
    episode_id: str,
    panel_id: str,
    image_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Switch the active candidate image for a panel."""
    selected = await generation_service.select_generated_image(db, episode_id, panel_id, image_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Candidate image not found for this panel")
    return GeneratedImageResponse(
        id=selected.id,
        generation_run_id=selected.generation_run_id,
        episode_id=selected.episode_id,
        panel_id=selected.panel_id,
        image_path=selected.image_path,
        meta=selected.meta,
        created_at=selected.created_at.isoformat() if selected.created_at else None,
    )


@router.post("/episodes/{episode_id}/panels/{panel_id}/inpaint", response_model=GeneratedImageResponse)
async def inpaint_single_panel(
    episode_id: str,
    panel_id: str,
    request: PanelInpaintRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run mask-based local inpainting on a panel's current image and save as a new candidate."""
    from app.core.image_backend import get_image_backend

    episode = await episode_service.get_episode(db, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    active_images = await generation_service.get_generated_images(db, episode_id, include_candidates=False)
    current = next((im for im in active_images if im.panel_id == panel_id), None)
    if not current:
        raise HTTPException(status_code=404, detail=f"No rendered image found for panel {panel_id}")

    source_bytes = storage_service.get_object_bytes(settings.MINIO_BUCKET, current.image_path)
    if not source_bytes:
        raise HTTPException(status_code=404, detail="Original panel image missing from storage")

    raw_b64 = request.mask_base64.split(",", 1)[-1]
    try:
        mask_bytes = base64.b64decode(raw_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid mask_base64: {exc}") from exc

    img_cfg = resolve_role_config("image_gen")
    run = await generation_service.create_generation_run(
        db,
        episode_id=episode.id,
        stage="render",
        backend=request.image_backend or img_cfg.provider_key,
        model=request.image_model or img_cfg.model,
        params={"panel_id": panel_id, "inpaint": True},
    )
    await generation_service.update_generation_run(db, run.id, "running")
    try:
        from app.core.telemetry import usage_context

        backend = get_image_backend(backend_name=request.image_backend, model=request.image_model)
        with usage_context(
            project_id=episode.project_id,
            episode_id=episode.id,
            generation_run_id=run.id,
            operation="image_inpaint",
            panel_id=panel_id,
        ):
            result = await backend.inpaint(source_bytes, mask_bytes, request.prompt)
        object_key = storage_service.generate_object_key(f"generated/{episode.id}", f"{panel_id}_inpaint.png")
        storage_service.upload_file(settings.MINIO_BUCKET, object_key, result.image_data, content_type="image/png")
        gen_image = await generation_service.save_generated_image(
            db,
            generation_run_id=run.id,
            episode_id=episode.id,
            panel_id=panel_id,
            image_path=object_key,
            meta={
                **(current.meta or {}),
                **result.meta,
                "inpaint_prompt": request.prompt,
                "rendered_by": "inpaint",
            },
            keep_history=True,
        )
        await generation_service.update_generation_run(db, run.id, "succeeded", commit_message=f"Inpainted {panel_id}")
    except Exception as exc:
        await generation_service.update_generation_run(db, run.id, "failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"局部重绘失败: {exc}") from exc

    return GeneratedImageResponse(
        id=gen_image.id,
        generation_run_id=gen_image.generation_run_id,
        episode_id=gen_image.episode_id,
        panel_id=gen_image.panel_id,
        image_path=gen_image.image_path,
        meta=gen_image.meta,
        created_at=gen_image.created_at.isoformat() if gen_image.created_at else None,
    )


@router.post("/layout", response_model=LayoutResponse)
async def trigger_layout(request: LayoutRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Episode).where(Episode.id == request.episode_id).limit(1))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    if await generation_service.has_active_run(db, episode.id, "layout"):
        raise HTTPException(status_code=409, detail="该章节已有正在运行的排版任务")

    run = await generation_service.create_generation_run(
        db,
        episode_id=episode.id,
        stage="layout",
        params={"writing_mode": request.writing_mode, "sync": request.sync},
    )

    if request.sync:
        from workers.tasks.layout import _layout_episode_with_db

        try:
            pages = await _layout_episode_with_db(
                db=db,
                self_task=None,
                run_id=str(run.id),
                episode_id=episode.id,
                template_override=request.template_override,
                trigger_writeback=False,
                writing_mode=request.writing_mode,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"同步排版失败: {exc}") from exc
        return LayoutResponse(
            task_id=str(run.id),
            episode_id=episode.id,
            status="succeeded",
            page_count=len(pages),
            pages=pages,
        )

    try:
        task = _dispatch_task(
            "workers.tasks.layout.layout_episode",
            str(run.id),
            episode.id,
            request.template_override,
            True,
            request.writing_mode,
        )
    except Exception as exc:
        await generation_service.update_generation_run(db, str(run.id), "failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"提交 layout 任务失败: {exc}") from exc

    return LayoutResponse(
        task_id=task.id,
        episode_id=episode.id,
        status="queued",
        page_count=0,
    )


@router.get("/episodes/{episode_id}/images")
async def list_generated_images(
    episode_id: str,
    include_candidates: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    images = await generation_service.get_generated_images(db, episode_id, include_candidates=include_candidates)
    return {
        "items": [
            GeneratedImageResponse(
                id=img.id,
                generation_run_id=img.generation_run_id,
                episode_id=img.episode_id,
                panel_id=img.panel_id,
                image_path=img.image_path,
                meta=img.meta,
                created_at=img.created_at.isoformat() if img.created_at else None,
            )
            for img in images
        ]
    }


@router.get("/episodes/{episode_id}/layout")
async def get_episode_layout(episode_id: str, db: AsyncSession = Depends(get_db)):
    layout = await generation_service.get_layout_result(db, episode_id)
    if not layout:
        return {"pages": []}
    return {"pages": layout.content.get("pages", [])}


def _build_cbz_bytes(
    page_blobs: list[tuple[int, bytes]],
    title: str,
    number: str,
    series: str = "MangaForge",
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, (page_no, raw) in enumerate(page_blobs, start=1):
            zf.writestr(f"{idx:03d}_p{page_no:02d}.png", raw)
        comic_info = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<ComicInfo>\n"
            f"  <Series>{xml_escape(series)}</Series>\n"
            f"  <Title>{xml_escape(title)}</Title>\n"
            f"  <Number>{xml_escape(number)}</Number>\n"
            f"  <PageCount>{len(page_blobs)}</PageCount>\n"
            "  <Manga>YesAndRightToLeft</Manga>\n"
            "  <Notes>Generated by MangaForge</Notes>\n"
            "</ComicInfo>\n"
        )
        zf.writestr("ComicInfo.xml", comic_info.encode("utf-8"))
    return buf.getvalue()


def _build_webtoon_bytes(images: list) -> bytes:
    from PIL import Image

    target_w = max(im.width for im in images)
    gap = 28
    resized = []
    for im in images:
        if im.width != target_w:
            new_h = max(1, int(im.height * (target_w / im.width)))
            resized.append(im.resize((target_w, new_h), Image.Resampling.LANCZOS))
        else:
            resized.append(im)
    total_h = sum(im.height for im in resized) + gap * (len(resized) + 1)
    strip = Image.new("RGB", (target_w, total_h), color=(255, 255, 255))
    y = gap
    for im in resized:
        strip.paste(im, (0, y))
        y += im.height + gap
    buf = io.BytesIO()
    strip.save(buf, format="PNG")
    return buf.getvalue()


@router.get("/episodes/{episode_id}/export")
async def export_episode(episode_id: str, format: str = "pdf", db: AsyncSession = Depends(get_db)):
    """Export an episode's composed final pages as PDF, CBZ (ComicInfo.xml), or stitched Webtoon PNG."""
    fmt = format.lower()
    if fmt not in ("pdf", "cbz", "webtoon"):
        raise HTTPException(status_code=400, detail="Supported formats: pdf, cbz, webtoon")

    episode = await episode_service.get_episode(db, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    layout = await generation_service.get_layout_result(db, episode_id)
    if not layout or not layout.content.get("pages"):
        raise HTTPException(status_code=404, detail="No composed pages yet — run layout first")

    from PIL import Image

    pages = sorted(layout.content.get("pages", []), key=lambda p: p.get("page_number", 0))
    page_blobs: list[tuple[int, bytes]] = []
    images: list[Image.Image] = []
    for page in pages:
        data = storage_service.get_object_bytes(settings.MINIO_BUCKET, page.get("image_path", ""))
        if data is None:
            continue
        page_blobs.append((int(page.get("page_number", len(page_blobs) + 1)), data))
        images.append(Image.open(io.BytesIO(data)).convert("RGB"))
    if not images:
        raise HTTPException(status_code=404, detail="Composed page images missing from object storage")

    label = episode.label or str(episode.number)
    if fmt == "cbz":
        cbz_bytes = _build_cbz_bytes(
            page_blobs,
            title=episode.title or f"Episode {label}",
            number=str(label),
        )
        return Response(
            content=cbz_bytes,
            media_type="application/vnd.comicbook+zip",
            headers={"Content-Disposition": f'attachment; filename="episode_{label}.cbz"'},
        )

    if fmt == "webtoon":
        webtoon_bytes = _build_webtoon_bytes(images)
        return Response(
            content=webtoon_bytes,
            media_type="image/png",
            headers={"Content-Disposition": f'attachment; filename="episode_{label}_webtoon.png"'},
        )

    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:])
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="episode_{label}.pdf"'},
    )
