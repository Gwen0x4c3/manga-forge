# ruff: noqa: E501
"""Deterministic verification suite for MangaForge's upgraded continuity engine:
1. Strict temporal & branch isolation in build_context_for_generation (zero future spoilers)
2. Main plotline, previous episode ending bridge, cumulative character dossier & speech samples
3. Idempotent re-understanding / re-scripting / re-layout (zero MultipleResultsFound or duplicate long_summary lines)
4. Safe episode deletion when pits reference introduced_episode_id / resolved_episode_id
5. Branch fork & diff accuracy (episodes, assets, pits with real UUIDs)
6. LayoutEngine 1..6 panel dynamic layouts & CJK bubble rendering
"""
from __future__ import annotations

import asyncio
import io
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗ FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


def sample_panel_png(color: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (800, 800), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def test_layout_engine() -> None:
    print("== 1. LayoutEngine multi-panel & CJK speech bubble rendering ==")
    from app.core.layout_engine import LayoutEngine, PanelImage

    engine = LayoutEngine()
    for count, layout_name in [
        (1, "splash"),
        (2, "2_cinematic"),
        (3, "3_panels"),
        (4, "4_manga_dynamic"),
        (5, "5_panels"),
        (5, "unrecognized_template"),  # must still render all 5 panels without dropping any!
        (6, "6_panels"),
    ]:
        boxes = engine._apply_layout(layout_name, count)
        check(f"layout '{layout_name}' ({count} panels) produces {count} boxes", len(boxes) == count, str(len(boxes)))
        panels = [
            PanelImage(
                image_data=sample_panel_png((210 + i * 5, 220, 235)),
                panel_id=f"1-{i + 1}",
                dialogues=[
                    {"speaker": "小樱", "text": "星之匣真的在发光！我们快看看信里写了什么！", "type": "speech"},
                    {"speaker": "", "text": "阁楼外传来了沉重的脚步声……", "type": "narration"},
                    {"speaker": "阿明", "text": "难道有人一直守在这里？", "type": "thought"},
                    {"speaker": "", "text": "咚——！！", "type": "sfx"},
                ],
            )
            for i in range(count)
        ]
        composed = engine.compose_page(layout_name, panels, page_number=1)
        out_img = Image.open(io.BytesIO(composed.image_data))
        check(
            f"composed page ({layout_name}, {count}p) is 2480x3508 PNG",
            out_img.size == (2480, 3508),
            str(out_img.size),
        )


async def test_continuity_and_lifecycle() -> None:
    print("\n== 2. Continuity Context Isolation, Idempotency, Fork/Diff & Safe Deletion ==")
    from app.database import worker_session
    from app.models.branch import Branch
    from app.models.episode_memory import EpisodeMemory
    from app.models.pit import Pit
    from app.schemas.branch import DiffRequest, ForkRequest
    from app.schemas.episode import EpisodeImport
    from app.schemas.project import ProjectCreate
    from app.services import (
        branch_service,
        episode_service,
        generation_service,
        memory_service,
        project_service,
        understanding_service,
    )
    from sqlalchemy import select

    async with worker_session() as db:
        project = await project_service.create_project(
            db, ProjectCreate(title="连续性验证·星轨战记", description="isolation test", language="zh")
        )
        branch = (
            await db.execute(select(Branch).where(Branch.project_id == project.id, Branch.is_default.is_(True)).limit(1))
        ).scalar_one()

        ep1 = await episode_service.create_episode(
            db, project.id, EpisodeImport(branch_id=branch.id, number=Decimal("1"), label="1", title="起航")
        )
        ep2 = await episode_service.create_episode(
            db, project.id, EpisodeImport(branch_id=branch.id, number=Decimal("2"), label="2", title="断剑")
        )
        ep3_draft = await episode_service.create_episode(
            db, project.id, EpisodeImport(branch_id=branch.id, number=Decimal("3"), label="3", title="Episode 3", source="generated")
        )
        ep4_future = await episode_service.create_episode(
            db, project.id, EpisodeImport(branch_id=branch.id, number=Decimal("4"), label="4", title="未来剧透章")
        )

        # Register assets & pits for Ep 1 & Ep 2
        await generation_service.auto_discover_assets(
            db,
            project.id,
            ep1.id,
            [
                {
                    "name": "林澈",
                    "asset_type": "character",
                    "description": "黑发少年剑士，左眼下有细小剑痕",
                    "visual_tags": ["black hair", "young swordsman", "scar under left eye"],
                    "speech_style": "冷静克制，常自称“在下”",
                    "role": "protagonist",
                },
                {
                    "name": "碎星古剑",
                    "asset_type": "item",
                    "description": "剑身布满星辰裂纹的青铜古剑",
                    "visual_tags": ["ancient bronze sword", "starry cracks"],
                },
            ],
        )

        pits_ep1 = await generation_service.auto_discover_pits(
            db,
            project.id,
            ep1.id,
            [{"title": "剑鞘封印", "description": "碎星古剑为何被三重封印锁死？", "priority": "high"}],
        )
        seal_pit = pits_ep1[0]

        # Advance clue in Ep 2
        await generation_service.advance_pits(
            db, project.id, "2", [{"pit_id": seal_pit.id, "clue": "封印在月蚀之夜出现了松动"}]
        )

        # Save Ep 1 understanding TWICE to test idempotent upsert & long_summary deduplication
        u1 = {
            "summary": "林澈在废墟中拔出碎星古剑，发现剑鞘被三重封印锁死。",
            "main_plot": {
                "core_conflict": "解开碎星古剑封印并阻止星蚀降临",
                "current_arc": "古剑苏醒篇",
                "protagonist_goal": "寻找解开第一重封印的方法",
                "arc_progress": "林澈获得碎星古剑",
                "next_hook": "神秘黑衣人在废墟外窥视",
            },
            "ending_state": {"location": "古神殿废墟", "active_characters": ["林澈"], "cliffhanger": "远处响起钟声"},
            "events": [{"description": "林澈取得碎星古剑", "characters_involved": ["林澈"], "significance": "major"}],
            "state_changes": [{"character": "林澈", "attribute": "possession", "before": "无武器", "after": "持有碎星古剑"}],
            "page_dialogues": [{"page_number": 1, "lines": [{"speaker": "林澈", "text": "在下绝不会让这把剑落入恶人之手。", "line_type": "speech"}]}],
        }
        await understanding_service.save_understanding_memories(db, ep1.id, u1)
        await understanding_service.save_understanding_memories(db, ep1.id, u1)
        await memory_service.append_episode_summary(db, project.id, "1", u1["summary"])
        await memory_service.append_episode_summary(db, project.id, "1", u1["summary"])

        u2 = {
            "summary": "林澈与黑衣人交手，左肩受伤，但月蚀令古剑第一重封印松动。",
            "main_plot": {
                "core_conflict": "解开碎星古剑封印并阻止星蚀降临",
                "current_arc": "古剑苏醒篇",
                "protagonist_goal": "在左肩重伤下突破黑衣人包围",
                "arc_progress": "第一重封印松动，林澈左肩受伤",
                "next_hook": "黑衣人摘下面具露出熟悉的面孔",
            },
            "ending_state": {
                "location": "断崖木桥",
                "time_and_mood": "月蚀深夜·剑拔弩张",
                "active_characters": ["林澈", "黑衣人"],
                "cliffhanger": "黑衣人缓缓摘下面具，林澈震惊失声",
            },
            "events": [{"description": "断崖激战，黑衣人摘下面具", "characters_involved": ["林澈"], "significance": "cliffhanger"}],
            "state_changes": [{"character": "林澈", "attribute": "injury", "before": "完好", "after": "左肩受刀伤流血"}],
            "page_dialogues": [
                {"page_number": 2, "lines": [{"speaker": "林澈", "text": "怎么可能……这张脸难道是师兄？！", "line_type": "speech"}]}
            ],
        }
        await understanding_service.save_understanding_memories(db, ep2.id, u2)
        await memory_service.append_episode_summary(db, project.id, "2", u2["summary"])
        await understanding_service._update_project_story_bible(db, project, "2", u2)

        # Future Ep 4: resolves Ep 1's pit AND plants a future spoiler pit + spoiler summary!
        u4_spoiler = {
            "summary": "未来第4话剧透：外星战舰降临皇都，封印彻底解开。",
            "main_plot": {"core_conflict": "未来外星战舰入侵", "current_arc": "未来星际篇"},
            "events": [{"description": "外星战舰降临", "significance": "major"}],
            "state_changes": [],
            "page_dialogues": [],
        }
        await understanding_service.save_understanding_memories(db, ep4_future.id, u4_spoiler)
        await generation_service.resolve_pits(db, project.id, ep4_future.id, [seal_pit.id])
        await generation_service.auto_discover_pits(
            db, project.id, ep4_future.id, [{"title": "外星战舰核心", "description": "未来剧透伏笔", "priority": "high"}]
        )

        # Verify idempotent summary storage
        ep1_mems = (
            await db.execute(select(EpisodeMemory).where(EpisodeMemory.episode_id == ep1.id, EpisodeMemory.type == "summary"))
        ).scalars().all()
        check("idempotent save_understanding_memories (only 1 summary row)", len(ep1_mems) == 1, str(len(ep1_mems)))
        long_sum = await memory_service.get_long_summary(db, project.id) or ""
        check("idempotent append_episode_summary (no duplicate 第1话)", long_sum.count("第1话：") == 1, long_sum)

        # Build context for Ep 3 (continuing from Ep 2: cutoff = 2)
        ctx = await memory_service.build_context_for_generation(db, project.id, branch.id, Decimal("2"))

        recent_nums = [e["number"] for e in ctx["recent_episodes"]]
        check("recent_episodes strictly [1.0, 2.0] (no Ep3 draft, no Ep4 spoiler)", recent_nums == [1.0, 2.0], str(recent_nums))
        check(
            "no future spoiler in long_summary at cutoff=2",
            "外星战舰" not in ctx["long_summary"] and "月蚀" in ctx["long_summary"],
            ctx["long_summary"],
        )
        check(
            "no future spoiler in main_plot at cutoff=2",
            ctx["story_bible"]["main_plot"]["current_arc"] == "古剑苏醒篇",
            str(ctx["story_bible"]["main_plot"]),
        )
        pit_titles = [p["title"] for p in ctx["active_pits"]]
        check(
            "seal_pit still OPEN at cutoff=2 (resolved in Ep4) & Ep4 pit excluded",
            "剑鞘封印" in pit_titles and "外星战舰核心" not in pit_titles,
            str(pit_titles),
        )
        seal_ctx = next((p for p in ctx["active_pits"] if p["title"] == "剑鞘封印"), None)
        check("pit progression clues passed to LLM context", bool(seal_ctx and seal_ctx.get("clues")), str(seal_ctx))

        bridge = ctx.get("previous_bridge") or {}
        check(
            "previous_bridge captures Ep2 cliffhanger & closing dialogue",
            "面具" in str(bridge.get("ending_state", {}).get("cliffhanger", ""))
            and any("师兄" in ln for ln in bridge.get("closing_dialogue", [])),
            str(bridge),
        )

        linche = next((c for c in ctx["character_dossier"] if c["name"] == "林澈"), None)
        check(
            "character_dossier collapses Ep1+Ep2 states (possession + injury)",
            bool(linche and "碎星古剑" in linche["current_state"] and "左肩" in linche["current_state"]),
            str(linche),
        )
        check(
            "character_dossier includes authentic speech_samples",
            bool(linche and len(linche.get("speech_samples") or []) >= 2),
            str(linche.get("speech_samples") if linche else None),
        )

        sword = next((a for a in ctx["world_assets"] if a["name"] == "碎星古剑"), None)
        check("world_assets includes key item with visual_tags", bool(sword and sword.get("visual_tags")), str(sword))

        # Test Branch Fork & Diff
        forked_branch = await branch_service.fork_from_episode(
            db, project.id, ForkRequest(episode_id=ep2.id, branch_name="if-route", description="IF线")
        )
        diff = await branch_service.diff_branches(
            db, project.id, DiffRequest(source_branch_id=branch.id, target_branch_id=forked_branch.id)
        )
        check("forked branch has 2 episodes", await branch_service.get_branch_episode_count(db, forked_branch.id) == 2)
        check(
            "diff_branches includes real source_episode_id & asset_id",
            any(d.source_episode_id == ep4_future.id for d in diff.episodes)
            and any(a.asset_id and a.in_source and a.in_target for a in diff.assets),
        )

        # Test Safe Episode Deletion on Ep 4 (which resolved seal_pit AND introduced Ep 4 pit!)
        await episode_service.delete_episode(db, ep4_future)
        await episode_service.delete_episode(db, ep3_draft)
        refreshed_seal_pit = (await db.execute(select(Pit).where(Pit.id == seal_pit.id))).scalar_one()
        check(
            "deleting Ep4 safely re-opened seal_pit without FK crash",
            refreshed_seal_pit.status == "open" and refreshed_seal_pit.resolved_episode_id is None,
            f"{refreshed_seal_pit.status}, {refreshed_seal_pit.resolved_episode_id}",
        )

        # Clean up test project
        await project_service.delete_project(db, project)


async def main() -> None:
    await test_layout_engine()
    await test_continuity_and_lifecycle()
    print(f"\n==== CONTINUITY & LAYOUT VERIFICATION: {len(PASS)} passed, {len(FAIL)} failed ====")
    for f in FAIL:
        print(f"  FAILED: {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
