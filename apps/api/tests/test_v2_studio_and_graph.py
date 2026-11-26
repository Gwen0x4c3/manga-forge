from __future__ import annotations

import asyncio
import io
import types
import uuid
import zipfile
from decimal import Decimal

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.core.image_backend import ComfyUIImageBackend
from app.core.layout_engine import LayoutEngine, PanelImage
from app.database import Base
from app.models.asset import Asset
from app.models.asset_image import AssetImage
from app.models.branch import Branch
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.episode_page import EpisodePage
from app.models.pit import Pit
from app.models.project import Project
from app.routers.generation import _build_cbz_bytes, _build_webtoon_bytes
from app.services import asset_service, generation_service, memory_service, storage_service


class AsyncSyncSessionAdapter:
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


def _png_bytes(width: int = 400, height: int = 400, color: tuple[int, int, int] = (230, 235, 242)) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_build_story_graph_and_ask_bible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_service, "embeddings_configured", lambda: False)
    db = _make_memory_db()

    captured_calls: list[dict] = []

    class _FakeCompletions:
        async def create(self, **kwargs):  # type: ignore[no-untyped-def]
            captured_calls.append(kwargs)
            return types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        message=types.SimpleNamespace(
                            content="根据第1话和第2话，舅舅在异世界使用精灵魔法『冰霜之手』并经常提起世嘉土星。[第1话][第2话]",
                            reasoning_content=None,
                        )
                    )
                ]
            )

    from app.core import llm as core_llm

    fake_client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=_FakeCompletions()))
    monkeypatch.setattr(core_llm, "get_raw_openai_client", lambda: fake_client)

    async def _run() -> None:
        pid = str(uuid.uuid4())
        bid_main = str(uuid.uuid4())
        bid_alt = str(uuid.uuid4())
        ep1_id = str(uuid.uuid4())
        ep2_id = str(uuid.uuid4())
        ep_alt_id = str(uuid.uuid4())

        db.add(
            Project(
                id=pid,
                title="异世界舅舅",
                language="zh",
                canon_rules={
                    "story_bible": {
                        "art_style": "bw manga ink",
                        "core_rules": ["魔法依赖与精灵对话"],
                        "discovered_rules": ["世嘉主机是舅舅的精神支柱"],
                        "arc_summaries": [
                            {
                                "arc_index": 1,
                                "start_episode": 1,
                                "end_episode": 2,
                                "summary": "舅舅苏醒并开始用魔法拍视频。",
                            }
                        ],
                    }
                },
            )
        )
        db.add(Branch(id=bid_main, project_id=pid, name="main", is_default=True))
        db.add(
            Branch(
                id=bid_alt,
                project_id=pid,
                name="sega-win",
                is_default=False,
                base_branch_id=bid_main,
                base_episode_id=ep1_id,
            )
        )
        db.add(
            Episode(
                id=ep1_id,
                project_id=pid,
                branch_id=bid_main,
                number=Decimal("1"),
                label="1",
                title="苏醒",
                source="imported",
                status="understood",
            )
        )
        db.add(
            Episode(
                id=ep2_id,
                project_id=pid,
                branch_id=bid_main,
                number=Decimal("2"),
                label="2",
                title="世嘉回忆",
                source="imported",
                status="understood",
            )
        )
        db.add(
            Episode(
                id=ep_alt_id,
                project_id=pid,
                branch_id=bid_alt,
                number=Decimal("2"),
                label="2",
                title="世嘉称霸分支",
                source="generated",
                status="published",
                parent_episode_id=ep1_id,
            )
        )
        db.add(EpisodePage(id=str(uuid.uuid4()), episode_id=ep1_id, page_index=0, image_path="p1.jpg"))
        db.add(EpisodePage(id=str(uuid.uuid4()), episode_id=ep2_id, page_index=0, image_path="p2.jpg"))

        char_ojisan = Asset(
            id=str(uuid.uuid4()),
            project_id=pid,
            type="character",
            name="舅舅",
            description="沉迷世嘉游戏的中年大叔",
            tags={"role": "protagonist", "speech_style": "平淡冷吐槽", "aliases": ["高丘敬文舅舅"]},
            episode_ids={ep1_id: True, ep2_id: True},
        )
        char_taka = Asset(
            id=str(uuid.uuid4()),
            project_id=pid,
            type="character",
            name="敬文",
            description="负责吐槽的大学生外甥",
            tags={"role": "main"},
            episode_ids={ep1_id: True, ep2_id: True},
        )
        outfit_ojisan = Asset(
            id=str(uuid.uuid4()),
            project_id=pid,
            type="outfit",
            name="舅舅的病号服",
            description="医院蓝白条纹病号服",
            parent_asset_id=char_ojisan.id,
            episode_ids={ep1_id: True},
        )
        db.add(char_ojisan)
        db.add(char_taka)
        db.add(outfit_ojisan)
        db.add(
            AssetImage(
                id=str(uuid.uuid4()),
                asset_id=char_ojisan.id,
                kind="reference",
                image_path="assets/ojisan/ref.png",
            )
        )

        db.add(
            EpisodeMemory(
                id=str(uuid.uuid4()),
                episode_id=ep1_id,
                type="summary",
                content={
                    "summary": "舅舅昏迷17年后苏醒，展示异世界魔法让敬文震惊。",
                    "events": [{"description": "舅舅在病房用精灵魔法浮起水杯", "significance": "turning_point"}],
                    "state_changes": [{"character": "舅舅", "attribute": "住处", "after": "搬入敬文出租屋"}],
                    "ending_state": {"active_characters": ["舅舅", "敬文"], "location": "出租屋"},
                    "character_sightings": [{"name": "舅舅"}, {"name": "敬文"}],
                },
            )
        )
        db.add(
            EpisodeMemory(
                id=str(uuid.uuid4()),
                episode_id=ep2_id,
                type="summary",
                content={
                    "summary": "舅舅得知世嘉退出主机市场后崩溃，与敬文一起回忆土星主机。",
                    "events": [{"description": "舅舅在屋里用冰霜魔法冷静情绪", "significance": "major"}],
                    "ending_state": {"active_characters": ["舅舅", "敬文"], "location": "出租屋"},
                    "character_sightings": [{"name": "舅舅"}, {"name": "敬文"}],
                },
            )
        )
        db.add(
            Pit(
                id=str(uuid.uuid4()),
                project_id=pid,
                title="翠的真实身份",
                description="异世界傲娇精灵一直在寻找舅舅\n[第2话线索] 提到戒指还留在舅舅手中",
                priority=10,
                introduced_episode_id=ep1_id,
                status="open",
                trigger_hint="当回忆起迷宫逃亡时触发",
            )
        )
        await db.commit()

        graph = await memory_service.build_story_graph(db, pid, branch_id=bid_main)  # type: ignore[arg-type]
        assert len(graph["character_graph"]["nodes"]) == 2
        assert len(graph["timeline"]["episodes"]) == 2
        assert len(graph["timeline"]["pit_swimlanes"]) == 1
        assert len(graph["branch_tree"]) == 2
        assert len(graph["character_graph"]["edges"]) == 1
        assert graph["character_graph"]["edges"][0]["weight"] == 2
        ojisan_node = next(n for n in graph["character_graph"]["nodes"] if n["name"] == "舅舅")
        assert ojisan_node["avatar_path"] == "assets/ojisan/ref.png"
        assert len(ojisan_node["outfits"]) == 1
        assert len(ojisan_node["state_timeline"]) == 1
        assert graph["timeline"]["pit_swimlanes"][0]["clues"][0]["episode_number"] == 2.0
        assert graph["story_bible"]["core_rules"] == ["魔法依赖与精灵对话"]

        qa = await memory_service.ask_story_bible(
            db, pid, "舅舅在出租屋用了什么魔法？", branch_id=bid_main  # type: ignore[arg-type]
        )
        assert "冰霜之手" in qa["answer"]
        assert len(qa["citations"]) >= 1
        assert captured_calls[0]["max_tokens"] == settings.OPENAI_MAX_TOKENS

    asyncio.run(_run())


