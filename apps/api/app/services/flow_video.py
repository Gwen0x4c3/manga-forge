from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Episode, FlowBrowserJob, GenerationRun, Project
from app.providers import google_flow as browser
from app.providers.google_flow import FlowError
from app.schemas.google_flow import FlowStart
from app.services import storage_service
from app.services.flow_plan import build_plan
from app.services.generation_service import create_generation_run

STAGE = "google_flow"
ACTIVE = ("queued", "running")


async def active_run(db: AsyncSession, episode_id: str) -> GenerationRun | None:
    return (
        await db.execute(
            select(GenerationRun)
            .where(
                GenerationRun.episode_id == episode_id, GenerationRun.stage == STAGE, GenerationRun.status.in_(ACTIVE)
            )
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def start_run(db: AsyncSession, ep: Episode, spec: FlowStart) -> tuple[GenerationRun, bool]:
    # Serialize starts and resumes for this episode, across API processes.
    await db.execute(select(Episode.id).where(Episode.id == ep.id).with_for_update())
    existing = (
        await db.execute(
            select(GenerationRun)
            .where(
                GenerationRun.episode_id == ep.id,
                GenerationRun.stage == STAGE,
                GenerationRun.params["request_id"].as_string() == str(spec.request_id),
            )
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing:
        return existing, False
    if await active_run(db, ep.id):
        raise FlowError("本话已有 Flow 任务在执行")
    device = await browser.locked_browser(db, spec.provider_id)
    if spec.connection_id is not None and device.session_id != spec.connection_id:
        raise FlowError("所选 Flow 扩展连接已更新，请刷新后重新提交")
    if not browser.online(device) or not device.ready:
        raise FlowError(browser.OFFLINE)
    plan = await build_plan(db, ep, spec)
    if not plan.shots:
        raise FlowError("请先导入漫画页，或生成本话分镜原画")
    if plan.plan_id != spec.plan_id:
        raise FlowError("本话画面或素材已变化，请刷新镜头方案")
    if spec.prompts is not None:
        if len(spec.prompts) != len(plan.shots):
            raise FlowError("提示词数量与镜头数不一致")
        for shot, prompt in zip(plan.shots, spec.prompts):
            shot.prompt = prompt

    params = {
        **spec.model_dump(exclude={"prompts", "connection_id"}, mode="json"),
        **plan.model_dump(),
        "browser_session": device.session_id,
        "project_title": (await db.get(Project, ep.project_id)).title,
        "project_id": ep.project_id,
    }
    run = await create_generation_run(db, ep.id, stage=STAGE, backend=browser.PRESET, model=spec.model, params=params)
    return run, True


def describe(run: GenerationRun) -> dict:
    p = run.params or {}
    shots = p["shots"]
    return {
        "id": run.id,
        "provider_id": p.get("provider_id"),
        "connection_id": p.get("browser_session"),
        "status": run.status,
        "error": run.error,
        "mode": p["mode"],
        "model": run.model,
        "synced": sum(bool(s.get("media_id")) for s in p["sources"]),
        "sources": len(p["sources"]),
        "completed": sum(bool(s.get("video_id")) for s in shots),
        "clips": len(shots),
        "project_title": p.get("remote_title"),
        "remote_id": p.get("remote_id"),
        "project_url": p.get("project_url"),
        "waiting_for": p.get("waiting_for") if run.status == "running" else None,
        "output_key": p.get("output_key"),
        "created_at": run.created_at,
        "uncertain": bool(p.get("uncertain")),
        "legacy": not p.get("browser_session"),
    }


async def resume_run(
    db: AsyncSession, ep: Episode, run_id: str, retry_uncertain: bool = False, provider_id: str | None = None
) -> tuple[GenerationRun, bool]:
    await db.execute(select(Episode.id).where(Episode.id == ep.id).with_for_update())
    run = (
        await db.execute(
            select(GenerationRun)
            .where(GenerationRun.id == run_id, GenerationRun.stage == STAGE, GenerationRun.episode_id == ep.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not run:
        raise FlowError("未找到本话的 Flow 任务")
    if run.status != "failed":
        return run, False
    if await active_run(db, ep.id):
        raise FlowError("请等待本话正在执行的 Flow 任务结束")
    params = deepcopy(run.params)
    if not params.get("browser_session"):
        raise FlowError("这是旧版任务。请用浏览器直连创建新任务")
    if provider_id is not None and provider_id != params.get("provider_id"):
        raise FlowError("此任务属于另一个 Flow 连接，请选择原连接继续或创建新任务")
    try:
        device = await browser.locked_browser(db, params["provider_id"])
    except FlowError:
        device = None
    if not device or device.session_id != params["browser_session"]:
        action = "请用当前连接重新同步素材" if params["mode"] == "sync" else "请先查看原 Flow 项目的镜头再新建视频任务"
        raise FlowError(f"此任务的原 Flow 连接已失效。{action}")
    if not browser.online(device) or not device.ready:
        raise FlowError("请打开本次任务使用的 Flow 标签页，待原连接上线后继续")
    if params.get("uncertain") and not retry_uncertain:
        raise FlowError("请先在 Flow 核对上次提交，再确认重试")
    job = await db.get(FlowBrowserJob, params["pending_job"]) if params.get("pending_job") else None
    if job and job.status == "failed":
        if job.action in {"video", "image"}:
            params["attempt"] = params.get("attempt", 0) + 1
        else:
            job.status, job.result, job.runner, job.lease_until = "queued", None, None, None
        params.pop("pending_job", None)
    params.pop("uncertain", None)
    params.pop("waiting_for", None)
    run.params, run.status, run.error, run.finished_at = params, "queued", None, None
    await db.commit()
    return run, True


def join_files(directory: Path, parts: list[str], target: Path):
    manifest = directory / "clips.txt"
    manifest.write_text("".join(f"file '{name}'\n" for name in parts))
    proc = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(manifest),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(target),
        ],
        capture_output=True,
        timeout=600,
    )
    if proc.returncode:
        raise FlowError("FFmpeg 拼接视频失败，请检查 Worker 上的 FFmpeg")


async def export_video(keys: list[str], output_key: str):
    with tempfile.TemporaryDirectory(prefix="mangaforge-flow-") as temp:
        directory = Path(temp)
        parts = []
        for i, key in enumerate(keys):
            raw = await asyncio.to_thread(storage_service.get_object_bytes, settings.MINIO_BUCKET, key)
            if not raw:
                raise FlowError("未找到已生成的镜头文件")
            if len(keys) == 1:
                await asyncio.to_thread(
                    storage_service.upload_file, settings.MINIO_BUCKET, output_key, raw, "video/mp4"
                )
                return
            name = f"shot_{i}.mp4"
            (directory / name).write_bytes(raw)
            parts.append(name)
        target = directory / "episode.mp4"
        await asyncio.to_thread(join_files, directory, parts, target)
        store = storage_service.get_minio_client()
        await asyncio.to_thread(storage_service.ensure_bucket, store, settings.MINIO_BUCKET)
        await asyncio.to_thread(
            store.fput_object, settings.MINIO_BUCKET, output_key, str(target), content_type="video/mp4"
        )


async def locked_run(db: AsyncSession, run_id: str) -> GenerationRun | None:
    return (
        await db.execute(
            select(GenerationRun)
            .where(GenerationRun.id == run_id, GenerationRun.stage == STAGE)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def finish(run: GenerationRun, error: str | None = None):
    run.status = "failed" if error else "succeeded"
    run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    run.error = error


async def advance(db: AsyncSession, run_id: str) -> float | None:
    run = await locked_run(db, run_id)
    if not run or run.status not in ACTIVE:
        await db.commit()
        return None
    p = deepcopy(run.params)
    if not p.get("browser_session"):
        raise FlowError("旧版中转任务已停用，请选择已配对的浏览器创建新任务")
    run.status = "running"
    source = next((s for s in p["sources"] if not s.get("media_id")), None)
    shot = next((s for s in p["shots"] if not s.get("video_id")), None)
    scope = (db, p["provider_id"], p["browser_session"])
    delay = 0
    p.pop("waiting_for", None)
    if p.get("pending_job"):
        job = await db.get(FlowBrowserJob, p["pending_job"], populate_existing=True)
        if not job:
            raise FlowError("未找到本地浏览器任务")
        result = job.result or {}
        if result.get("project_url"):
            p["project_url"] = result["project_url"]
        if job.status == "failed":
            p["uncertain"] = bool((job.result or {}).get("uncertain"))
            finish(run, (job.result or {}).get("error") or "Flow 网页操作失败")
        elif job.status == "succeeded":
            if job.action == "project":
                p["remote_id"], p["remote_title"] = str(UUID(result["project"])), p["project_title"]
            elif job.action == "upload":
                source["media_id"] = result["name"]
            elif job.action == "video":
                shot["video_id"] = result["output_key"]
                p.pop("attempt", None)
            p.pop("pending_job")
        else:
            device = await browser.locked_browser(db, p["provider_id"])
            if device.session_id != p["browser_session"]:
                finish(run, "本次任务的浏览器已被替换，请创建新任务")
            elif not browser.online(device) and (browser.now() - job.created_at).total_seconds() > 120:
                # A claimed paid job can still finish on the original desktop. Resume polls the same command.
                if job.status == "queued":
                    job.status, job.result = "failed", {"error": "连接器离线，任务尚未领取"}
                finish(run, "浏览器连接器离线，重新连接后可从此处继续")
            else:
                if job.action == "upload" and result.get("waiting_for") == "upload_rights":
                    p["waiting_for"] = "upload_rights"
                delay = 3
    elif not p.get("remote_id"):
        if p["mode"] == "video" and len(p["shots"]) > 1 and not shutil.which("ffmpeg"):
            raise FlowError("请在 Worker 上安装 FFmpeg 以拼接本话镜头")
        job = await browser.enqueue(
            *scope, "project", p["project_id"], {"workspace": p["project_id"], "title": p["project_title"]}
        )
        p["pending_job"] = job.id
    elif source:
        raw = await asyncio.to_thread(storage_service.get_object_bytes, settings.MINIO_BUCKET, source["key"])
        if not raw:
            raise FlowError(f"无法读取素材「{source['label']}」")
        raw = await asyncio.to_thread(browser.reference_bytes, raw)
        digest = hashlib.sha256(raw).hexdigest()
        job = await browser.enqueue(
            *scope,
            "upload",
            f"{p['remote_id']}/{digest}",
            {
                "project": p["remote_id"],
                "digest": digest,
                "input_keys": [source["key"]],
            },
        )
        p["pending_job"] = job.id
    elif p["mode"] == "sync":
        finish(run)
    elif shot:
        names = {s["key"]: s["media_id"] for s in p["sources"]}
        chosen = [names[k] for k in shot["references"]]
        refs = list(dict.fromkeys(chosen))
        prompt = shot["prompt"]
        if len(chosen) != len(refs):
            order = "、".join(str(refs.index(name) + 1) for name in chosen)
            prompt += f"\n相同参考图已合并。方案中的参考图依次对应实际附图 {order}。"
        index = p["shots"].index(shot)
        job = await browser.enqueue(
            *scope,
            "video",
            f"{run.id}/{index}/{p.get('attempt', 0)}",
            {
                "project": p["remote_id"],
                "model": run.model,
                "prompt": prompt,
                "ratio": "16:9" if p["aspect_ratio"] == "landscape" else "9:16",
                "references": refs,
            },
        )
        p["pending_job"] = job.id
    else:
        key = f"flow/{run.episode_id}/{run.id}.mp4"
        await export_video([s["video_id"] for s in p["shots"]], key)
        p["output_key"] = key
        finish(run)
    run.params = p
    await db.commit()
    return delay if run.status in ACTIVE else None


async def fail_run(db: AsyncSession, run_id: str, message: str):
    await db.rollback()
    run = await locked_run(db, run_id)
    if run and run.status in ACTIVE:
        finish(run, message)
    await db.commit()


async def execute(db: AsyncSession, run_id: str):
    try:
        while (delay := await advance(db, run_id)) is not None:
            if delay:
                await asyncio.sleep(delay)
    except Exception as exc:
        await fail_run(
            db, run_id, str(exc) if isinstance(exc, FlowError) else f"Flow 任务处理失败（{type(exc).__name__}）"
        )
        raise
