from __future__ import annotations

import asyncio
import io
import json
import re
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import FlowBrowser, FlowBrowserJob, FlowExtensionKey, ModelProvider
from app.providers import google_flow as flow
from app.schemas.google_flow import FlowAccount
from app.services import storage_service

router = APIRouter()
desktop = Path(__file__).resolve().parents[1] / "providers" / "flow_desktop.py"
extension_dir = Path(__file__).resolve().parents[1] / "flow_extension"
extension_files = ("manifest.json", "background.js", "protocol.js", "flow.js", "popup.html", "popup.js", "popup.css")


class Pair(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class Poll(BaseModel):
    ready: bool


class Finish(BaseModel):
    project: UUID | None = None
    project_url: str = Field(default="", max_length=512)
    name: str = Field(default="", max_length=120)
    error: str = Field(default="", max_length=500)
    uncertain: bool = False


class Progress(BaseModel):
    waiting_for: Literal["upload_rights"] | None = None
    project_url: str = Field(default="", max_length=512)


def project_link(url: str, project: str | UUID | None) -> dict:
    # Preserve the UI's route in a multi-login browser. Only an official link to this exact project can be shown.
    root = r"(?:flow\.google(?:\.com)?(?:/u/\d+)?|labs\.google/fx/(?:[\w-]+/)?tools/flow)"
    if project and re.fullmatch(rf"https://{root}/project/{re.escape(str(project))}/?", url):
        return {"project_url": url}
    return {}


@router.get("/accounts", response_model=list[FlowAccount])
async def accounts(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(ModelProvider.id, ModelProvider.name, FlowBrowser)
        .select_from(ModelProvider)
        .outerjoin(FlowBrowser)
        .where(ModelProvider.preset_key == flow.PRESET, ModelProvider.enabled.is_(True))
        .order_by(ModelProvider.created_at.desc(), ModelProvider.id)
    )
    return [
        {
            "id": provider_id,
            "name": name,
            "status": flow.connection_status(browser),
            "connection_id": browser.session_id if browser else None,
        }
        for provider_id, name, browser in rows
    ]


@router.get("/connector")
def connector():
    return FileResponse(desktop, filename="mangaforge_flow.py", media_type="application/octet-stream")


@router.get("/extension.zip")
def download_extension(server: str = ""):
    preset = server.rstrip("/")
    if preset:
        try:
            u = urlsplit(preset)
            if (
                len(preset) > 512
                or u.scheme not in {"http", "https"}
                or not u.hostname
                or u.username
                or u.password
                or u.query
                or u.fragment
                or u.path
                or "\\" in preset
            ):
                raise ValueError()
            _ = u.port
        except ValueError as exc:
            raise HTTPException(422, "预填地址须为 MangaForge 的站点地址") from exc
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in extension_files:
            if name == "manifest.json" and preset:
                manifest = json.loads((extension_dir / name).read_text())
                manifest["homepage_url"] = preset + "/"
                archive.writestr(name, json.dumps(manifest, ensure_ascii=False))
            else:
                archive.write(extension_dir / name, name)
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="MangaForge-Flow.zip"',
            "Cache-Control": "no-cache",
        },
    )


def model_center(request: Request, x_mangaforge_manage: str = Header(default="")):
    if (
        x_mangaforge_manage != "flow-extension"
        or request.headers.get("sec-fetch-site") == "cross-site"
        or request.headers.get("origin", "").startswith("chrome-extension:")
    ):
        raise HTTPException(403, "请在 MangaForge 模型中心管理扩展令牌")


@router.get("/browsers/{provider_id}/extension-token")
async def key_status(provider_id: str, db: AsyncSession = Depends(get_db)):
    key = await db.get(FlowExtensionKey, provider_id)
    return {"issued": bool(key)}


@router.post("/browsers/{provider_id}/extension-token", dependencies=[Depends(model_center)])
async def issue_key(provider_id: str, response: Response, db: AsyncSession = Depends(get_db)):
    try:
        response.headers["Cache-Control"] = "no-store"
        return {"token": await flow.extension_key(db, provider_id)}
    except flow.FlowError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/browsers/{provider_id}/extension-token", status_code=204, dependencies=[Depends(model_center)])
