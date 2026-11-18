# ruff: noqa: E501
"""End-to-end smoke test: multimodal understanding, character/pit tracking,
consistency-checked script gen, mock render, layout, writeback.

Run: .venv/bin/python scripts/smoke_e2e.py  (from repo root, with .env loaded)
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

FONT = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 22)
SMALL = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 16)

PASS = []
FAIL = []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗ FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


def draw_page(elements: list[dict]) -> bytes:
    """elements: dicts with kind=character|bubble|narration|caption placed on panels."""
    img = Image.new("RGB", (900, 1300), "white")
    d = ImageDraw.Draw(img)
    # two stacked panels
    d.rectangle([20, 20, 880, 630], outline="black", width=4)
    d.rectangle([20, 650, 880, 1280], outline="black", width=4)
    for el in elements:
        if el["kind"] == "bg":
            x0, y0, x1, y1, color = el["box"] + [el["color"]]
            d.rectangle([x0, y0, x1, y1], fill=color)
        elif el["kind"] == "character":
            cx, cy, hair, cloth = el["pos"] + [el["hair"], el["cloth"]]
            d.ellipse([cx - 45, cy - 110, cx + 45, cy - 20], fill="#ffe0c8", outline="black", width=3)  # head
            d.polygon([cx - 50, cy - 60, cx - 30, cy - 130, cx + 5, cy - 95], fill=hair)                 # hair L
            d.polygon([cx + 50, cy - 60, cx + 30, cy - 130, cx - 5, cy - 95], fill=hair)                 # hair R
            d.rectangle([cx - 40, cy - 20, cx + 40, cy + 90], fill=cloth, outline="black", width=3)      # body
            d.ellipse([cx - 14, cy - 85, cx - 4, cy - 75], fill="black")
            d.ellipse([cx + 4, cy - 85, cx + 14, cy - 75], fill="black")
            d.arc([cx - 12, cy - 70, cx + 12, cy - 55], 20, 160, fill="black", width=2)
        elif el["kind"] in ("bubble", "narration", "caption"):
            x0, y0, x1, y1 = el["box"]
            text = el["text"]
            if el["kind"] == "narration":
                d.rectangle([x0, y0, x1, y1], fill="#f2f2f2", outline="black", width=2)
            else:
                d.ellipse([x0, y0, x1, y1], fill="white", outline="black", width=3)
            words, lines, cur = text, [], ""
            for ch in words:
                cur += ch
                if d.textlength(cur, font=FONT if el["kind"] != "caption" else SMALL) > (x1 - x0) * 0.82:
                    lines.append(cur[:-1])
                    cur = ch
            lines.append(cur)
            fnt = FONT if el["kind"] != "caption" else SMALL
            lh = d.textbbox((0, 0), "字", font=fnt)[3] + 10
            ty = (y0 + y1) / 2 - lh * len(lines) / 2
            for ln in lines:
                w = d.textlength(ln, font=fnt)
                d.text(((x0 + x1) / 2 - w / 2, ty), ln, fill="black", font=fnt)
                ty += lh
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def make_episode1_pages() -> list[bytes]:
    p1 = draw_page([
        {"kind": "bg", "box": [20, 20, 880, 630], "color": "#e8dcc8"},
        {"kind": "narration", "box": [60, 50, 620, 110], "text": "放学后，小樱独自来到爷爷家的阁楼。"},
        {"kind": "character", "pos": [300, 320], "hair": "#ff9ecf", "cloth": "#3a5fbf"},
        {"kind": "bubble", "box": [420, 180, 840, 330], "text": "爷爷的阁楼里好多灰尘啊……那个角落放的是什么？"},
        {"kind": "bg", "box": [20, 650, 880, 1280], "color": "#d8c8a8"},
        {"kind": "character", "pos": [640, 960], "hair": "#ff9ecf", "cloth": "#3a5fbf"},
        {"kind": "bubble", "box": [60, 760, 480, 900], "text": "是一个旧木箱！上面还有一把锁。"},
    ])
    p2 = draw_page([
        {"kind": "bg", "box": [20, 20, 880, 630], "color": "#e0d8c0"},
        {"kind": "caption", "box": [60, 40, 500, 80], "text": "小樱在木箱旁发现了一把钥匙"},
        {"kind": "character", "pos": [320, 350], "hair": "#ff9ecf", "cloth": "#3a5fbf"},
        {"kind": "bubble", "box": [430, 150, 850, 320], "text": "一把星星形状的钥匙！它能打开这个箱子吗？"},
        {"kind": "bg", "box": [20, 650, 880, 1280], "color": "#c8b898"},
        {"kind": "bubble", "box": [80, 720, 560, 880], "text": "可是锁纹丝不动……箱子里到底装着什么呢？"},
        {"kind": "character", "pos": [680, 1080], "hair": "#ff9ecf", "cloth": "#3a5fbf"},
    ])
    return [p1, p2]


def make_episode2_pages() -> list[bytes]:
    p1 = draw_page([
        {"kind": "bg", "box": [20, 20, 880, 630], "color": "#e8f0ff"},
        {"kind": "narration", "box": [60, 50, 640, 110], "text": "第二天，小樱把钥匙带到了学校。"},
        {"kind": "character", "pos": [280, 340], "hair": "#ff9ecf", "cloth": "#3a5fbf"},
        {"kind": "bubble", "box": [400, 160, 830, 320], "text": "阿明你看！箱子上的锁孔正好是星星的形状！"},
        {"kind": "character", "pos": [700, 980], "hair": "#7fbfff", "cloth": "#4c8c4a"},
        {"kind": "bubble", "box": [80, 800, 480, 960], "text": "小樱，快试试打开它吧！"},
    ])
    p2 = draw_page([
        {"kind": "bg", "box": [20, 20, 880, 630], "color": "#fff4d8"},
        {"kind": "character", "pos": [320, 360], "hair": "#ff9ecf", "cloth": "#3a5fbf"},
        {"kind": "bubble", "box": [440, 150, 860, 330], "text": "打开了！里面是一封会发光的信……"},
        {"kind": "bg", "box": [20, 650, 880, 1280], "color": "#ffe8f0"},
        {"kind": "caption", "box": [60, 680, 560, 720], "text": "信封上写着一行小字"},
        {"kind": "narration", "box": [120, 900, 700, 1010], "text": "“致找到星之匣的人——爷爷”"},
    ])
    return [p1, p2]


class Shim:
    def update_state(self, **kw):
        print(f"    [task state] {kw.get('state')}: {kw.get('meta')}")


async def main():
    from decimal import Decimal

    from app.config import settings
    from app.database import worker_session as async_session
    from app.models.asset import Asset
    from app.models.branch import Branch
    from app.models.episode import Episode
    from app.models.episode_memory import EpisodeMemory
    from app.models.episode_page import EpisodePage
    from app.models.generation_run import GenerationRun
    from app.models.pit import Pit
    from app.schemas.episode import EpisodeImport
    from app.schemas.project import ProjectCreate
    from app.services import (
        episode_service,
        generation_service,
        memory_service,
        project_service,
        storage_service,
    )
    from sqlalchemy import select

    async with async_session() as db:
        project = await project_service.create_project(
            db,
            ProjectCreate(title="冒烟测试·星之匣", description="e2e smoke", language="zh"),
        )
        branch = (
            await db.execute(select(Branch).where(Branch.project_id == project.id, Branch.is_default.is_(True)).limit(1))
        ).scalar_one()
        ep1 = await episode_service.create_episode(
            db, project.id, EpisodeImport(branch_id=branch.id, number=Decimal("1"), title="阁楼里的星之匣")
        )
        ep2 = await episode_service.create_episode(
            db, project.id, EpisodeImport(branch_id=branch.id, number=Decimal("2"), title="打开匣子")
        )
        for ep, pages in ((ep1, make_episode1_pages()), (ep2, make_episode2_pages())):
            for i, data in enumerate(pages):
                key = storage_service.generate_object_key(f"smoke/{ep.id}", f"page_{i}.jpg")
                storage_service.upload_file(settings.MINIO_BUCKET, key, data, "image/jpeg")
                db.add(EpisodePage(episode_id=ep.id, page_index=i, image_path=key, width=900, height=1300))
        await db.commit()
        print(f"seeded: project={project.id} ep1={ep1.id} ep2={ep2.id}")

    # ---- Episode 1: multimodal understanding ----
    print("\n== understand episode 1 (multimodal) ==")
    from workers.tasks.understand import _summarize_episode

    run1 = None
    async with async_session() as db:
        run1 = await generation_service.create_generation_run(db, episode_id=ep1.id, stage="understand")
    await _summarize_episode(Shim(), str(run1.id), ep1.id)

    async with async_session() as db:
        ep1 = await db.get(Episode, ep1.id)
        check("ep1 status=understood", ep1.status == "understood", ep1.status)
        mem = (
            await db.execute(select(EpisodeMemory).where(EpisodeMemory.episode_id == ep1.id))
        ).scalars().all()
        summary_mem = next((m for m in mem if m.type == "summary" and "summary" in (m.content or {})), None)
        check("ep1 summary memory with content.summary", summary_mem is not None and bool(summary_mem.content.get("summary")))
        if summary_mem:
            print(f"    summary: {summary_mem.content['summary'][:120]}")
        ocr_mem = next((m for m in mem if m.type == "ocr_dump"), None)
        check("ep1 ocr_dump transcription", ocr_mem is not None and "小樱" in ocr_mem.content.get("text", ""))
        if ocr_mem:
            print(f"    ocr excerpt: {ocr_mem.content['text'][:120]!r}")
        assets = (await db.execute(select(Asset).where(Asset.project_id == project.id))).scalars().all()
        char_assets = [a for a in assets if a.type == "character"]
        check("ep1 character asset 小樱 discovered", any("小樱" in a.name for a in char_assets),
              str([(a.name, a.type) for a in assets]))
        pits = (await db.execute(select(Pit).where(Pit.project_id == project.id))).scalars().all()
        check("ep1 pit discovered (box/key mystery)", len(pits) >= 1 and all(p.status == "open" for p in pits),
              str([(p.title, p.status) for p in pits]))
        proj = await db.get(type(project), project.id)
        check("long_summary updated", bool(proj.long_summary))

    # ---- Episode 2: pit resolution + character recognition ----
    print("\n== understand episode 2 (pit resolution + new character) ==")
    run2 = None
    async with async_session() as db:
        run2 = await generation_service.create_generation_run(db, episode_id=ep2.id, stage="understand")
    await _summarize_episode(Shim(), str(run2.id), ep2.id)

    async with async_session() as db:
        pits = (await db.execute(select(Pit).where(Pit.project_id == project.id))).scalars().all()
        resolved = [p for p in pits if p.status == "resolved"]
        check("pit resolved by ep2", len(resolved) >= 1, str([(p.title[:30], p.status) for p in pits]))
        if resolved:
            check("pit resolved_episode_id=ep2", all(p.resolved_episode_id == ep2.id for p in resolved))
        assets = (await db.execute(select(Asset).where(Asset.project_id == project.id))).scalars().all()
        xiaoying = next((a for a in assets if "小樱" in a.name), None)
        check("小樱 tracked across episodes", xiaoying is not None and ep1.id in (xiaoying.episode_ids or {}) and ep2.id in (xiaoying.episode_ids or {}),
              str(xiaoying.episode_ids if xiaoying else None))
        check("阿明 discovered as new character", any("阿明" in a.name for a in assets if a.type == "character"),
              str([(a.name, a.type) for a in assets]))

    # ---- Generation context (RAG fallback + pits + assets) ----
    print("\n== build_context_for_generation (keyword RAG fallback) ==")
    async with async_session() as db:
        ctx = await memory_service.build_context_for_generation(db, project.id, branch.id, Decimal("2"))
        check("recent window has real summaries", any(ep["summary"] for ep in ctx["recent_episodes"]),
              str(ctx["recent_episodes"]))
        check("rag_memories non-empty (keyword fallback)", len(ctx["rag_memories"]) > 0,
              str(ctx["rag_memories"])[:200])
        check("assets in context", len(ctx["assets"]) >= 2)
        print(f"    rag: {[m['content'][:60] for m in ctx['rag_memories']]}")

    # ---- Full continue pipeline (script → mock render → layout → writeback) ----
    print("\n== continue pipeline on episode 3 (mock image backend) ==")
    async with async_session() as db:
        ep3 = await episode_service.create_episode(
            db, project.id, EpisodeImport(branch_id=branch.id, number=Decimal("3"), title="")
        )
        await generation_service.create_generation_run(db, episode_id=ep3.id, stage="continue")

    # Direct in-process invocation (mirrors run_continue body)
    shim = Shim()
    async with async_session() as db:
        script_run = await generation_service.create_generation_run(db, episode_id=ep3.id, stage="script")
        render_run = await generation_service.create_generation_run(db, episode_id=ep3.id, stage="render", backend="mock")
        layout_run = await generation_service.create_generation_run(db, episode_id=ep3.id, stage="layout")
        script_id, render_id, layout_id = str(script_run.id), str(render_run.id), str(layout_run.id)

    from workers.tasks.layout import _layout_episode
    from workers.tasks.render import _render_episode
    from workers.tasks.script_gen import _generate_script
    from workers.tasks.writeback import _writeback_episode

    await _generate_script(shim, script_id, ep3.id, branch.id, 2.0, "main", None)
    await _render_episode(shim, render_id, ep3.id, "mock", None, "1024x1024")
    await _layout_episode(shim, layout_id, ep3.id, None, trigger_writeback=False)
    await _writeback_episode(shim, ep3.id, project.id)

    async with async_session() as db:
        ep3 = await db.get(Episode, ep3.id)
        check("ep3 scripted→published status", ep3.status in ("scripted", "rendered", "published"), ep3.status)
        mem3 = (await db.execute(select(EpisodeMemory).where(EpisodeMemory.episode_id == ep3.id))).scalars().all()
        types = {m.type for m in mem3}
        check("storyboard_json saved", "storyboard_json" in types, str(types))
        check("consistency_report saved", "consistency_report" in types, str(types))
        check("layout_result saved", "layout_result" in types, str(types))
        check("writeback understanding saved", any(m.type == "summary" and "summary" in (m.content or {}) for m in mem3))
        cons = next((m for m in mem3 if m.type == "consistency_report"), None)
        if cons:
            print(f"    consistency: overall={cons.content.get('overall')} issues={len(cons.content.get('issues', []))}")
        stage_runs = (
            await db.execute(
                select(GenerationRun).where(
                    GenerationRun.episode_id == ep3.id, GenerationRun.stage != "continue"
                )
            )
        ).scalars().all()
        check("all stage runs succeeded", all(r.status == "succeeded" for r in stage_runs),
              str([(r.stage, r.status, r.error) for r in stage_runs]))
        proj = await db.get(type(project), project.id)
        check("long_summary grew after writeback", bool(proj.long_summary) and len(proj.long_summary) > 100)

    print(f"\n==== SMOKE RESULT: {len(PASS)} passed, {len(FAIL)} failed ====")
    for f in FAIL:
        print(f"  FAILED: {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
