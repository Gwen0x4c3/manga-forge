from __future__ import annotations

import asyncio
import base64
import json
import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.asset import Asset
from app.models.asset_image import AssetImage
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.pit import Pit
from app.models.project import Project
from app.services import understanding_service
from app.services.manga_vision_utils import (
    crop_pixel_box,
    prepare_manga_page_blocks,
    render_crop_contact_sheet,
    render_pixel_grid,
    render_zoom_refinement_grid,
    sanitize_understanding,
)


class AsyncSyncSessionAdapter:
    def __init__(self, sync_session):
        self._s = sync_session

    async def execute(self, *args, **kwargs):
        return self._s.execute(*args, **kwargs)

    def add(self, obj):
        self._s.add(obj)

    async def delete(self, obj):
        self._s.delete(obj)

    async def flush(self):
        self._s.flush()

    async def commit(self):
        self._s.commit()

    async def refresh(self, obj):
        self._s.refresh(obj)


def _make_memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return AsyncSyncSessionAdapter(sessionmaker(bind=engine)())


def _textured_manga_page(w: int = 800, h: int = 1200) -> bytes:
    """Create a synthetic textured page with distinct geometric patterns so stddev crop gates pass."""
    im = Image.new("RGB", (w, h), (245, 245, 245))
    d = ImageDraw.Draw(im)
    # Draw high-contrast manga panels + face-like circle + sword-like diagonal across the page
    d.rectangle([40, 40, w - 40, h - 40], outline=(15, 15, 15), width=6)
    for x in range(80, w - 80, 35):
        d.line([(x, 80), (x + 20, h - 80)], fill=(30, 30, 30), width=4)
    # Character face-like box around (150, 150, 450, 480)
    d.ellipse([180, 180, 420, 440], fill=(230, 230, 230), outline=(10, 10, 10), width=6)
    d.ellipse([235, 260, 275, 300], fill=(10, 10, 10))
    d.ellipse([325, 260, 365, 300], fill=(10, 10, 10))
    d.arc([250, 330, 350, 390], 10, 170, fill=(10, 10, 10), width=5)
    # Blank white speech bubble patch at bottom-right (for blank crop rejection test)
    d.rectangle([560, 920, 740, 1120], fill=(255, 255, 255))
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_prepare_manga_page_blocks_rtl_spread_and_webtoon():
    # 1. Double-page spread: RTL puts Right before Left, LTR puts Left before Right
    spread = _textured_manga_page(1600, 1000)
    rtl_blocks, rtl_splits = prepare_manga_page_blocks(6, spread, "p06.png", rtl=True)
    assert [lbl for lbl, _ in rtl_blocks] == ["p06 R", "p06 L"]
    assert all(url.startswith("data:image/webp;base64,") for _, url in rtl_blocks)
    assert set(rtl_splits.keys()) == {"p06 R", "p06 L"}

    ltr_blocks, _ = prepare_manga_page_blocks(6, spread, "p06.png", rtl=False)
    assert [lbl for lbl, _ in ltr_blocks] == ["p06 L", "p06 R"]

    # 2. Standard portrait page is downscaled to 768x1152 + stamped 28px white header (= 1180)
    portrait = _textured_manga_page(800, 1200)
    p_blocks, p_splits = prepare_manga_page_blocks(3, portrait, "p03.png", rtl=True)
    assert [lbl for lbl, _ in p_blocks] == ["p03"]
    assert p_splits == {}
    decoded = Image.open(BytesIO(base64.b64decode(p_blocks[0][1].split(",", 1)[1])))
    assert decoded.size == (768, 1180)

    # 3. Ultra-tall webtoon strip is sliced cleanly into multiple blocks
    tall = _textured_manga_page(600, 2600)
    t_blocks, _ = prepare_manga_page_blocks(1, tall, "p01.png", rtl=True)
    assert len(t_blocks) >= 2
    assert t_blocks[0][0] == "p01 #1"


