from __future__ import annotations

import base64
import logging
from io import BytesIO
from typing import TYPE_CHECKING

from jinja2 import Template
from sqlalchemy import select

from app.config import settings
from app.core.llm import get_llm_client
from app.models.asset import Asset
from app.models.asset_image import AssetImage
from app.models.episode_memory import EpisodeMemory
from app.models.pit import Pit
from app.models.project import Project
from app.prompts.summarize import SUMMARIZE_SYSTEM_PROMPT, SUMMARIZE_USER_PROMPT
from app.schemas.understanding import EpisodeUnderstanding
from app.services import generation_service, memory_service, storage_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.episode import Episode

logger = logging.getLogger(__name__)

# Long-edge cap for images sent to the LLM: keeps payloads and vision tokens
# reasonable while staying well above readable resolution for manga pages.
_MAX_IMAGE_EDGE = 1568

_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}

# One reference sheet per known character, capped to keep vision-token cost sane.
_MAX_CHARACTER_REFS = 12
_REF_KIND_PRIORITY = ("reference", "turnaround", "thumbnail", "lora_dataset")


async def _character_reference_blocks(db, known_assets: list[Asset]) -> list[tuple[str, str]]:
    """(label, data_url) pairs for the best reference sheet of each character
    that has one, most frequently seen characters first."""
    candidates: list[tuple[Asset, AssetImage]] = []
    for asset in known_assets:
        if asset.type != "character":
            continue
        images = (
            await db.execute(select(AssetImage).where(AssetImage.asset_id == asset.id))
        ).scalars().all()
        if not images:
            continue
        best = min(
            images,
            key=lambda i: _REF_KIND_PRIORITY.index(i.kind) if i.kind in _REF_KIND_PRIORITY else 99,
        )
        candidates.append((asset, best))

    candidates.sort(key=lambda pair: -len(pair[0].episode_ids or {}))
    blocks: list[tuple[str, str]] = []
    for asset, image in candidates[:_MAX_CHARACTER_REFS]:
        data = storage_service.get_object_bytes(settings.MINIO_BUCKET, image.image_path)
        if data is None:
            continue
        blocks.append((f"参考图 [{asset.id}] {asset.name}", image_to_data_url(data, image.image_path)))
    return blocks


def image_to_data_url(data: bytes, object_key: str) -> str:
    ext = object_key.rsplit(".", 1)[-1].lower() if "." in object_key else "png"
    mime = _MIME_BY_EXT.get(ext, "image/png")
    if ext in ("jpg", "jpeg", "webp", "bmp"):
        data = _downscale(data, mime)
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def _downscale(data: bytes, mime: str) -> bytes:
    try:
        from PIL import Image
    except ImportError:  # Pillow unavailable — send original bytes
        return data
    try:
        img = Image.open(BytesIO(data))
        if max(img.size) <= _MAX_IMAGE_EDGE:
            return data
        ratio = _MAX_IMAGE_EDGE / max(img.size)
        img = img.convert("RGB").resize((round(img.width * ratio), round(img.height * ratio)))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
    except Exception:
        logger.warning("Image downscale failed, sending original bytes", exc_info=True)
        return data


