from __future__ import annotations

import asyncio
import types
import uuid
from decimal import Decimal

import pytest
from app.database import Base
from app.models.asset import Asset
from app.models.branch import Branch
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.pit import Pit
from app.models.project import Project
from app.services import memory_service, render_agent, understanding_service
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class AsyncSyncSessionAdapter:
    """Thin async adapter over an in-memory SQLite Session so full ORM queries run in milliseconds."""

    def __init__(self, sync_session: Session) -> None:
        self._s = sync_session

    async def execute(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._s.execute(statement, *args, **kwargs)

    def add(self, instance) -> None:  # type: ignore[no-untyped-def]
        self._s.add(instance)

    async def flush(self) -> None:
        self._s.flush()

    async def commit(self) -> None:
        self._s.commit()

    async def refresh(self, instance) -> None:  # type: ignore[no-untyped-def]
        self._s.refresh(instance)


def _make_memory_db() -> AsyncSyncSessionAdapter:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return AsyncSyncSessionAdapter(Session(engine))


def test_65_episode_hierarchical_memory_and_targeted_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a 65-episode ongoing manga with 40+ characters, forked branch, and early callbacks."""
    monkeypatch.setattr(memory_service, "embeddings_configured", lambda: False)
    db = _make_memory_db()

    async def _run() -> None:
        pid = str(uuid.uuid4())
        bid = str(uuid.uuid4())
        other_bid = str(uuid.uuid4())

        proj = Project(id=pid, title="Long Manga 65", language="zh", canon_rules={})
        main_branch = Branch(id=bid, project_id=pid, name="main", is_default=True)
        alt_branch = Branch(id=other_bid, project_id=pid, name="what-if", is_default=False)
        db.add(proj)
        db.add(main_branch)
        db.add(alt_branch)
        await db.commit()

        ep_ids: dict[int, str] = {}
        for i in range(1, 66):
            eid = str(uuid.uuid4())
            ep_ids[i] = eid
            ep = Episode(
                id=eid,
                project_id=pid,
                branch_id=bid,
                number=Decimal(str(i)),
                label=str(i),
                title=f"第{i}话",
                source="imported",
                status="understood",
            )
            db.add(ep)

            if i == 1:
                summary = "主角觉醒『苍蓝星痕』契约，立下寻找失落圣剑的誓言。"
                events = [{"description": "觉醒苍蓝星痕并与守护灵缔结契约", "significance": "turning_point"}]
            elif i == 7:
                summary = "在迷雾港遇见神秘铁匠古斯塔夫，获赠半枚『龙鳞罗盘』碎片。"
                events = [{"description": "古斯塔夫交出龙鳞罗盘碎片并约定集齐两枚后重铸圣剑", "significance": "major"}]
            else:
                summary = f"第{i}话日常推进与迷宫探索战斗记录。"
                events = [{"description": f"第{i}话探索第{i}层迷宫", "significance": "normal"}]

            db.add(
                EpisodeMemory(
                    id=str(uuid.uuid4()),
                    episode_id=eid,
                    type="summary",
                    content={
                        "summary": summary,
                        "events": events,
                        "state_changes": (
                            [{"character": "主角", "attribute": "持有物", "after": "龙鳞罗盘残片"}] if i == 7 else []
                        ),
                        "ending_state": {
                            "location": "王都钟楼",
                            "cliffhanger": "神秘黑衣人亮出另一半龙鳞罗盘！" if i == 65 else "继续前行",
                            "active_characters": ["主角", "新篇章圣女露娜"] if i >= 64 else ["主角"],
                        },
                    },
                )
            )

        # Add a sibling branch episode that MUST NOT leak into main branch RAG
        alt_ep_id = str(uuid.uuid4())
        db.add(
            Episode(
                id=alt_ep_id,
                project_id=pid,
                branch_id=other_bid,
                number=Decimal("8"),
                label="8",
                title="平行世界线第8话",
                source="generated",
                status="published",
            )
        )
        db.add(
            EpisodeMemory(
                id=str(uuid.uuid4()),
                episode_id=alt_ep_id,
                type="summary",
                content={
                    "summary": "平行世界线：古斯塔夫叛变投靠魔王并销毁了龙鳞罗盘。",
                    "events": [{"description": "平行支线古斯塔夫销毁龙鳞罗盘", "significance": "major"}],
                },
            )
        )

        # Populate 30 minor early characters (each appeared in 3 early episodes)
        for m in range(30):
            db.add(
                Asset(
                    id=str(uuid.uuid4()),
                    project_id=pid,
                    type="character",
                    name=f"早期路人甲{m}",
                    description="早期城镇背景角色",
                    episode_ids={ep_ids[2]: True, ep_ids[3]: True, ep_ids[4]: True},
                )
            )

        # Core protagonist (appeared in 50 episodes)
        db.add(
            Asset(
                id=str(uuid.uuid4()),
                project_id=pid,
                type="character",
                name="主角",
                description="黑发少年剑士",
                episode_ids={ep_ids[k]: True for k in range(1, 51)},
            )
        )
        # Early callback character from Ep 7 (only 1 appearance, but mentioned in custom_instructions!)
        db.add(
            Asset(
                id=str(uuid.uuid4()),
                project_id=pid,
                type="character",
                name="古斯塔夫",
                description="迷雾港独眼矮人铁匠",
                tags={"aliases": ["独眼铁匠"]},
                episode_ids={ep_ids[7]: True},
            )
        )
        # Brand-new heroine introduced in Ep 65 (only 1 appearance, must NOT be evicted by the 30 minor chars!)
        db.add(
            Asset(
                id=str(uuid.uuid4()),
                project_id=pid,
                type="character",
                name="新篇章圣女露娜",
                description="第65话初登场的银发圣女",
                episode_ids={ep_ids[65]: True},
            )
        )

        # Add an early high-priority pit from Ep 7
        db.add(
            Pit(
                id=str(uuid.uuid4()),
                project_id=pid,
                title="龙鳞罗盘之谜",
                description="龙鳞罗盘两枚碎片合二为一后能否唤醒古斯塔夫所说的失落圣剑",
                status="open",
                priority=9,
                introduced_episode_id=ep_ids[7],
            )
        )
        await db.commit()

        # 1. Verify Understanding history before Ep 65 still contains Ep 1~10 Arc Summary!
        history_before_65 = await memory_service.get_branch_history_before(db, pid, bid, Decimal("65"))
        assert "【第1~10话篇章纪要】" in history_before_65
        assert "苍蓝星痕" in history_before_65
        assert "第64话" in history_before_65

        # 2. Verify Generation Context at Ep 65 (for Ep 66)
        ctx = await memory_service.build_context_for_generation(
            db,
            pid,
            bid,
            Decimal("65"),
            custom_instructions="让独眼铁匠古斯塔夫重逢并鉴定黑衣人的龙鳞罗盘",
        )

        # Ep 1~10 arc digest survives intact inside long_summary without front-slicing
        assert "【第1~10话篇章纪要】" in ctx["long_summary"]
        assert "苍蓝星痕" in ctx["long_summary"]
        assert "【第51~60话篇章纪要】" in ctx["long_summary"]

        # Both brand-new Ep 65 heroine AND Ep 7 callback blacksmith beat the 30 3-episode minor characters!
        dossier_names = [c["name"] for c in ctx["character_dossier"]]
        assert "主角" in dossier_names
        assert "新篇章圣女露娜" in dossier_names
        assert "古斯塔夫" in dossier_names

        # Multi-query RAG recalls Ep 7 blacksmith/compass memory AND excludes sibling branch (`other_bid`)!
        rag_eps = [m["episode_number"] for m in ctx["rag_memories"]]
        rag_texts = " ".join(m["content"] for m in ctx["rag_memories"])
        assert 7.0 in rag_eps
        assert "古斯塔夫" in rag_texts
        assert "平行世界线" not in rag_texts
        assert "叛变投靠魔王" not in rag_texts

    asyncio.run(_run())


def test_tiered_world_rules_preserve_foundational_canon_past_60_rules() -> None:
    """Foundational Episode 1 world rules must never be evicted when 60+ later trivia rules are added."""
    db = _make_memory_db()

    async def _run() -> None:
        pid = str(uuid.uuid4())
        proj = Project(id=pid, title="Canon Persistence Test", language="zh", canon_rules={})
        db.add(proj)
        await db.commit()

        # Episode 1 establishes 3 foundational magic laws
        await understanding_service._update_project_story_bible(
            db,
            proj,
            "1",
            {
                "world_rules_discovered": [
                    "核心法则一：记忆消除魔法『伊库拉斯·库欧拉』可抹除特定记忆。",
                    "核心法则二：格兰巴哈马尔与地球现实时间呈 1:1 流逝。",
                    "核心法则三：记忆投影视窗支持触屏式旋转与双指缩放。",
                ]
            },
        )

        # Episodes 2..65 discover 65 additional distinct regional rules
        topics = ["矿山锻造", "航海风向", "王都税制", "药剂调配", "迷宫生态", "吟游诗篇", "公会晋升"]
        for ep_no in range(2, 67):
            topic = topics[ep_no % len(topics)]
            await understanding_service._update_project_story_bible(
                db,
                proj,
                str(ep_no),
                {"world_rules_discovered": [f"[{topic}·话{ep_no}] 支线城镇关于{topic}的第{ep_no * 37}条细则说明。"]},
            )

        bible = (proj.canon_rules or {})["story_bible"]
        rules = bible["discovered_rules"]
        assert len(rules) <= 50
        assert "核心法则一：记忆消除魔法『伊库拉斯·库欧拉』可抹除特定记忆。" in rules
        assert "核心法则二：格兰巴哈马尔与地球现实时间呈 1:1 流逝。" in rules
        assert "核心法则三：记忆投影视窗支持触屏式旋转与双指缩放。" in rules
        assert any("话66]" in r for r in rules)

    asyncio.run(_run())


def test_render_agent_alias_search_and_completion_guardrail(monkeypatch: pytest.MonkeyPatch) -> None:
    """RenderAgent finds assets by alias and nudges the LLM when a turn ends with unrendered panels."""
    db = _make_memory_db()

    async def _run() -> None:
        pid = str(uuid.uuid4())
        bid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        db.add(Project(id=pid, title="Render Guardrail Test", language="zh", canon_rules={}))
        db.add(Branch(id=bid, project_id=pid, name="main", is_default=True))
        ep = Episode(
            id=eid,
            project_id=pid,
            branch_id=bid,
            number=Decimal("5"),
            label="5",
            source="generated",
            status="scripted",
        )
        db.add(ep)
        char_id = str(uuid.uuid4())
        db.add(
            Asset(
                id=char_id,
                project_id=pid,
                type="character",
                name="敬文",
                description="浅灰短发细框眼镜青年",
                tags={"aliases": ["高文", "Takafumi"], "visual_tags": ["glasses"]},
            )
        )
        await db.commit()

        monkeypatch.setattr(render_agent.storage_service, "upload_file", lambda *a, **kw: None)

        call_step = 0

        class FakeCompletions:
            async def create(self, **kwargs):  # type: ignore[no-untyped-def]
                nonlocal call_step
                call_step += 1
                if call_step == 1:
                    # Step 1: only renders panel 1-1, forgets 1-2!
                    tc = types.SimpleNamespace(
                        id="tc1",
                        function=types.SimpleNamespace(
                            name="generate_panel",
                            arguments='{"panel_id": "1-1", "prompt": "panel 1-1 art"}',
                        ),
                    )
                    msg = types.SimpleNamespace(content="", tool_calls=[tc])
                elif call_step == 2:
                    # Step 2: prematurely stops without rendering 1-2 -> triggers Completion Guardrail!
                    msg = types.SimpleNamespace(content="Done!", tool_calls=[])
                elif call_step == 3:
                    # Step 3: after guardrail nudge, renders missing 1-2!
                    tc = types.SimpleNamespace(
                        id="tc2",
                        function=types.SimpleNamespace(
                            name="generate_panel",
                            arguments='{"panel_id": "1-2", "prompt": "panel 1-2 art"}',
                        ),
                    )
                    msg = types.SimpleNamespace(content="", tool_calls=[tc])
                else:
                    msg = types.SimpleNamespace(content="All panels rendered.", tool_calls=[])
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

        fake_client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=FakeCompletions()))
        monkeypatch.setattr(render_agent, "get_raw_openai_client", lambda: fake_client)

        agent = render_agent.RenderAgent(db, ep, "run-1", "mock", None, "1024x1024")
        # Verify alias search matches "Takafumi" -> "敬文"
        found = await agent._tool_search_assets("Takafumi", "character")
        assert len(found) == 1 and found[0]["name"] == "敬文"

        sb = {
            "title": "Test",
            "synopsis": "Test",
            "pages": [
                {
                    "page_number": 1,
                    "layout": "2_vertical",
                    "panels": [
                        {"panel_id": "1-1", "prompt": "p1"},
                        {"panel_id": "1-2", "prompt": "p2"},
                    ],
                }
            ],
        }
        res = await agent.run(sb)
        assert set(res["agent_rendered"]) == {"1-1", "1-2"}
        assert res["fallback_rendered"] == []

    asyncio.run(_run())