def test_layout_engine_vertical_cjk_styles_and_custom_box() -> None:
    engine = LayoutEngine()
    panels = [
        PanelImage(
            image_data=_png_bytes(600, 600),
            panel_id="1-1",
            dialogues=[
                {
                    "speaker": "舅舅",
                    "text": "「世嘉土星才是最强主机！」",
                    "type": "shout",
                    "custom_box": {"x_pct": 0.42, "y_pct": 0.25, "font_scale": 1.15, "tail_dir": "down-left"},
                },
                {
                    "speaker": "敬文",
                    "text": "（这也太离谱了吧……）",
                    "type": "whisper",
                },
            ],
        ),
        PanelImage(
            image_data=_png_bytes(600, 600),
            panel_id="1-2",
            dialogues=[{"speaker": "旁白", "text": "十七年后的现实世界。", "type": "narration"}],
        ),
    ]
    composed = engine.compose_page("2_vertical", panels, page_number=1, writing_mode="vertical")
    assert composed.writing_mode == "vertical"
    assert len(composed.panel_boxes) == 2
    assert len(composed.bubble_layouts) == 3
    first_bubble = composed.bubble_layouts[0]
    assert first_bubble["panel_id"] == "1-1"
    assert first_bubble["style"] == "shout"
    assert abs(first_bubble["x_pct"] - 0.42) < 0.05
    assert abs(first_bubble["y_pct"] - 0.25) < 0.05
    img = Image.open(io.BytesIO(composed.image_data))
    assert img.size == (LayoutEngine.PAGE_WIDTH, LayoutEngine.PAGE_HEIGHT)


