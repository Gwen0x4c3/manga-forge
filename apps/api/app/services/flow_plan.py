from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, Episode, EpisodeMemory, EpisodePage, GeneratedImage, Project
from app.providers.google_flow import VIDEO_REF_LIMIT, FlowError
from app.schemas.google_flow import FlowOptions, FlowPlan, FlowShot, FlowSource
from app.services.asset_service import list_asset_images


@dataclass
class Frame:
    source: FlowSource
    notes: str
    page: int


def _lines(lines: list) -> str:
    return " / ".join(f"{d.get('speaker') or '旁白'}：{d.get('text')}" for d in lines if d.get("text"))


def _panel_notes(panel: dict) -> str:
    names = "、".join(c["name"] for c in panel.get("characters") or [] if c.get("name"))
    return " ".join(
        str(s)
        for s in (
            panel.get("scene"),
            names,
            panel.get("location"),
            panel.get("camera"),
            panel.get("mood"),
            _lines(panel.get("dialogue") or []),
        )
        if s
    )


async def build_plan(db: AsyncSession, ep: Episode, options: FlowOptions) -> FlowPlan:
    project = await db.get(Project, ep.project_id)
    memories = {
        m.type: m.content
        for m in (
            await db.execute(
                select(EpisodeMemory)
                .where(
                    EpisodeMemory.episode_id == ep.id,
                    EpisodeMemory.type.in_(["storyboard_json", "layout_result", "summary", "ocr_dump"]),
                )
                .order_by(EpisodeMemory.created_at, EpisodeMemory.id)
            )
        ).scalars()
    }
    summary = memories.get("summary", {})
    boards = {int(p["page_number"]): p.get("panels", []) for p in memories.get("storyboard_json", {}).get("pages", [])}
    dialogues = {
        p.get("page_number"): _lines(p.get("lines") or [])
        for p in summary.get("page_dialogues") or memories.get("ocr_dump", {}).get("pages") or []
    }
    original = (
        (await db.execute(select(EpisodePage).where(EpisodePage.episode_id == ep.id).order_by(EpisodePage.page_index)))
        .scalars()
        .all()
    )
    page_keys = {p.page_index + 1: p.image_path for p in original}
    layout = memories.get("layout_result", {}).get("pages") or []
    if layout and (ep.source == "generated" or not page_keys):
        page_keys = {int(p["page_number"]): p["image_path"] for p in layout}
    frames = []
    for n, key in sorted(page_keys.items()):
        notes = " ".join(_panel_notes(p) for p in boards.get(n, [])) or dialogues.get(n, "")
        frames.append(Frame(FlowSource(key=key, label=f"第 {n} 页", kind="page"), notes, n))
    if not frames and boards:
        images = {
            im.panel_id: im.image_path
            for im in (
                await db.execute(
                    select(GeneratedImage)
                    .where(GeneratedImage.episode_id == ep.id)
                    .order_by(GeneratedImage.created_at, GeneratedImage.id)
                )
            ).scalars()
        }
        for n, panels in sorted(boards.items()):
            for panel in panels:
                pid = panel.get("panel_id")
                if pid not in images:
                    raise FlowError("分镜原画尚未齐全，请先渲染本话原画")
                source = FlowSource(key=images[pid], label=f"分镜 {pid}", kind="panel")
                frames.append(Frame(source, _panel_notes(panel), n))
    if not frames:
        return FlowPlan(sources=[], shots=[])

    # Match assets by episode membership or explicit storyboard mentions, including hand-made assets.
    mentions = " ".join(f.notes for f in frames)
    assets = (
        await db.execute(select(Asset).where(Asset.project_id == ep.project_id).order_by(Asset.name, Asset.id))
    ).scalars()
    sources = {f.source.key: f.source for f in frames}
    asset_refs = []
    for asset in assets:
        if asset.type != "style" and ep.id not in (asset.episode_ids or {}) and asset.name not in mentions:
            continue
        images = await list_asset_images(db, asset.id)
        if images:
            ref = FlowSource(key=images[0].image_path, label=asset.name, kind=asset.type)
            sources.setdefault(ref.key, ref)
            asset_refs.append(ref)

    sightings = {
        s.get("name"): s.get("source_page")
        for s in (summary.get("characters") or []) + (summary.get("new_assets") or [])
    }
    shots = []
    for start in range(0, len(frames), options.pages_per_clip):
        group = frames[start : start + options.pages_per_clip]
        shot_notes = " ".join(f.notes for f in group)
        pages = {f.page for f in group}
        refs = [f.source for f in group]
        relevant = [a for a in asset_refs if a.label in shot_notes or sightings.get(a.label) in pages]
        refs.extend(relevant + [a for a in asset_refs if a.kind == "style"])
        refs = list({r.key: r for r in refs}.values())[: VIDEO_REF_LIMIT[options.model]]
        anchors = "，".join(f"第 {i} 张（{r.label[:80]}）" for i, r in enumerate(refs, 1))
        title = f"《{project.title}》第 {ep.label or ep.number} 话" + (f"《{ep.title}》" if ep.title else "")
        parts = [
            f"{title}。将以下漫画画面改编为一段 8 秒的连续动画。参考图依次为 {anchors}。",
            "按原作分格顺序呈现动作和反应，保持人物造型、道具、线条与明暗一致。"
            "把分格转为全画幅镜头，利用人物动作与镜头移动衔接。气泡台词转为对白，画面中去掉气泡。",
        ]
        if summary.get("art_style_notes"):
            parts.append(f"画风：{str(summary['art_style_notes'])[:180]}")
        if summary.get("summary"):
            parts.append(f"本话背景（只演本镜头画面）：{str(summary['summary'])[:220]}")
        parts.extend(f"{f.source.label}：{f.notes[:1100]}" for f in group if f.notes)
        shots.append(
            FlowShot(
                label="、".join(f.source.label for f in group),
                prompt="\n".join(parts)[:4000],
                references=[r.key for r in refs],
            )
        )
    plan = FlowPlan(sources=list(sources.values()), shots=shots)
    plan.plan_id = hashlib.sha256(
        (options.model_dump_json(include=set(FlowOptions.model_fields)) + plan.model_dump_json()).encode()
    ).hexdigest()
    return plan