def test_pixel_grid_zoom_crop_and_contact_sheet():
    page = _textured_manga_page(900, 1300)
    grid_bytes, orig_w, orig_h = render_pixel_grid(page, step=100)
    assert (orig_w, orig_h) == (900, 1300)
    assert len(grid_bytes) > 500

    zoom_bytes, (zx0, zy0, zx1, zy1) = render_zoom_refinement_grid(page, (150, 150, 450, 480))
    assert len(zoom_bytes) > 500
    assert zx0 < 150 and zy0 < 150 and zx1 > 450 and zy1 > 480
    assert zx0 >= 0 and zy0 >= 0 and zx1 <= 900 and zy1 <= 1300

    # Valid face-like crop succeeds
    face_crop = crop_pixel_box(page, (150, 150, 450, 480), pad_ratio=0.04, square_portrait=True)
    assert face_crop is not None

    # Pure white speech bubble region is rejected by stddev gate
    blank_crop = crop_pixel_box(page, (570, 930, 730, 1110), pad_ratio=0.0, square_portrait=False)
    assert blank_crop is None

    # Contact sheet renders labeled WebP
    sheet = render_crop_contact_sheet([(1, "精灵 (character)", face_crop)])
    assert len(sheet) > 500
    sheet_im = Image.open(BytesIO(sheet))
    assert sheet_im.format == "WEBP"


def test_sanitize_understanding_and_note_hint_parsers():
    raw = {
        "summary": "舅舅醒来。",
        "characters": [
            {"name": "Dead-chan", "aliases": ["Stripease"], "source_page": 2},
            {"name": "路人", "aliases": [], "source_page": 3},
            {"name": "舅舅", "aliases": ["おじさん", "Dead-chan", "舅舅"], "source_page": 99},
            {"name": "舅 舅", "aliases": [], "source_page": 4},
        ],
        "new_assets": [
            {"name": "招募翻译横幅", "asset_type": "item", "description": "discord.gg/abc", "source_page": 1},
            {"name": "地下城戒指", "asset_type": "item", "description": "发光戒指", "source_page": 5},
            {"name": "地下城戒指", "asset_type": "item", "description": "重复", "source_page": 6},
        ],
        "pit_discoveries": [
            {"title": "汉化组招募", "description": "scanlation ad", "priority": "high"},
            {"title": "低优先伏笔", "description": "low", "priority": "low"},
            {"title": "精灵的戒指去向", "description": "high 1", "priority": "high"},
            {"title": "舅舅为何失忆", "description": "high 2", "priority": "high"},
        ],
        "events": [
            {"description": "Discord.gg 招人", "significance": "normal"},
            {"description": "舅舅施展漂浮魔法", "significance": "major"},
        ],
        "world_rules_discovered": ["scanlation rule", "大巴哈马尔世界存在精灵族"],
    }
    clean = sanitize_understanding(raw, valid_pages={1, 2, 3, 4, 5}, max_new_pits=2)
    assert [c["name"] for c in clean["characters"]] == ["舅舅"]
    assert clean["characters"][0]["aliases"] == ["おじさん"]
    assert clean["characters"][0]["source_page"] is None  # 99 clamped out of valid_pages
    assert [a["name"] for a in clean["new_assets"]] == ["地下城戒指"]
    assert len(clean["pit_discoveries"]) == 2
    assert {p["title"] for p in clean["pit_discoveries"]} == {"精灵的戒指去向", "舅舅为何失忆"}
    assert len(clean["events"]) == 1
    assert clean["world_rules_discovered"] == ["大巴哈马尔世界存在精灵族"]

    notes = (
        "- p04: 精灵出现\n"
        "- ★裁剪候选 [character] 精灵 @ p06 R: 右半页清晰正面脸\n"
        "- ★裁剪候选 [item] 地下城戒指 @ p04: 发光宝石戒指\n"
        "- ?需放大复核 @ p03: 魔法阵小字\n"
    )
    hints = understanding_service._parse_crop_hints_from_notes(notes)
    assert "精灵" in hints and hints["精灵"][0]["page_num"] == 6 and hints["精灵"][0]["split_label"] == "p06 R"
    zooms = understanding_service._parse_zoom_requests_from_notes(notes)
    assert zooms == [(3, "", "魔法阵小字")]

    # Deterministic JSON recovery handles unescaped inner quotes & trailing commas
    tricky = 'Here is JSON:\n```json\n{"summary": "他说"你好"然后走了", "events": [],}\n```'
    recovered = understanding_service._extract_json_object(tricky)
    assert recovered["summary"] == '他说"你好"然后走了'
    assert recovered["events"] == []

    # Relational/possessive alias must NEVER merge two distinct characters (e.g. Fujimiya into Takafumi!)
    from app.services import generation_service

    takafumi = Asset(
        id="a1",
        project_id="p1",
        type="character",
        name="侄子敬一",
        tags={"aliases": ["敬一", "タカフミ"]},
    )
    assert not generation_service._asset_matches_name(
        takafumi, "富士宫", ["藤宫", "富士宫（敬一的小学同学）", "敬一的小学同学", "Fujimiya"]
    )
    assert generation_service._asset_matches_name(takafumi, "敬一", [])
    fujimiya = Asset(id="a2", project_id="p1", type="character", name="藤宫澄夏", tags={"aliases": ["Fujimiya"]})
    assert generation_service._asset_matches_name(fujimiya, "藤宫", [])


