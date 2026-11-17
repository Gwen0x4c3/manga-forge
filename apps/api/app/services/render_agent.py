from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.config import settings
from app.core.image_backend import get_image_backend
from app.core.llm import get_raw_openai_client
from app.models.asset import Asset
from app.models.asset_image import AssetImage
from app.models.generated_image import GeneratedImage
from app.models.pit import Pit
from app.services import memory_service, storage_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.episode import Episode

logger = logging.getLogger(__name__)

MAX_AGENT_STEPS = 40
MAX_REFERENCES_PER_PANEL = 8

RENDER_AGENT_SYSTEM_PROMPT = """You are the rendering agent of a manga generation pipeline. \
You turn an approved storyboard into panel images.

Workflow for every episode:
1. RESEARCH FIRST — before generating anything, understand the current story state:
   - call search_story_memories with the episode synopsis to recall relevant past events
   - call list_open_pits to know which foreshadowing must stay consistent
   - call search_assets for each character/location/item that appears in the panels
   - call get_asset_references for the assets you found to see which ones have \
reference images (character sheets, turnarounds, style refs)
2. THEN GENERATE — call generate_panel exactly once for every panel in the storyboard, \
in order. For panels containing established characters, pass their asset ids in \
reference_asset_ids so the image model keeps faces/outfits consistent. Base each \
prompt on the storyboard panel prompt, enriched with the asset descriptions you found \
(appearance, outfit, visual tags) — write prompts in English, keep them specific.

Rules:
- Every panel_id must be generated exactly once. Never invent panel ids.
- Prefer references over long descriptions when a reference image exists.
- Do not narrate progress; act through tools.
- When every panel is generated, reply with a one-line summary and stop."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_assets",
            "description": (
                "Search project assets (characters, outfits, locations, items, styles) by keyword. "
                "Returns id, name, type, description and visual tags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword to match asset name/description"},
                    "asset_type": {"type": "string", "description": "Optional type filter"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_asset_references",
            "description": "List reference images (character sheets, turnarounds, style refs) attached to an asset.",
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
            "description": "Keyword search over past episode summaries and events for story continuity.",
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
            "description": "List unresolved foreshadowing (pits) that must stay consistent in new panels.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_panel",
            "description": (
                "Generate one storyboard panel image. Attaches reference images of the given "
                "assets and character/context info to keep visuals consistent, then saves the result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "panel_id": {"type": "string", "description": "Panel id from the storyboard, e.g. '2-1'"},
                    "prompt": {"type": "string", "description": "Final image prompt (English), asset-enriched"},
                    "negative_prompt": {"type": "string", "description": "Optional things to avoid"},
                    "reference_asset_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Asset ids whose reference images/descriptions should anchor this panel",
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
        w, h = image_size.split("x")
        self.size = (int(w), int(h))
        self.rendered: dict[str, str] = {}
        self.trace: list[dict] = []

        original_backend = settings.IMAGE_BACKEND
        original_model = settings.IMAGE_MODEL
        if image_backend_name:
            settings.IMAGE_BACKEND = image_backend_name
        if image_model:
            settings.IMAGE_MODEL = image_model
        self._restore = (original_backend, original_model)
        self.backend = get_image_backend()

    async def run(self, storyboard: dict) -> dict:
        panels = [p for page in storyboard.get("pages", []) for p in page.get("panels", [])]
        if not panels:
            raise ValueError("Storyboard has no panels")

        brief = self._build_brief(storyboard, panels)
        client = get_raw_openai_client()
        messages: list[dict] = [
            {"role": "system", "content": RENDER_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": brief},
        ]

        fallback: list[str] = []
        try:
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
                        break  # agent is done

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
                    for tc in tool_calls:
                        result = await self._execute(tc.function.name, tc.function.arguments)
                        self.trace.append({"tool": tc.function.name, "args": tc.function.arguments[:200]})
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps(result, ensure_ascii=False, default=str)[:4000],
                            }
                        )

                    if len(self.rendered) >= len(panels) and step >= 2:
                        # everything generated; one more round lets the agent wrap up
                        response = await client.chat.completions.create(
                            model=settings.OPENAI_MODEL, messages=messages
                        )
                        break
            except Exception:
                # Agent LLM failure must not fail the render: fall back to
                # mechanical rendering of whatever is missing.
                logger.warning("Render agent loop failed, using mechanical fallback", exc_info=True)

            missing = [p for p in panels if p.get("panel_id") not in self.rendered]
            for panel in missing:
                ok = await self._generate_panel(
                    panel_id=panel.get("panel_id", ""),
                    prompt=self._mechanical_prompt(panel),
                    reference_asset_ids=await self._auto_assets(panel),
                    mechanical=True,
                )
                if ok:
                    fallback.append(panel.get("panel_id"))
        finally:
            settings.IMAGE_BACKEND, settings.IMAGE_MODEL = self._restore

        return {
            "rendered": self.rendered,
            "agent_rendered": [pid for pid in self.rendered if pid not in fallback],
            "fallback_rendered": fallback,
            "total": len(panels),
            "trace": self.trace,
        }

    # ---- brief ----

    def _build_brief(self, storyboard: dict, panels: list[dict]) -> str:
        lines = [
            "Generate all panel images for this episode.",
            f"Title: {storyboard.get('title', '')}",
            f"Synopsis: {storyboard.get('synopsis', '')}",
            "",
            "Panels:",
        ]
        for p in panels:
            chars = ", ".join(
                c.get("name", "") + (f" ({c.get('outfit', '')})" if c.get("outfit") else "")
                for c in p.get("characters", [])
            )
            dialogue = " / ".join(d.get("text", "") for d in p.get("dialogue", [])[:3])
            lines.append(
                f"- {p.get('panel_id')}: scene={p.get('scene', '')}; characters=[{chars}]; "
                f"camera={p.get('camera', '')}; mood={p.get('mood', '')}; dialogue: {dialogue}"
            )
        return "\n".join(lines)

    # ---- tool execution ----

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
        q = f"%{query.strip()}%"
        stmt = select(Asset).where(Asset.project_id == self.episode.project_id)
        conds = (Asset.name.like(q) | Asset.description.like(q))
        if asset_type:
            stmt = stmt.where(conds, Asset.type == asset_type)
        else:
            stmt = stmt.where(conds)
        rows = (await self.db.execute(stmt.limit(20))).scalars().all()
        return [
            {
                "asset_id": a.id,
                "name": a.name,
                "type": a.type,
                "description": (a.description or "")[:300],
                "visual_tags": (a.tags or {}).get("visual_tags", []),
            }
            for a in rows
        ]
    async def _tool_asset_references(self, asset_id: str) -> dict:
        rows = (
            await self.db.execute(
                select(AssetImage).where(AssetImage.asset_id == asset_id).limit(20)
            )
        ).scalars().all()
        return {
            "asset_id": asset_id,
            "references": [
                {"image_id": r.id, "kind": r.kind, "object_key": r.image_path} for r in rows
            ],
        }

    async def _tool_search_memories(self, query: str) -> list[dict]:
        results = await memory_service.search_rag(self.db, self.episode.project_id, query, top_k=5)
        return [
            {
                "episode_number": r["payload"].get("episode_number"),
                "type": r["payload"].get("type"),
                "content": str(r["payload"].get("content", ""))[:500],
            }
            for r in results
        ]

    async def _tool_open_pits(self) -> list[dict]:
        rows = (
            await self.db.execute(
                select(Pit).where(Pit.project_id == self.episode.project_id, Pit.status == "open").limit(30)
            )
        ).scalars().all()
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

    # ---- generation ----

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

        reference_images: list[tuple[bytes, str]] = []
        context: dict = {
            "episode_number": self.episode.number,
            "panel_id": panel_id,
            "characters": [],
            "style_tags": [],
        }
        ref_names = []

        if reference_asset_ids:
            assets = (
                await self.db.execute(
                    select(Asset).where(
                        Asset.project_id == self.episode.project_id,
                        Asset.id.in_(reference_asset_ids),
                    )
                )
            ).scalars().all()
        else:
            assets = []
        for asset in assets:
            ref_names.append(asset.name)
            if asset.type == "character":
                context["characters"].append(
                    {"name": asset.name, "appearance": (asset.description or "")[:200]}
                )
            elif asset.type == "style":
                context["style_tags"].extend((asset.tags or {}).get("visual_tags", []))

            images = (
                await self.db.execute(
                    select(AssetImage).where(AssetImage.asset_id == asset.id).limit(3)
                )
            ).scalars().all()
            for img in images:
                data = storage_service.get_object_bytes(settings.MINIO_BUCKET, img.image_path)
                if data:
                    mime = "image/png" if img.image_path.lower().endswith(".png") else "image/jpeg"
                    reference_images.append((data, mime))
                if len(reference_images) >= MAX_REFERENCES_PER_PANEL:
                    break

        result = await self.backend.generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            size=self.size,
            reference_images=reference_images or None,
            context=context,
            model=self.image_model or None,
        )

        object_key = storage_service.generate_object_key(f"generated/{self.episode.id}", f"{panel_id}.png")
        storage_service.upload_file(settings.MINIO_BUCKET, object_key, result.image_data, content_type="image/png")

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

    # ---- mechanical fallback helpers ----

    def _mechanical_prompt(self, panel: dict) -> str:
        parts = [panel.get("prompt", "") or panel.get("scene", "")]
        for c in panel.get("characters", []):
            desc = c.get("outfit") or c.get("appearance") or ""
            parts.append(f"{c.get('name', '')}: {desc}" if desc else c.get("name", ""))
        return ", ".join(p for p in parts if p)

    async def _auto_assets(self, panel: dict) -> list[str]:
        names = [c.get("name", "") for c in panel.get("characters", []) if c.get("name")]
        if not names:
            return []
        assets = (
            await self.db.execute(
                select(Asset).where(Asset.project_id == self.episode.project_id, Asset.type == "character")
            )
        ).scalars().all()
        from app.services.generation_service import _names_match

        return [a.id for a in assets if any(_names_match(a.name, n) for n in names)]


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
