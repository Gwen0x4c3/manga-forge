"""Local job queue for the browser that the user pairs with MangaForge. Google login stays in Chrome."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from hmac import compare_digest

from PIL import Image, ImageOps
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FlowBrowser, FlowBrowserJob, FlowExtensionKey, GenerationRun, ModelProvider

PRESET = "google_flow_browser"
LEGACY = "google_flow"
FLOW_URL = "https://flow.google.com/"
IMAGE_MODELS = ("nano-banana-2-lite", "nano-banana-2", "nano-banana-pro")
VIDEO_REF_LIMIT = {"veo-3.1-lite": 3, "omni-flash-1.2": 10}
OFFLINE = "请在安装 MangaForge 扩展的浏览器打开 Google Flow，并检查扩展的连接状态。"


class FlowError(ValueError):
    pass


def reference_bytes(data: bytes) -> bytes:
    """Keep supported originals byte-identical; normalize other formats before hashing and uploading."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format in {"PNG", "JPEG", "WEBP"} and len(data) <= 20_000_000:
                return data
            rgb = ImageOps.exif_transpose(image).convert("RGB")
            rgb.thumbnail((4096, 4096))
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=90)
            return out.getvalue()
    except (OSError, ValueError) as exc:
        raise FlowError("无法读取该参考图片") from exc


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def online(browser: FlowBrowser | None) -> bool:
    return bool(browser and browser.last_seen and browser.last_seen > now() - timedelta(seconds=65))


def connection_status(browser: FlowBrowser | None) -> str:
    if not browser or not browser.session_id:
        return "unpaired"
    if not online(browser):
        return "offline"
    return "ready" if browser.ready else "login_required"