async def revoke_key(provider_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await flow.extension_key(db, provider_id, revoke=True)
    except flow.FlowError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/extension/connect")
async def connect_extension(
    x_flow_runner: UUID = Header(),
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await flow.connect_extension(db, authorization, str(x_flow_runner))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except flow.FlowError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/browsers/{provider_id}/pair")
async def pair(provider_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return {"code": await flow.pair_code(db, provider_id)}
    except flow.FlowError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/browsers/{provider_id}/connect")
async def connect(provider_id: str, data: Pair, db: AsyncSession = Depends(get_db)):
    try:
        return {"token": await flow.connect(db, provider_id, data.code)}
    except flow.FlowError as exc:
        raise HTTPException(403, str(exc)) from exc


async def authenticated(
    provider_id: str,
    authorization: str = Header(default=""),
    x_flow_runner: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await flow.authenticate(db, provider_id, authorization, x_flow_runner)
    except flow.FlowError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/browsers/{provider_id}/next")
async def next_job(
    data: Poll,
    x_flow_runner: UUID = Header(),
    browser: FlowBrowser = Depends(authenticated),
    db: AsyncSession = Depends(get_db),
):
    return {"job": await flow.claim(db, browser, str(x_flow_runner), data.ready)}


@router.post("/browsers/{provider_id}/presence")
async def presence(data: Poll, browser: FlowBrowser = Depends(authenticated), db: AsyncSession = Depends(get_db)):
    browser.ready, browser.last_seen = data.ready, flow.now()
    await db.commit()
    return {"ready": browser.ready}


async def owned_job(
    job_id: UUID,
    x_flow_runner: UUID = Header(),
    browser: FlowBrowser = Depends(authenticated),
    db: AsyncSession = Depends(get_db),
) -> FlowBrowserJob:
    job = await db.get(FlowBrowserJob, str(job_id), with_for_update=True)
    if not job or job.provider_id != browser.provider_id or job.session_id != browser.session_id:
        raise HTTPException(404, "找不到该浏览器任务")
    if job.runner != str(x_flow_runner) or job.status == "queued":
        raise HTTPException(409, "任务已由另一连接器接管")
    return job


jobs = "/browsers/{provider_id}/jobs/{job_id}"


@router.post(jobs + "/heartbeat")
async def heartbeat(
    data: Progress | None = None,
    job: FlowBrowserJob = Depends(owned_job),
    browser: FlowBrowser = Depends(authenticated),
    db: AsyncSession = Depends(get_db),
):
    browser.last_seen = flow.now()
    job.lease_until = flow.now() + timedelta(seconds=70)
    if job.status == "running" and job.action == "upload" and data and "waiting_for" in data.model_fields_set:
        job.result = {"waiting_for": data.waiting_for, **project_link(data.project_url, job.payload["project"])}
    await db.commit()
    return {"status": job.status}


@router.get(jobs + "/inputs/{index}")
async def source(index: int, job: FlowBrowserJob = Depends(owned_job)):
    keys = job.payload.get("input_keys", [])
    if not 0 <= index < len(keys):
        raise HTTPException(404, "未找到任务素材")
    data = await asyncio.to_thread(storage_service.get_object_bytes, settings.MINIO_BUCKET, keys[index])
    if not data:
        raise HTTPException(404, "素材已不可用")
    try:
        data = await asyncio.to_thread(flow.reference_bytes, data)
    except flow.FlowError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(data, media_type="application/octet-stream")


@router.post(jobs + "/finish")
async def finish(data: Finish, job: FlowBrowserJob = Depends(owned_job), db: AsyncSession = Depends(get_db)):
    if job.status != "running":
        return {"status": job.status}
    if data.error:
        job.status = "failed"
        job.result = {"error": data.error, "uncertain": data.uncertain}
    elif job.action == "project" and data.project:
        job.status = "succeeded"
        job.result = {"project": str(data.project), **project_link(data.project_url, data.project)}
    elif job.action == "upload" and re.fullmatch(r"mf-[a-f0-9]{64}\.(jpg|png|webp)", data.name):
        if not data.name.startswith(f"mf-{job.payload['digest']}."):
            raise HTTPException(422, "素材摘要不匹配")
        job.status = "succeeded"
        job.result = {"name": data.name, **project_link(data.project_url, job.payload["project"])}
    else:
        raise HTTPException(422, "任务结果缺少素材或项目")
    await db.commit()
    return {"status": job.status}


@router.put(jobs + "/media")
async def media(request: Request, job: FlowBrowserJob = Depends(owned_job), db: AsyncSession = Depends(get_db)):
    if job.status != "running":
        return {"status": job.status}
    if job.action not in {"image", "video"}:
        raise HTTPException(422, "任务类型不接收媒体")
    buf = io.BytesIO()
    async for part in request.stream():
        if buf.tell() + len(part) > 120 * 1024 * 1024:
            raise HTTPException(413, "单个媒体文件超过 120 MiB")
        buf.write(part)
    raw = buf.getvalue()
    if zipfile.is_zipfile(buf):
        try:
            with zipfile.ZipFile(buf) as archive:
                extensions = {".mp4"} if job.action == "video" else {".png", ".jpg", ".jpeg", ".webp"}
                items = [
                    i for i in archive.infolist() if not i.is_dir() and Path(i.filename).suffix.lower() in extensions
                ]
                if len(items) != 1 or items[0].file_size > 120 * 1024 * 1024:
                    raise HTTPException(422, "Flow 下载包须包含单个预期媒体文件")
                with archive.open(items[0]) as entry:
                    raw = entry.read(120 * 1024 * 1024 + 1)
                if len(raw) > 120 * 1024 * 1024:
                    raise HTTPException(413, "单个媒体文件超过 120 MiB")
        except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
            raise HTTPException(422, "无法读取 Flow 下载包") from exc
    if job.action == "video":
        if len(raw) < 16 or raw[4:8] != b"ftyp":
            raise HTTPException(422, "未收到 MP4 视频")
        ext, mime = "mp4", "video/mp4"
    else:
        try:
            with Image.open(io.BytesIO(raw)) as im:
                out = io.BytesIO()
                im.save(out, format="PNG")
            raw = out.getvalue()
        except (OSError, ValueError) as exc:
            raise HTTPException(422, "未收到有效图片") from exc
        ext, mime = "png", "image/png"
    key = f"flow/browser/{job.id}.{ext}"
    await asyncio.to_thread(storage_service.upload_file, settings.MINIO_BUCKET, key, raw, mime)
    job.status, job.result = "succeeded", {"output_key": key}
    await db.commit()
    return {"status": job.status}