def test_end_to_end_two_phase_understanding_and_2stage_crop():
    async def _run():
        db = _make_memory_db()
        project = Project(id=str(uuid.uuid4()), title="异世界舅舅", language="zh", canon_rules={})
        episode = Episode(
            id=str(uuid.uuid4()),
            project_id=project.id,
            branch_id="main",
            number=1,
            label="1",
            title="第1话",
            status="imported",
        )
        db.add(project)
        db.add(episode)
        await db.commit()

        page_bytes = _textured_manga_page(800, 1200)
        stored_uploads: dict[str, bytes] = {}

        def fake_get_object_bytes(_bucket, key):
            if key.startswith("pages/"):
                return page_bytes
            return stored_uploads.get(key)

        def fake_upload_file(_bucket, key, data, content_type="image/png"):
            stored_uploads[key] = data
            return key

        call_log: list[dict] = []
        synth_calls = {"count": 0}

        class _FakeCompletions:
            async def create(self, **kwargs):
                msgs = kwargs["messages"]
                sys_msg = msgs[0]["content"] if msgs[0]["role"] == "system" else ""
                user_content = msgs[-1]["content"]
                user_text = (
                    user_content
                    if isinstance(user_content, str)
                    else "\n".join(b.get("text", "") for b in user_content if b.get("type") == "text")
                )
                call_log.append({"sys": sys_msg[:40], "user_preview": user_text[:120], "content": user_content})

                # Phase A: Zoom HD re-read
                if "Zoomed HD re-read" in user_text:
                    reply = "- p03 高清确认：魔法咒语为『伊丘拉斯·艾斯兰』。"
                # Phase A: Sequential reading window
                elif "Next Pages to Read" in user_text:
                    if "Window 1/" in user_text:
                        reply = (
                            "- p01~p04: 舅舅昏迷17年苏醒，敬文接他回家。\n"
                            "- ★裁剪候选 [character] 舅舅 @ p02: 正面戴眼镜特写\n"
                            "- ★裁剪候选 [item] 地下城戒指 @ p03: 发光宝石戒指\n"
                            "- ?需放大复核 @ p03: 魔法咒语小字"
                        )
                    else:
                        # Assert rolling earlier notes were injected into Window 2!
                        assert "舅舅昏迷17年苏醒" in user_text
                        reply = "- p05: 舅舅展示魔法，敬文决定和他合租。"
                # Phase B: Whole-episode synthesis (first attempt deliberately malformed to test auto-repair!)
                elif "Complete Sequential Page-by-Page Reading Notes" in user_text or "failed validation" in user_text:
                    synth_calls["count"] += 1
                    if synth_calls["count"] == 1:
                        reply = "{not valid json"
                    else:
                        reply = json.dumps(
                            {
                                "summary": "昏迷十七年的舅舅在医院苏醒，用异世界魔法震慑外甥敬文并开启同居生活。",
                                "main_plot": {
                                    "core_conflict": "舅舅在异世界归来后适应现代社会",
                                    "current_arc": "归来篇",
                                    "protagonist_goal": "靠魔法与视频谋生",
                                    "arc_progress": "刚出院同居",
                                    "next_hook": "舅舅记忆中的异世界冒险",
                                },
                                "ending_state": {
                                    "location": "敬文公寓",
                                    "time_of_day": "夜晚",
                                    "active_characters": ["舅舅", "敬文"],
                                    "emotional_tone": "搞笑震惊",
                                    "cliffhanger": "异世界往事待揭晓",
                                },
                                "art_style_notes": "黑白日式喜剧漫画，网点精细",
                                "world_rules_discovered": ["舅舅可召唤精灵使用魔法"],
                                "events": [
                                    {
                                        "description": "舅舅在医院施展漂浮魔法",
                                        "characters_involved": ["舅舅", "敬文"],
                                        "location": "医院",
                                        "items_involved": [],
                                        "significance": "major",
                                    }
                                ],
                                "state_changes": [],
                                "characters": [
                                    {
                                        "name": "舅舅",
                                        "aliases": ["おじさん", "Uncle"],
                                        "appearance": "长发戴眼镜大叔",
                                        "role": "protagonist",
                                        "vital_status": "alive",
                                        "source_page": 2,
                                    },
                                    {
                                        "name": "Dead-chan",
                                        "aliases": [],
                                        "appearance": "scanlation mascot",
                                        "role": "cameo",
                                        "source_page": 1,
                                    },
                                ],
                                "asset_sightings": [],
                                "new_assets": [
                                    {
                                        "name": "地下城戒指",
                                        "aliases": [],
                                        "asset_type": "item",
                                        "description": "发光宝石戒指",
                                        "visual_tags": ["glowing ring"],
                                        "source_page": 3,
                                    },
                                    {
                                        "name": "口头提到的烤红薯",
                                        "aliases": [],
                                        "asset_type": "item",
                                        "description": "只在对话里提到没画出来",
                                        "visual_tags": ["sweet potato"],
                                        "source_page": 4,
                                    },
                                ],
                                "pit_discoveries": [
                                    {
                                        "title": "舅舅为何昏迷十七年并穿越异世界",
                                        "description": "卡车撞击后灵魂穿越机制未明",
                                        "priority": "high",
                                        "related_characters": ["舅舅"],
                                    }
                                ],
                                "pit_progressions": [],
                                "resolved_pits": [],
                                "page_dialogues": [
                                    {
                                        "page_number": 2,
                                        "lines": [{"speaker": "舅舅", "text": "世嘉还活着吗", "line_type": "speech"}],
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        )
                # Stage 1: Coarse pixel grid
                elif "TRUE-PIXEL coordinate grid" in user_text:
                    ids = []
                    for line in user_text.splitlines():
                        if line.startswith("- id="):
                            aid = line.split("id=", 1)[1].split(" | ", 1)[0].strip()
                            ids.append((aid, line))
                    crops = []
                    for aid, line in ids:
                        if "口头提到的烤红薯" in line:
                            continue  # Not drawn on page -> omitted!
                        crops.append(
                            {
                                "id": aid,
                                "x0": 150,
                                "y0": 150,
                                "x1": 450,
                                "y1": 480,
                                "score": 9.0,
                                "full_view": True,
                                "classic_look": True,
                            }
                        )
                    reply = json.dumps({"crops": crops})
                # Stage 2: Zoom refinement grid
                elif "Zoomed refinement view" in user_text:
                    reply = json.dumps({"x0": 165, "y0": 165, "x1": 435, "y1": 465})
                # Stage 3: Contact-sheet self-inspection
                elif "Visual QA self-inspection" in user_text:
                    reviews = [
                        {
                            "num": 1,
                            "what": "清晰眼镜正面头像",
                            "verdict": "ok",
                            "dx0": 0,
                            "dy0": 0,
                            "dx1": 0,
                            "dy1": 0,
                            "score": 9.2,
                        },
                        {
                            "num": 2,
                            "what": "发光宝石戒指略偏左",
                            "verdict": "adjust",
                            "dx0": -10,
                            "dy0": -10,
                            "dx1": 10,
                            "dy1": 10,
                            "score": 8.6,
                        },
                    ]
                    reply = json.dumps({"reviews": reviews})
                else:
                    reply = "{}"

                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
        fake_cfg = SimpleNamespace(
            role="vision_llm",
            provider_key="glm_coding",
            model="glm-5.4",
            base_url="https://example.invalid/v1",
            api_key="test-key",
            max_tokens=4096,
        )

        page_refs = [(i, f"pages/p{i:02d}.png") for i in range(1, 10)]  # 9 pages -> 2 windows (8 + 1)!
        with (
            patch.object(understanding_service.storage_service, "get_object_bytes", side_effect=fake_get_object_bytes),
            patch.object(understanding_service.storage_service, "upload_file", side_effect=fake_upload_file),
            patch.object(understanding_service, "get_active_llm_config", return_value=fake_cfg),
            patch.object(understanding_service, "get_raw_openai_client", return_value=fake_client),
            patch.object(understanding_service.memory_service, "vectorize_and_store_episode_memory", return_value=None),
            patch.object(understanding_service.memory_service, "append_episode_summary", return_value=None),
        ):
            result = await understanding_service.run_multimodal_understanding(db, episode, page_refs)

        assert synth_calls["count"] == 2  # Verified automatic JSON repair retry worked!
        assert [c["name"] for c in result["characters"]] == ["舅舅"]  # Dead-chan stripped!

        assets = list((await db.execute(select(Asset).where(Asset.project_id == project.id))).scalars().all())
        asset_names = {a.name for a in assets}
        assert "舅舅" in asset_names
        assert "地下城戒指" in asset_names
        assert "口头提到的烤红薯" not in asset_names  # Ungrounded newly discovered item was cleanly pruned!
        assert "Dead-chan" not in asset_names

        # Both 舅舅 and 地下城戒指 got verified crops uploaded!
        for target_name in ("舅舅", "地下城戒指"):
            a = next(x for x in assets if x.name == target_name)
            imgs = list((await db.execute(select(AssetImage).where(AssetImage.asset_id == a.id))).scalars().all())
            assert len(imgs) == 1
            assert imgs[0].meta["refined_2stage"] is True

        # Memories & pits & story bible persisted
        mem_q = select(EpisodeMemory).where(EpisodeMemory.episode_id == episode.id)
        mems = list((await db.execute(mem_q)).scalars().all())
        assert {m.type for m in mems} == {"summary", "ocr_dump"}
        pits = list((await db.execute(select(Pit).where(Pit.project_id == project.id))).scalars().all())
        assert len(pits) == 1
        assert project.canon_rules["story_bible"]["main_plot"]["current_arc"] == "归来篇"

    asyncio.run(_run())


def test_streaming_completion_and_telemetry_tracking():
    async def _run():
        from app.core.telemetry import instrument_openai_client, set_usage_test_sink, usage_context

        class _FakeStream:
            def __init__(self):
                self._items = [
                    SimpleNamespace(
                        model="glm-5.4",
                        usage=None,
                        choices=[SimpleNamespace(delta=SimpleNamespace(content='{"summary": '))],
                    ),
                    SimpleNamespace(
                        model="glm-5.4",
                        usage=None,
                        choices=[SimpleNamespace(delta=SimpleNamespace(content='"ok"}'))],
                    ),
                    SimpleNamespace(
                        model="glm-5.4",
                        usage=SimpleNamespace(
                            prompt_tokens=1200,
                            completion_tokens=45,
                            total_tokens=1245,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=800),
                            completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
                        ),
                        choices=[],
                    ),
                ]
                self._i = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._i >= len(self._items):
                    raise StopAsyncIteration
                item = self._items[self._i]
                self._i += 1
                return item

        class _FakeCompletions:
            async def create(self, **kwargs):
                assert kwargs.get("stream") is True
                assert kwargs.get("stream_options") == {"include_usage": True}
                return _FakeStream()

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
        instrument_openai_client(fake_client, provider="glm_coding")  # type: ignore[arg-type]

        recorded: list[dict] = []
        set_usage_test_sink(lambda ev: recorded.append(ev))
        try:
            with usage_context(project_id="proj-1", episode_id="ep-1", operation="understand_read"):
                txt = await understanding_service._create_completion_text(
                    fake_client,
                    stream=True,
                    model="glm-5.4",
                    messages=[{"role": "user", "content": "hi"}],
                )
        finally:
            set_usage_test_sink(None)

        assert txt == '{"summary": "ok"}'
        assert len(recorded) == 1
        assert recorded[0]["input_tokens"] == 1200
        assert recorded[0]["output_tokens"] == 45
        assert recorded[0]["cache_read_tokens"] == 800
        assert recorded[0]["operation"] == "understand_read"
        assert recorded[0]["meta"]["streamed"] is True

    asyncio.run(_run())