async def locked_browser(db: AsyncSession, provider_id: str) -> FlowBrowser:
    row = (
        await db.execute(
            select(FlowBrowser)
            .join(ModelProvider)
            .where(
                FlowBrowser.provider_id == provider_id,
                ModelProvider.preset_key == PRESET,
                ModelProvider.enabled.is_(True),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if not row:
        raise FlowError("所选 Flow 连接已移除或停用，请刷新并选择可用的连接")
    return row


async def pair_code(db: AsyncSession, provider_id: str) -> str:
    browser = await locked_browser(db, provider_id)
    code = secrets.token_urlsafe(24)
    browser.pair_hash, browser.pair_until = digest(code), now() + timedelta(minutes=10)
    await db.commit()
    return code


async def connect(db: AsyncSession, provider_id: str, code: str) -> str:
    browser = await locked_browser(db, provider_id)
    if (
        not browser.pair_until
        or browser.pair_until < now()
        or not compare_digest(browser.pair_hash or "", digest(code))
    ):
        raise FlowError("配对码无效或已过期")
    token = secrets.token_urlsafe(40)
    await db.execute(delete(FlowExtensionKey).where(FlowExtensionKey.provider_id == provider_id))
    browser.pair_hash, browser.pair_until = None, None
    browser.session_id, browser.token_hash = str(uuid.uuid4()), digest(token)
    browser.last_seen, browser.ready = None, False
    await db.commit()
    return token


async def authenticate(db: AsyncSession, provider_id: str, authorization: str, runner: str = "") -> FlowBrowser:
    browser = await locked_browser(db, provider_id)
    if not authorization.startswith("Bearer ") or not compare_digest(
        browser.token_hash or "", digest(authorization[7:])
    ):
        raise FlowError("本地连接器未配对或已由其他浏览器替换")
    if authorization.startswith("Bearer mf_flow."):
        key = await db.get(FlowExtensionKey, provider_id)
        if not key or key.installation != runner:
            raise FlowError("此扩展令牌已撤销或绑定在另一个浏览器")
        key.account_hash = None  # Discard a fingerprint saved by the 1.0 extension.
    return browser


async def no_active_jobs(db: AsyncSession, browser: FlowBrowser):
    if not browser.session_id:
        return
    job = await db.execute(
        select(FlowBrowserJob.id)
        .where(
            FlowBrowserJob.provider_id == browser.provider_id,
            FlowBrowserJob.session_id == browser.session_id,
            FlowBrowserJob.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    run = await db.execute(
        select(GenerationRun.id)
        .where(
            GenerationRun.stage == "google_flow",
            GenerationRun.status.in_(("queued", "running")),
            GenerationRun.params["browser_session"].as_string() == browser.session_id,
        )
        .limit(1)
    )
    if job.scalar_one_or_none() or run.scalar_one_or_none():
        raise FlowError("当前连接还有媒体任务，请在任务结束后切换")


async def extension_key(db: AsyncSession, provider_id: str, *, revoke: bool = False) -> str | None:
    browser = await locked_browser(db, provider_id)
    key = await db.get(FlowExtensionKey, provider_id)
    if key and key.token_hash == browser.token_hash:
        if not revoke:
            await no_active_jobs(db, browser)
        browser.session_id = browser.token_hash = browser.last_seen = None
        browser.ready = False
    token = None
    if revoke:
        await db.execute(delete(FlowExtensionKey).where(FlowExtensionKey.provider_id == provider_id))
    else:
        token = f"mf_flow.{provider_id}.{secrets.token_urlsafe(32)}"
        if not key:
            key = FlowExtensionKey(provider_id=provider_id)
            db.add(key)
        key.token_hash, key.installation, key.account_hash = digest(token), None, None
    await db.commit()
    return token


async def connect_extension(db: AsyncSession, authorization: str, runner: str) -> dict:
    parts = authorization.removeprefix("Bearer ").split(".")
    if not authorization.startswith("Bearer mf_flow.") or len(parts) != 3:
        raise PermissionError("MangaForge 扩展令牌无效")
    try:
        provider_id = str(uuid.UUID(parts[1]))
        browser = await locked_browser(db, provider_id)
    except (ValueError, FlowError) as exc:
        raise PermissionError("MangaForge 扩展令牌无效") from exc
    key = await db.get(FlowExtensionKey, provider_id)
    if not key or not compare_digest(key.token_hash, digest(authorization[7:])):
        raise PermissionError("MangaForge 扩展令牌无效或已撤销")
    if not key.installation:
        await no_active_jobs(db, browser)
        key.installation = runner
        browser.session_id, browser.token_hash = str(uuid.uuid4()), key.token_hash
        browser.pair_hash = browser.pair_until = None
    elif key.installation != runner or browser.token_hash != key.token_hash:
        raise FlowError("该令牌已绑定其他扩展安装。如需更换浏览器，请在模型中心更换令牌")
    key.account_hash = None
    browser.last_seen, browser.ready = now(), False  # The extension reports its Flow tab on its next poll.
    provider = await db.get(ModelProvider, provider_id)
    await db.commit()
    return {"provider_id": provider_id, "name": provider.name, "session": browser.session_id}


async def enqueue(
    db: AsyncSession, provider_id: str, session: str, action: str, key: str, payload: dict
) -> FlowBrowserJob:
    # Lock before lookup. Concurrent episodes can share a project and the same uploaded character portrait.
    browser = await locked_browser(db, provider_id)
    if browser.session_id != session or not session:
        raise FlowError("浏览器配对已变更，请用新连接创建任务")
    job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"mangaforge/flow/{provider_id}/{session}/{action}/{key}"))
    job = await db.get(FlowBrowserJob, job_id, with_for_update=True, populate_existing=True)
    if job:
        if action in {"project", "upload"} and job.status == "failed" and online(browser) and browser.ready:
            job.status, job.result, job.runner, job.lease_until = "queued", None, None, None
        return job
    if not online(browser) or not browser.ready:
        raise FlowError(OFFLINE)
    job = FlowBrowserJob(id=job_id, provider_id=provider_id, session_id=session, action=action, payload=payload)
    db.add(job)
    await db.flush()
    return job


async def claim(db: AsyncSession, browser: FlowBrowser, runner: str, ready: bool) -> dict | None:
    browser.last_seen, browser.ready = now(), ready
    query = select(FlowBrowserJob).where(
        FlowBrowserJob.provider_id == browser.provider_id, FlowBrowserJob.session_id == browser.session_id
    )
    job = (await db.execute(query.where(FlowBrowserJob.status == "running").with_for_update())).scalar_one_or_none()
    again = bool(job)
    if job and job.runner != runner and job.lease_until and job.lease_until > now():
        job = None
    elif job is None and ready:
        job = (
            await db.execute(
                query.where(FlowBrowserJob.status == "queued")
                .order_by(FlowBrowserJob.created_at, FlowBrowserJob.id)
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
    data = None
    if job and ready:
        job.runner, job.lease_until, job.status = runner, now() + timedelta(seconds=70), "running"
        data = {
            "id": job.id,
            "action": job.action,
            "redelivered": again,
            **{k: v for k, v in job.payload.items() if k != "input_keys"},
            "input_count": len(job.payload.get("input_keys", [])),
        }
    await db.commit()
    return data


async def wait_result(db: AsyncSession, job: FlowBrowserJob) -> dict:
    job_id = job.id
    while True:
        job = await db.get(FlowBrowserJob, job_id, populate_existing=True)
        if not job:
            raise FlowError("浏览器任务不存在")
        if job.status == "failed":
            raise FlowError((job.result or {}).get("error", "浏览器任务失败"))
        if job.status == "succeeded":
            return job.result or {}
        device = await locked_browser(db, job.provider_id)
        if device.session_id != job.session_id:
            raise FlowError("任务所属的浏览器配对已变更")
        if (not online(device) or not device.ready) and (now() - job.created_at) > timedelta(minutes=2):
            if job.status == "queued":
                job.status, job.result = "failed", {"error": "浏览器离线，任务尚未领取"}
                await db.commit()
            raise FlowError("连接器离线或等待登录，请在 Flow 项目核对任务状态")
        await db.commit()
        await asyncio.sleep(2)


async def generate_image(
    provider_id: str, model: str, prompt: str, ratio: str, refs: list[tuple], project_id: str | None = None
) -> bytes:
    from app.config import settings
    from app.core.telemetry import get_usage_context
    from app.database import worker_session
    from app.models import Project
    from app.services import storage_service

    if model not in IMAGE_MODELS or len(refs) > 10:
        raise FlowError("请选择 Flow 的 Nano Banana 模型，每次最多使用 10 张参考图")
    async with worker_session() as db:
        device = await locked_browser(db, provider_id)
        if not online(device) or not device.ready:
            raise FlowError(OFFLINE)
        session = device.session_id
        project = await db.get(Project, project_id) if project_id else None
        scope = project.id if project else "illustrations"
        workspace = await enqueue(
            db,
            provider_id,
            session,
            "project",
            scope,
            {"workspace": scope, "title": project.title if project else "MangaForge 原画"},
        )
        await db.commit()
        remote = (await wait_result(db, workspace))["project"]
        names = []
        for data, _ in refs:
            data = await asyncio.to_thread(reference_bytes, data)
            sha = hashlib.sha256(data).hexdigest()
            key = f"flow/references/{sha}"
            await asyncio.to_thread(storage_service.upload_file, settings.MINIO_BUCKET, key, data)
            job = await enqueue(
                db,
                provider_id,
                session,
                "upload",
                f"{remote}/{sha}",
                {"project": remote, "digest": sha, "input_keys": [key]},
            )
            await db.commit()
            names.append((await wait_result(db, job))["name"])
        spec = {
            "project": remote,
            "model": model,
            "prompt": prompt,
            "ratio": ratio,
            "references": list(dict.fromkeys(names)),
        }
        ctx = get_usage_context()
        # Retried deliveries for the same render run and panel reuse the original paid request.
        request_key = str(uuid.uuid4())
        if ctx.generation_run_id and ctx.panel_id:
            signature = digest(json.dumps(spec, sort_keys=True))
            request_key = f"{ctx.generation_run_id}/{ctx.panel_id}/{signature}"
        job = await enqueue(db, provider_id, session, "image", request_key, spec)
        await db.commit()
        key = (await wait_result(db, job))["output_key"]
        data = await asyncio.to_thread(storage_service.get_object_bytes, settings.MINIO_BUCKET, key)
        if not data:
            raise FlowError("未找到 Flow 浏览器返回的图片")
        return data
