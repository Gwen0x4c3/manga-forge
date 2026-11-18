from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select

from app.config import settings
from app.core.image_backend import get_image_backend
from app.core.llm import get_raw_openai_client
from app.models.asset import Asset
from app.models.asset_image import AssetImage
from app.models.generated_image import GeneratedImage
from app.models.pit import Pit
from app.models.project import Project
from app.services import memory_service, storage_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.episode import Episode

logger = logging.getLogger(__name__)

MAX_AGENT_STEPS = 40
MAX_REFERENCES_PER_PANEL = 8
_REF_KIND_PRIORITY = ("reference", "turnaround", "thumbnail", "lora_dataset")

RENDER_AGENT_SYSTEM_PROMPT = """You are the rendering director agent of a manga continuation pipeline. \
You turn an approved storyboard into visually consistent manga panel illustrations.

Workflow for every episode:
1. RESEARCH FIRST — before generating anything, inspect story and visual assets:
   - call search_story_memories with the episode synopsis to recall key continuity details
   - call list_open_pits to know which foreshadowing details must stay visually accurate
   - call search_assets for every character, location, key item, and style appearing in the panels
   - call get_asset_references for matched assets to check available reference sheets / thumbnails
2. THEN GENERATE — call generate_panel once for every panel in the storyboard, in order:
   - Pass relevant character/item/location/style asset IDs in `reference_asset_ids` to anchor visuals.
   - Build a rich English `prompt` combining the storyboard's base `prompt`, exact character appearance/outfit \
from assets, key props/locations, camera angle, lighting, and the series' manga art style.
   - Keep raw artwork free of speech bubbles or text (`negative_prompt`: "speech bubble, text, watermark, blurry").

Rules:
- Every panel_id must be generated exactly once. Never invent panel ids.
- Prefer attaching reference_asset_ids whenever an asset exists.
- Act directly through tools without verbose commentary; finish with a one-line summary once all panels are rendered."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_assets",
            "description": (
                "Search project assets (characters, outfits, locations, items, styles) by keyword. "
                "Returns asset_id, name, type, description and visual tags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to match asset name/description (empty returns top assets)",
                    },
                    "asset_type": {
                        "type": "string",
                        "description": "Optional type filter: character|outfit|location|item|style",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_asset_references",
            "description": (
                "List reference images (character sheets, turnarounds, thumbnails, style refs) "
                "attached to an asset."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string"},
                },
                "required": ["asset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_story_memories",
            "description": "Semantic/keyword search over past episode summaries and events for visual continuity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_open_pits",
            "description": "List unresolved foreshadowing (pits) that must stay visually consistent in new panels.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_panel",
            "description": (
                "Generate one storyboard panel image. Attaches reference images of the given "
                "assets and character/style context to keep visuals consistent, then saves the result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "panel_id": {"type": "string", "description": "Panel id from the storyboard, e.g. '1-1'"},
                    "prompt": {
                        "type": "string",
                        "description": "Final English image prompt enriched with asset visuals & manga style",
                    },
                    "negative_prompt": {"type": "string", "description": "Things to avoid (e.g. speech bubbles, text)"},
                    "reference_asset_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Asset ids (characters, items, locations, style) whose reference images "
                            "and descriptions anchor this panel"
                        ),
                    },
                },
                "required": ["panel_id", "prompt"],
            },
        },
    },
]


class RenderAgent:
    """Tool-calling agent that researches story context and asset references,
    then renders every storyboard panel through the configured image backend."""

    def __init__(
        self,
        db: AsyncSession,
        episode: Episode,
        run_id: str,
        image_backend_name: str | None,
        image_model: str | None,
        image_size: str,
    ):
        self.db = db
        self.episode = episode
        self.run_id = run_id
        self.image_backend_name = image_backend_name
        self.image_model = image_model
        self.image_size = image_size
        w, h = (image_size or "1024x1024").split("x")
        self.size = (int(w), int(h))
        self.panel_sizes: dict[str, tuple[int, int]] = {}
        self.rendered: dict[str, str] = {}
        self.trace: list[dict] = []
        self.art_style: str = ""
        self.style_asset_id: str | None = None
        self._db_lock = asyncio.Lock()
        self._render_sem = asyncio.Semaphore(4)
        self.backend = get_image_backend(backend_name=image_backend_name, model=image_model)

    async def _load_style_context(self) -> None:
        project = (
            await self.db.execute(select(Project).where(Project.id == self.episode.project_id).limit(1))
        ).scalar_one_or_none()
        if project and project.canon_rules:
            self.art_style = ((project.canon_rules or {}).get("story_bible") or {}).get("art_style", "")
        style_asset = (
            await self.db.execute(
                select(Asset).where(Asset.project_id == self.episode.project_id, Asset.type == "style").limit(1)
            )
        ).scalar_one_or_none()
        if style_asset:
            self.style_asset_id = style_asset.id
            if not self.art_style and style_asset.description:
                self.art_style = style_asset.description

    def _compute_panel_sizes(self, storyboard: dict) -> None:
        if self.size != (1024, 1024):
            return
        from app.core.layout_engine import LayoutEngine

        engine = LayoutEngine()
        for page in storyboard.get("pages", []):
            p_list = page.get("panels", [])
            if not p_list:
                continue
            boxes = engine._apply_layout(page.get("layout", ""), len(p_list))
            for panel, (_px, _py, pw, ph) in zip(p_list, boxes):
                pid = panel.get("panel_id")
                if pid and pw > 0 and ph > 0:
                    ratio = pw / ph
                    if ratio >= 1.25:
                        self.panel_sizes[pid] = (int(round(1024 * min(ratio, 2.0))), 1024)
                    elif ratio <= 0.80:
                        self.panel_sizes[pid] = (1024, int(round(1024 / max(ratio, 0.5))))
                    else:
                        self.panel_sizes[pid] = (1024, 1024)

    async def run(self, storyboard: dict) -> dict:
        panels = [p for page in storyboard.get("pages", []) for p in page.get("panels", [])]
        if not panels:
            raise ValueError("Storyboard has no panels")

        self._compute_panel_sizes(storyboard)
        await self._load_style_context()
        brief = self._build_brief(storyboard, panels)
        client = get_raw_openai_client()
        messages: list[dict] = [
            {"role": "system", "content": RENDER_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": brief},
        ]

        fallback: list[str] = []
        nudged_missing = False
        try:
            for step in range(MAX_AGENT_STEPS):
                response = await client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                )
                message = response.choices[0].message
                tool_calls = getattr(message, "tool_calls", None) or []

                if not tool_calls:
                    remaining_ids = [p.get("panel_id") for p in panels if p.get("panel_id") not in self.rendered]
                    if remaining_ids and not nudged_missing:
                        nudged_missing = True
                        messages.append({"role": "assistant", "content": message.content or ""})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"Incomplete: {len(remaining_ids)} panel(s) still unrendered: {remaining_ids}. "
                                    "Call generate_panel for each remaining panel_id now."
                                ),
                            }
                        )
                        continue
                    break

                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )
                # Execute batched tool calls concurrently (DB access serialized via self._db_lock)
                results = await asyncio.gather(
                    *(self._execute(tc.function.name, tc.function.arguments) for tc in tool_calls)
                )
                for tc, result in zip(tool_calls, results):
                    self.trace.append({"tool": tc.function.name, "args": tc.function.arguments[:200]})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str)[:4000],
                        }
                    )

                if len(self.rendered) >= len(panels) and step >= 1:
                    break
        except Exception:
            logger.warning("Render agent loop failed, using mechanical fallback", exc_info=True)

        missing = [p for p in panels if p.get("panel_id") not in self.rendered]
        for panel in missing:
            ok = await self._generate_panel(
                panel_id=panel.get("panel_id", ""),
                prompt=self._mechanical_prompt(panel),
                negative_prompt=panel.get("negative_prompt"),
                reference_asset_ids=await self._auto_assets(panel),
                mechanical=True,
            )
            if ok:
                fallback.append(panel.get("panel_id"))

        return {
            "rendered": self.rendered,
            "agent_rendered": [pid for pid in self.rendered if pid not in fallback],
            "fallback_rendered": fallback,
            "total": len(panels),
            "trace": self.trace,
        }

    def _build_brief(self, storyboard: dict, panels: list[dict]) -> str:
        lines = [
            "Generate all panel images for this manga episode.",
            f"Title: {storyboard.get('title', '')}",
            f"Synopsis: {storyboard.get('synopsis', '')}",
            f"Series Art Style: {self.art_style or 'Manga style, consistent character designs and ink linework'}",
            "",
            "Panels to render (in order):",
        ]
        for p in panels:
            chars = ", ".join(
                c.get("name", "")
                + (f" [outfit: {c.get('outfit')}]" if c.get("outfit") else "")
                + (f" [emotion: {c.get('emotion')}]" if c.get("emotion") else "")
                + (f" [pose: {c.get('posture')}]" if c.get("posture") else "")
                for c in p.get("characters", [])
            )
            items = ", ".join(str(it) for it in (p.get("items") or []))
            loc = p.get("location") or ""
            dialogue = " / ".join(d.get("text", "") for d in p.get("dialogue", [])[:3])
            base_prompt = p.get("prompt", "")
            lines.append(
                f"- {p.get('panel_id')}: base_prompt={base_prompt!r}; scene={p.get('scene', '')}; "
                f"location={loc}; items=[{items}]; characters=[{chars}]; "
                f"camera={p.get('camera', '')}; mood={p.get('mood', '')}; dialogue_context: {dialogue}"
            )
        return "\n".join(lines)

    async def _execute(self, name: str, arguments: str) -> Any:
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return {"error": "invalid tool arguments"}

        handlers = {
            "search_assets": lambda: self._tool_search_assets(str(args.get("query", "")), args.get("asset_type")),
            "get_asset_references": lambda: self._tool_asset_references(str(args.get("asset_id", ""))),
            "search_story_memories": lambda: self._tool_search_memories(str(args.get("query", ""))),
            "list_open_pits": lambda: self._tool_open_pits(),
            "generate_panel": lambda: self._tool_generate_panel(args),
        }
        handler = handlers.get(name)
        if handler is None:
            return {"error": f"unknown tool {name}"}
        try:
            return await handler()
        except Exception as exc:
            logger.warning("Render agent tool %s failed: %s", name, exc, exc_info=True)
            return {"error": str(exc)[:300]}

    async def _tool_search_assets(self, query: str, asset_type: str | None) -> list[dict]:
        stmt = select(Asset).where(Asset.project_id == self.episode.project_id)
        if asset_type:
            stmt = stmt.where(Asset.type == asset_type)
        async with self._db_lock:
            all_rows = list((await self.db.execute(stmt)).scalars().all())

        q = query.strip().lower()
        if q:
            matched: list[Asset] = []
            for a in all_rows:
                tags = a.tags or {}
                hay = " ".join(
                    [
                        a.name or "",
                        a.description or "",
                        *(str(x) for x in (tags.get("aliases") or [])),
                        *(str(x) for x in (tags.get("visual_tags") or [])),
                    ]
                ).lower()
                if q in hay:
                    matched.append(a)
            rows = matched[:25]
        else:
            all_rows.sort(key=lambda a: -len(a.episode_ids or {}))
            rows = all_rows[:25]

        return [
            {
                "asset_id": a.id,
                "name": a.name,
                "type": a.type,
                "aliases": (a.tags or {}).get("aliases", []),
                "description": (a.description or "")[:320],
                "visual_tags": (a.tags or {}).get("visual_tags", []),
            }
            for a in rows
        ]

    async def _tool_asset_references(self, asset_id: str) -> dict:
        async with self._db_lock:
            rows = (
                (await self.db.execute(select(AssetImage).where(AssetImage.asset_id == asset_id).limit(20)))
                .scalars()
                .all()
            )
        return {
            "asset_id": asset_id,
            "references": [{"image_id": r.id, "kind": r.kind, "object_key": r.image_path} for r in rows],
        }

    async def _tool_search_memories(self, query: str) -> list[dict]:
        async with self._db_lock:
            results = await memory_service.search_rag(
                self.db,
                self.episode.project_id,
                query,
                top_k=5,
                max_episode_number=self.episode.number,
            )
        return [
            {
                "episode_number": r["payload"].get("episode_number"),
                "type": r["payload"].get("type"),
                "content": str(r["payload"].get("content", ""))[:500],
            }
            for r in results
        ]

    async def _tool_open_pits(self) -> list[dict]:
        async with self._db_lock:
            rows = (
                (
                    await self.db.execute(
                        select(Pit).where(Pit.project_id == self.episode.project_id, Pit.status == "open").limit(30)
                    )
                )
                .scalars()
                .all()
            )
        return [{"description": p.description or p.title, "trigger_hint": p.trigger_hint} for p in rows]

    async def _tool_generate_panel(self, args: dict) -> dict:
        panel_id = str(args.get("panel_id", ""))
        if panel_id in self.rendered:
            return {"status": "already_rendered", "image_path": self.rendered[panel_id]}
        ok = await self._generate_panel(
            panel_id=panel_id,
            prompt=str(args.get("prompt", "")),
            negative_prompt=args.get("negative_prompt"),
            reference_asset_ids=[str(a) for a in args.get("reference_asset_ids", []) or []],
        )
        return {"status": "ok", "image_path": self.rendered.get(panel_id)} if ok else {"status": "failed"}

    async def _generate_panel(
        self,
        panel_id: str,
        prompt: str,
        negative_prompt: str | None = None,
        reference_asset_ids: list[str] | None = None,
        mechanical: bool = False,
    ) -> bool:
        if not prompt.strip() or not panel_id:
            return False

        effective_ids = list(dict.fromkeys(reference_asset_ids or []))
        if self.style_asset_id and self.style_asset_id not in effective_ids:
            effective_ids.append(self.style_asset_id)

        reference_images: list[tuple[bytes, str]] = []
        context: dict = {
            "episode_number": self.episode.number,
            "panel_id": panel_id,
            "characters": [],
            "locations": [],
            "items": [],
            "art_style": self.art_style,
            "style_tags": [],
        }
        ref_names: list[str] = []

        asset_images_map: dict[str, list[AssetImage]] = {}
        async with self._db_lock:
            if effective_ids:
                assets_rows = (
                    (
                        await self.db.execute(
                            select(Asset).where(
                                Asset.project_id == self.episode.project_id,
                                Asset.id.in_(effective_ids),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                by_id = {a.id: a for a in assets_rows}
                assets = [by_id[aid] for aid in effective_ids if aid in by_id]
                if assets:
                    all_imgs = (
                        (
                            await self.db.execute(
                                select(AssetImage).where(AssetImage.asset_id.in_([a.id for a in assets]))
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for im in all_imgs:
                        asset_images_map.setdefault(im.asset_id, []).append(im)
            else:
                assets = []

        for asset in assets:
            if asset.type != "style":
                ref_names.append(asset.name)
            if asset.type == "character":
                context["characters"].append({"name": asset.name, "appearance": (asset.description or "")[:240]})
            elif asset.type == "location":
                context["locations"].append({"name": asset.name, "description": (asset.description or "")[:200]})
            elif asset.type in ("item", "outfit"):
                context["items"].append({"name": asset.name, "description": (asset.description or "")[:200]})
            elif asset.type == "style":
                context["style_tags"].extend((asset.tags or {}).get("visual_tags", []))

            images = list(asset_images_map.get(asset.id, []))
            images.sort(key=lambda img: _REF_KIND_PRIORITY.index(img.kind) if img.kind in _REF_KIND_PRIORITY else 99)
            max_per_asset = 1 if asset.type == "style" else 2
            for img in images[:max_per_asset]:
                if len(reference_images) >= MAX_REFERENCES_PER_PANEL:
                    break
                data = storage_service.get_object_bytes(settings.MINIO_BUCKET, img.image_path)
                if data:
                    lower_p = img.image_path.lower()
                    mime = (
                        "image/png"
                        if lower_p.endswith(".png")
                        else ("image/webp" if lower_p.endswith(".webp") else "image/jpeg")
                    )
                    reference_images.append((data, mime))

        neg = negative_prompt or "speech bubble, text, dialogue balloon, watermark, signature, blurry"
        target_size = self.panel_sizes.get(panel_id, self.size)

        async with self._render_sem:
            result = await self.backend.generate(
                prompt=prompt,
                negative_prompt=neg,
                size=target_size,
                reference_images=reference_images or None,
                context=context,
                model=self.image_model or None,
            )
            object_key = storage_service.generate_object_key(f"generated/{self.episode.id}", f"{panel_id}.png")
            storage_service.upload_file(settings.MINIO_BUCKET, object_key, result.image_data, content_type="image/png")

        async with self._db_lock:
            await self.db.execute(
                delete(GeneratedImage).where(
                    GeneratedImage.episode_id == self.episode.id,
                    GeneratedImage.panel_id == panel_id,
                )
            )
            gen_image = GeneratedImage(
                id=str(uuid.uuid4()),
                generation_run_id=self.run_id,
                episode_id=self.episode.id,
                panel_id=panel_id,
                image_path=object_key,
                meta={
                    **result.meta,
                    "prompt": prompt,
                    "seed": result.seed,
                    "reference_assets": ref_names,
                    "rendered_by": "fallback" if mechanical else "agent",
                },
            )
            self.db.add(gen_image)
            await self.db.commit()
            self.rendered[panel_id] = object_key
        return True

    def _mechanical_prompt(self, panel: dict) -> str:
        parts = [panel.get("prompt", "") or panel.get("scene", "")]
        if panel.get("camera"):
            parts.append(f"{panel['camera']} shot")
        if panel.get("location"):
            parts.append(f"setting: {panel['location']}")
        for c in panel.get("characters", []):
            desc = ", ".join(x for x in (c.get("outfit"), c.get("emotion"), c.get("posture")) if x)
            parts.append(f"{c.get('name', '')} ({desc})" if desc else c.get("name", ""))
        for it in panel.get("items", []) or []:
            parts.append(f"key prop: {it}")
        if self.art_style:
            parts.append(self.art_style)
        return ", ".join(p for p in parts if p)

    async def _auto_assets(self, panel: dict) -> list[str]:
        probe_names: list[str] = [c.get("name", "") for c in panel.get("characters", []) if c.get("name")]
        if panel.get("location"):
            probe_names.append(str(panel["location"]))
        probe_names.extend(str(it) for it in (panel.get("items") or []) if it)

        assets = (
            (await self.db.execute(select(Asset).where(Asset.project_id == self.episode.project_id))).scalars().all()
        )
        from app.services.generation_service import _asset_matches_name

        matched = [a.id for a in assets if a.type == "style" or any(_asset_matches_name(a, n) for n in probe_names)]
        return matched


async def run_render_agent(
    db: AsyncSession,
    episode: Episode,
    storyboard: dict,
    run_id: str,
    image_backend_name: str | None,
    image_model: str | None,
    image_size: str,
) -> dict:
    agent = RenderAgent(db, episode, run_id, image_backend_name, image_model, image_size)
    return await agent.run(storyboard)