async def run_multimodal_understanding(
    db: AsyncSession,
    episode: Episode,
    page_refs: list[tuple[int, str]],
    fallback_text: str = "",
    target_status: str | None = "understood",
) -> dict:
    """Understand one episode from its page images (multimodal) and write back
    memories, assets, and pit lifecycle changes.

    page_refs: (page_number, minio object key) in reading order.
    When no images are available, falls back to text-only understanding.
    """
    project = (await db.execute(select(Project).where(Project.id == episode.project_id))).scalar_one_or_none()

    known_assets = list(
        (await db.execute(select(Asset).where(Asset.project_id == episode.project_id))).scalars().all()
    )
    known_characters = [
        {"asset_id": a.id, "name": a.name, "type": a.type, "description": a.description or ""}
        for a in known_assets
        if a.type == "character"
    ]

    open_pits = list(
        (
            await db.execute(
                select(Pit).where(Pit.project_id == episode.project_id, Pit.status == "open")
            )
        ).scalars().all()
    )
    open_pit_refs = [{"id": pit.id, "description": pit.description or pit.title} for pit in open_pits]

    previous_summary = ""
    if project and project.long_summary:
        previous_summary = project.long_summary[-2000:]

    # Visual identity anchors: one reference sheet per known character (cap),
    # most frequently seen characters first — so recognition works by FACE,
    # not by name guessing (prevents mistaking a passer-by for the protagonist).
    reference_blocks = await _character_reference_blocks(db, known_assets)

    page_blocks: list[tuple[str, str]] = []
    for page_number, object_key in page_refs:
        data = storage_service.get_object_bytes(settings.MINIO_BUCKET, object_key)
        if data is None:
            logger.warning("Page image missing in object storage: %s (page %s)", object_key, page_number)
            continue
        page_blocks.append((f"第 {page_number} 页", image_to_data_url(data, object_key)))

    user_prompt = Template(SUMMARIZE_USER_PROMPT).render(
        episode_number=episode.number,
        episode_title=episode.title or "",
        previous_summary=previous_summary,
        known_characters=known_characters,
        has_reference_sheets=bool(reference_blocks),
        open_pits=open_pit_refs,
        pages=page_blocks,
        ocr_text="",
        raw_text=fallback_text if not page_blocks else "",
    )

    content: list[dict] = [{"type": "text", "text": user_prompt}]
    for label, url in reference_blocks:
        content.append({"type": "text", "text": label})
        content.append({"type": "image_url", "image_url": {"url": url}})
    for label, url in page_blocks:
        content.append({"type": "text", "text": label})
        content.append({"type": "image_url", "image_url": {"url": url}})
    if not page_blocks and not fallback_text:
        raise ValueError("Episode has no page images and no text content to understand")
    logger.info(
        "Understanding episode %s with %d page images and %d character reference sheets",
        episode.id, len(page_blocks), len(reference_blocks),
    )

    client = get_llm_client()
    understanding = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        response_model=EpisodeUnderstanding,
        max_retries=2,
    )
    understanding_dict = understanding.model_dump()

    # 1. Persist memories (understanding + OCR transcription)
    await save_understanding_memories(db, episode.id, understanding_dict)

    # 2. Character recognition: link sightings to assets
    await generation_service.record_character_sightings(
        db, episode.project_id, episode.id, understanding_dict.get("characters", [])
    )

    # 3. New assets (embedding-free name matching)
    if understanding_dict.get("new_assets"):
        await generation_service.auto_discover_assets(
            db, episode.project_id, episode.id, understanding_dict["new_assets"]
        )

    # 4. Pit lifecycle: create new pits, resolve addressed ones
    if understanding_dict.get("pit_discoveries"):
        await generation_service.auto_discover_pits(
            db, episode.project_id, episode.id, understanding_dict["pit_discoveries"]
        )
    if understanding_dict.get("resolved_pits"):
        await generation_service.resolve_pits(
            db, episode.project_id, episode.id, understanding_dict["resolved_pits"]
        )

    # 5. Vector memory (no-op when no embedding model is configured)
    await memory_service.vectorize_and_store_episode_memory(
        db, episode.project_id, episode.id, episode.number, understanding_dict
    )

    # 6. Rolling long summary (append + LLM compression when it outgrows budget)
    summary_text = understanding_dict.get("summary", "")
    if summary_text and project:
        await memory_service.append_episode_summary(db, project.id, episode.number, summary_text)

    if target_status:
        await generation_service.update_episode_status(db, episode.id, target_status)

    return understanding_dict


async def save_understanding_memories(db: AsyncSession, episode_id: str, understanding: dict) -> list[EpisodeMemory]:
    """Store the understanding as episode memories.

    One consolidated memory (type="summary") holds the full dict — the recent-window
    reader expects content.summary / content.state_changes — plus an ocr_dump memory
    with the per-page transcription.
    """
    memories = []
    db.add_all([EpisodeMemory(episode_id=episode_id, type="summary", content=understanding)])
    memories.append("summary")

    page_dialogues = understanding.get("page_dialogues", [])
    if page_dialogues:
        flat_lines = []
        for page in page_dialogues:
            for line in page.get("lines", []):
                speaker = line.get("speaker", "")
                flat_lines.append(f"p{page.get('page_number')}: {speaker}: {line.get('text', '')}" if speaker
                                  else f"p{page.get('page_number')}: {line.get('text', '')}")
        db.add(
            EpisodeMemory(
                episode_id=episode_id,
                type="ocr_dump",
                content={"text": "\n".join(flat_lines), "pages": page_dialogues},
            )
        )
        memories.append("ocr_dump")

    await db.commit()
    return memories