def test_candidate_history_and_selection() -> None:
    db = _make_memory_db()

    async def _run() -> None:
        pid, bid, eid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        db.add(Project(id=pid, title="Test", language="zh"))
        db.add(Branch(id=bid, project_id=pid, name="main", is_default=True))
        db.add(Episode(id=eid, project_id=pid, branch_id=bid, number=Decimal("1"), label="1"))
        await db.commit()

        run = await generation_service.create_generation_run(db, eid, "render")  # type: ignore[arg-type]
        img1 = await generation_service.save_generated_image(
            db, run.id, eid, "1-1", "generated/v1.png", {"prompt": "v1"}, keep_history=True  # type: ignore[arg-type]
        )
        img2 = await generation_service.save_generated_image(
            db, run.id, eid, "1-1", "generated/v2.png", {"prompt": "v2"}, keep_history=True  # type: ignore[arg-type]
        )

        active = await generation_service.get_generated_images(db, eid, include_candidates=False)  # type: ignore[arg-type]
        all_candidates = await generation_service.get_generated_images(db, eid, include_candidates=True)  # type: ignore[arg-type]
        assert len(all_candidates) == 2
        assert len(active) == 1
        assert active[0].id == img2.id

        switched = await generation_service.select_generated_image(db, eid, "1-1", img1.id)  # type: ignore[arg-type]
        assert switched is not None and switched.id == img1.id
        active_after = await generation_service.get_generated_images(db, eid, include_candidates=False)  # type: ignore[arg-type]
        assert active_after[0].id == img1.id

    asyncio.run(_run())


def test_cbz_and_webtoon_export_builders() -> None:
    p1 = _png_bytes(600, 800, (240, 240, 240))
    p2 = _png_bytes(600, 800, (210, 220, 230))
    cbz = _build_cbz_bytes([(1, p1), (2, p2)], title="测试话", number="5")
    with zipfile.ZipFile(io.BytesIO(cbz), "r") as zf:
        names = zf.namelist()
        assert "ComicInfo.xml" in names
        assert len(names) == 3
        xml_text = zf.read("ComicInfo.xml").decode("utf-8")
        assert "<Manga>YesAndRightToLeft</Manga>" in xml_text
        assert "<Number>5</Number>" in xml_text

    webtoon = _build_webtoon_bytes([Image.open(io.BytesIO(p1)), Image.open(io.BytesIO(p2))])
    stitched = Image.open(io.BytesIO(webtoon))
    assert stitched.width == 600
    assert stitched.height > 1600


def test_crop_asset_from_page_and_comfyui_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _make_memory_db()
    uploaded: dict[str, bytes] = {}
    page_blob = _png_bytes(1000, 1400, (180, 190, 200))

    monkeypatch.setattr(storage_service, "get_object_bytes", lambda bucket, key: page_blob)
    monkeypatch.setattr(
        storage_service,
        "upload_file",
        lambda bucket, key, data, content_type="image/png": uploaded.setdefault(key, data),
    )

    async def _run() -> None:
        pid, bid, eid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        db.add(Project(id=pid, title="CropTest", language="zh"))
        db.add(Branch(id=bid, project_id=pid, name="main", is_default=True))
        db.add(Episode(id=eid, project_id=pid, branch_id=bid, number=Decimal("1"), label="1"))
        db.add(EpisodePage(id=str(uuid.uuid4()), episode_id=eid, page_index=0, image_path="raw/p0.png"))
        asset = Asset(id=str(uuid.uuid4()), project_id=pid, type="character", name="主角")
        db.add(asset)
        await db.commit()

        img_row = await asset_service.crop_asset_image_from_page(
            db, asset, eid, 0, [0.1, 0.2, 0.5, 0.6], kind="reference"  # type: ignore[arg-type]
        )
        assert img_row.image_path in uploaded
        cropped_img = Image.open(io.BytesIO(uploaded[img_row.image_path]))
        assert cropped_img.size == (400, 560)
        assert img_row.meta and img_row.meta["cropped_manually"] is True

    asyncio.run(_run())

    # ComfyUI default & custom workflow placeholder substitution
    comfy = ComfyUIImageBackend(model="animagineXL.safetensors")
    default_wf = comfy._build_workflow("manga hero", "blurry", (832, 1216), 4242, [])
    assert default_wf["3"]["inputs"]["seed"] == 4242
    assert default_wf["5"]["inputs"]["width"] == 832
    assert default_wf["5"]["inputs"]["height"] == 1216
    assert default_wf["6"]["inputs"]["text"] == "manga hero"


def test_iterative_character_vital_status_death_branch_isolation_and_revival(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify iterative character death/revival state binding, branch isolation, and long-series lock."""
    monkeypatch.setattr(memory_service, "embeddings_configured", lambda: False)
    db = _make_memory_db()

    async def _run() -> None:
        pid = str(uuid.uuid4())
        bid_main = str(uuid.uuid4())
        bid_whatif = str(uuid.uuid4())
        ep1, ep2, ep3, ep5 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        ep_whatif_3 = str(uuid.uuid4())

        db.add(Project(id=pid, title="Death Lock Manga", language="zh"))
        db.add(Branch(id=bid_main, project_id=pid, name="main", is_default=True))
        db.add(
            Branch(
                id=bid_whatif,
                project_id=pid,
                name="what-if-saved",
                is_default=False,
                base_branch_id=bid_main,
                base_episode_id=ep2,
            )
        )
        for eid, num, lbl in [(ep1, "1", "1"), (ep2, "2", "2"), (ep3, "3", "3"), (ep5, "5", "5")]:
            db.add(
                Episode(
                    id=eid,
                    project_id=pid,
                    branch_id=bid_main,
                    number=Decimal(num),
                    label=lbl,
                    title=f"第{lbl}话",
                    status="understood",
                )
            )
        # What-if branch copies ep1 & ep2 lineage and diverges at ep3 (where Mentor survives)
        ep_w1, ep_w2 = str(uuid.uuid4()), str(uuid.uuid4())
        db.add(Episode(id=ep_w1, project_id=pid, branch_id=bid_whatif, number=Decimal("1"), label="1", parent_episode_id=ep1, status="understood"))
        db.add(Episode(id=ep_w2, project_id=pid, branch_id=bid_whatif, number=Decimal("2"), label="2", parent_episode_id=ep2, status="understood"))
        db.add(Episode(id=ep_whatif_3, project_id=pid, branch_id=bid_whatif, number=Decimal("3"), label="3", parent_episode_id=ep_w2, status="understood"))

        mentor = Asset(
            id=str(uuid.uuid4()),
            project_id=pid,
            type="character",
            name="雷恩导师",
            description="白发剑圣",
            tags={"role": "support"},
            episode_ids={ep1: True, ep3: True},
        )
        db.add(mentor)

        db.add(EpisodeMemory(id=str(uuid.uuid4()), episode_id=ep1, type="summary", content={"summary": "导师登场教导主角。", "state_changes": []}))
        db.add(EpisodeMemory(id=str(uuid.uuid4()), episode_id=ep2, type="summary", content={"summary": "前往边境城。", "state_changes": []}))
        db.add(
            EpisodeMemory(
                id=str(uuid.uuid4()),
                episode_id=ep3,
                type="summary",
                content={
                    "summary": "雷恩导师为掩护主角撤退与魔王军激战。",
                    "state_changes": [
                        {
                            "character": "雷恩导师",
                            "attribute": "vital_status",
                            "before": "存活",
                            "after": "战死",
                            "reason": "替主角挡下致命魔剑",
                        }
                    ],
                },
            )
        )
        db.add(
            EpisodeMemory(
                id=str(uuid.uuid4()),
                episode_id=ep5,
                type="summary",
                content={
                    "summary": "大祭司发动禁术复活了雷恩导师。",
                    "state_changes": [
                        {
                            "character": "雷恩导师",
                            "attribute": "vital_status",
                            "before": "已死亡",
                            "after": "被禁术复活",
                        }
                    ],
                },
            )
        )
        # What-if branch Ep 3: Mentor survives!
        db.add(EpisodeMemory(id=str(uuid.uuid4()), episode_id=ep_w1, type="summary", content={"summary": "导师登场。", "state_changes": []}))
        db.add(EpisodeMemory(id=str(uuid.uuid4()), episode_id=ep_w2, type="summary", content={"summary": "前往边境城。", "state_changes": []}))
        db.add(
            EpisodeMemory(
                id=str(uuid.uuid4()),
                episode_id=ep_whatif_3,
                type="summary",
                content={
                    "summary": "主角及时救下导师，全员生还。",
                    "state_changes": [
                        {"character": "雷恩导师", "attribute": "vital_status", "after": "逃过一死，重伤撤离"}
                    ],
                },
            )
        )
        await db.commit()

        # 1. On main after Ep 3 (cutoff=4): Mentor MUST be deceased & locked in unavailable_characters
        ctx_main_4 = await memory_service.build_context_for_generation(db, pid, bid_main, Decimal("4"))  # type: ignore[arg-type]
        assert len(ctx_main_4["unavailable_characters"]) == 1
        assert ctx_main_4["unavailable_characters"][0]["name"] == "雷恩导师"
        assert ctx_main_4["unavailable_characters"][0]["vital_status"] == "deceased"
        assert ctx_main_4["unavailable_characters"][0]["vital_status_episode"] == "3"

        # 2. On What-If branch after Ep 3: Mentor survived (injured, NOT deceased & NOT locked unavailable!)
        ctx_whatif_4 = await memory_service.build_context_for_generation(db, pid, bid_whatif, Decimal("4"))  # type: ignore[arg-type]
        assert ctx_whatif_4["unavailable_characters"] == []
        mentor_whatif = next(c for c in ctx_whatif_4["character_dossier"] if c["name"] == "雷恩导师")
        assert mentor_whatif["vital_status"] == "injured"
        assert memory_service.infer_vital_status("vital_status", "确认未死亡") == "alive"

        # 3. On main after Ep 5 revival (cutoff=5): Iterative replay flips status back to alive!
        ctx_main_5 = await memory_service.build_context_for_generation(db, pid, bid_main, Decimal("5"))  # type: ignore[arg-type]
        assert ctx_main_5["unavailable_characters"] == []
        mentor_revived = next(c for c in ctx_main_5["character_dossier"] if c["name"] == "雷恩导师")
        assert mentor_revived["vital_status"] == "alive"
        assert mentor_revived["vital_status_episode"] == "5"

        # 4. Story Graph exposes vital_status fields too
        graph = await memory_service.build_story_graph(db, pid, branch_id=bid_main)  # type: ignore[arg-type]
        node = next(n for n in graph["character_graph"]["nodes"] if n["name"] == "雷恩导师")
        assert node["vital_status"] == "alive"
        assert node["vital_status_episode"] == "5"

    asyncio.run(_run())
