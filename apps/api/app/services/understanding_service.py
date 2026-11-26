from __future__ import annotations

import base64
import logging
import uuid
from io import BytesIO
from typing import TYPE_CHECKING

from jinja2 import Template
from PIL import Image
from sqlalchemy import delete, func, select

from app.config import settings
from app.core.llm import get_active_llm_config, get_llm_client
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
_MAX_IMAGE_EDGE = 1344
_MAX_PAGES_PER_CHUNK = 12
_CHUNK_SIZE = 10

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


async def _character_reference_blocks(
    db,
    known_assets: list[Asset],
    recent_ep_ids: set[str] | None = None,
) -> list[tuple[str, str]]:
    """(label, data_url) pairs for the best reference sheet of each character,
    blending series regulars and recently active arc characters."""
    recent_ids = recent_ep_ids or set()
    candidates: list[tuple[Asset, AssetImage]] = []
    for asset in known_assets:
        if asset.type != "character":
            continue
        images = (await db.execute(select(AssetImage).where(AssetImage.asset_id == asset.id))).scalars().all()
        if not images:
            continue
        best = min(
            images,
            key=lambda i: _REF_KIND_PRIORITY.index(i.kind) if i.kind in _REF_KIND_PRIORITY else 99,
        )
        candidates.append((asset, best))

    def _ref_rank(pair: tuple[Asset, AssetImage]) -> tuple[int, int]:
        ep_keys = set((pair[0].episode_ids or {}).keys())
        in_recent = 1 if (ep_keys & recent_ids) else 0
        return (-in_recent, -len(ep_keys))

    # Reserve half for series regulars and half for characters active in the current arc
    by_freq = sorted(candidates, key=lambda pair: -len(pair[0].episode_ids or {}))
    by_recent = sorted(candidates, key=_ref_rank)
    picked: list[tuple[Asset, AssetImage]] = []
    seen_aids: set[str] = set()
    for pair in [*by_freq[:6], *by_recent]:
        if pair[0].id in seen_aids:
            continue
        seen_aids.add(pair[0].id)
        picked.append(pair)
        if len(picked) >= _MAX_CHARACTER_REFS:
            break

    blocks: list[tuple[str, str]] = []
    for asset, image in picked:
        data = storage_service.get_object_bytes(settings.MINIO_BUCKET, image.image_path)
        if data is None:
            continue
        blocks.append((f"参考图 [{asset.id}] {asset.name}", image_to_data_url(data, image.image_path)))
    return blocks


def image_to_data_url(data: bytes, object_key: str) -> str:
    ext = object_key.rsplit(".", 1)[-1].lower() if "." in object_key else "png"
    mime = _MIME_BY_EXT.get(ext, "image/png")
    data, out_mime = _downscale_with_mime(data, mime)
    return f"data:{out_mime};base64," + base64.b64encode(data).decode()


def _downscale_with_mime(data: bytes, mime: str) -> tuple[bytes, str]:
    """Downscale any oversized image (including PNG/WebP/BMP/JPEG) so LLM vision payloads stay bounded."""
    try:
        img = Image.open(BytesIO(data))
        if max(img.size) <= _MAX_IMAGE_EDGE and len(data) <= 1_800_000:
            return data, mime
        ratio = min(1.0, _MAX_IMAGE_EDGE / max(img.size))
        target_size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
        rgb = img.convert("RGB")
        if ratio < 1.0:
            rgb = rgb.resize(target_size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=88)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        logger.warning("Image downscale failed, sending original bytes", exc_info=True)
        return data, mime


def _prepare_page_blocks(page_number: int, data: bytes, object_key: str) -> list[tuple[str, str]]:
    """Convert one manga page into 1+ vision blocks; slices ultra-tall webtoon strips so text stays readable."""
    try:
        img = Image.open(BytesIO(data))
        w, h = img.size
        if w > 0 and h / w > 3.2 and h > 2200:
            slice_h = int(w * 2.2)
            overlap = int(slice_h * 0.08)
            step = max(400, slice_h - overlap)
            blocks: list[tuple[str, str]] = []
            top = 0
            part = 1
            rgb = img.convert("RGB")
            while top < h:
                bottom = min(h, top + slice_h)
                cropped = rgb.crop((0, top, w, bottom))
                buf = BytesIO()
                cropped.save(buf, format="JPEG", quality=88)
                blocks.append((f"第 {page_number} 页 (分段{part})", image_to_data_url(buf.getvalue(), "slice.jpg")))
                if bottom >= h:
                    break
                top += step
                part += 1
            return blocks
    except Exception:
        logger.debug("Tall-strip inspection skipped for page %s", page_number, exc_info=True)

    return [(f"第 {page_number} 页", image_to_data_url(data, object_key))]


def _merge_chunk_understandings(chunks: list[dict]) -> dict:
    """Merge multi-window understandings of a long manga chapter into a single coherent dict."""
    if not chunks:
        return {}
    if len(chunks) == 1:
        return chunks[0]

    summaries = [c.get("summary", "").strip() for c in chunks if c.get("summary")]
    merged_summary = " ".join(summaries)

    events, state_changes, page_dialogues = [], [], []
    characters_by_key: dict[str, dict] = {}
    asset_sightings_by_id: dict[str, dict] = {}
    new_assets_by_key: dict[str, dict] = {}
    pit_discoveries, pit_progressions = [], []
    resolved_pits: list[str] = []
    world_rules: list[str] = []
    art_style = ""

    for chunk in chunks:
        events.extend(chunk.get("events") or [])
        state_changes.extend(chunk.get("state_changes") or [])
        page_dialogues.extend(chunk.get("page_dialogues") or [])
        pit_discoveries.extend(chunk.get("pit_discoveries") or [])
        pit_progressions.extend(chunk.get("pit_progressions") or [])
        for pid in chunk.get("resolved_pits") or []:
            if pid not in resolved_pits:
                resolved_pits.append(pid)
        for rule in chunk.get("world_rules_discovered") or []:
            if rule and rule not in world_rules:
                world_rules.append(rule)
        if chunk.get("art_style_notes") and len(chunk["art_style_notes"]) > len(art_style):
            art_style = chunk["art_style_notes"]

        for char in chunk.get("characters") or []:
            key = char.get("asset_id") or generation_service._normalize_name(char.get("name", ""))
            if not key:
                continue
            prev = characters_by_key.get(key)
            if prev is None:
                characters_by_key[key] = dict(char)
            else:
                if not prev.get("asset_id") and char.get("asset_id"):
                    prev["asset_id"] = char["asset_id"]
                if char.get("appearance") and len(char["appearance"]) > len(prev.get("appearance") or ""):
                    prev["appearance"] = char["appearance"]
                if char.get("speech_style") and not prev.get("speech_style"):
                    prev["speech_style"] = char["speech_style"]
                if char.get("bbox") and not prev.get("bbox"):
                    prev["bbox"] = char["bbox"]
                    prev["source_page"] = char.get("source_page")
                if char.get("vital_status"):
                    prev["vital_status"] = char["vital_status"]
                prev["aliases"] = list(dict.fromkeys([*(prev.get("aliases") or []), *(char.get("aliases") or [])]))

        for sight in chunk.get("asset_sightings") or []:
            aid = sight.get("asset_id") or sight.get("name", "")
            if aid:
                asset_sightings_by_id[aid] = sight

        for na in chunk.get("new_assets") or []:
            nkey = f"{na.get('asset_type', 'item')}:{generation_service._normalize_name(na.get('name', ''))}"
            if nkey not in new_assets_by_key:
                new_assets_by_key[nkey] = dict(na)
            else:
                existing = new_assets_by_key[nkey]
                if len(na.get("description") or "") > len(existing.get("description") or ""):
                    existing["description"] = na["description"]
                existing["visual_tags"] = list(
                    dict.fromkeys([*(existing.get("visual_tags") or []), *(na.get("visual_tags") or [])])
                )
                if na.get("bbox") and not existing.get("bbox"):
                    existing["bbox"] = na["bbox"]
                    existing["source_page"] = na.get("source_page")

    # Last chunk holds the latest main_plot progression and exact ending_state
    last_mp = dict(chunks[-1].get("main_plot") or {})
    first_mp = dict(chunks[0].get("main_plot") or {})
    for field in ("core_conflict", "current_arc", "protagonist_goal"):
        if not last_mp.get(field) and first_mp.get(field):
            last_mp[field] = first_mp[field]

    return {
        "summary": merged_summary,
        "main_plot": last_mp,
        "ending_state": chunks[-1].get("ending_state") or {},
        "art_style_notes": art_style,
        "world_rules_discovered": world_rules,
        "events": events,
        "state_changes": state_changes,
        "characters": list(characters_by_key.values()),
        "asset_sightings": list(asset_sightings_by_id.values()),
        "new_assets": list(new_assets_by_key.values()),
        "pit_discoveries": pit_discoveries,
        "pit_progressions": pit_progressions,
        "resolved_pits": resolved_pits,
        "page_dialogues": page_dialogues,
    }


def _crop_bbox_bytes(page_bytes: bytes, bbox: list | None) -> bytes | None:
    """Crop [ymin, xmin, ymax, xmax] (0..1000 or 0..1 normalized) from page_bytes with slight margin."""
    if not bbox or len(bbox) != 4:
        return None
    try:
        vals = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return None

    scale = 1.0 if max(vals) <= 1.05 else 1000.0
    ymin, xmin, ymax, xmax = [v / scale for v in vals]
    if xmax <= xmin or ymax <= ymin:
        return None
    # Reject implausibly tiny or full-page boxes
    bw, bh = xmax - xmin, ymax - ymin
    if bw < 0.04 or bh < 0.04:
        return None

    try:
        img = Image.open(BytesIO(page_bytes)).convert("RGB")
        w, h = img.size
        pad_x = bw * 0.08
        pad_y = bh * 0.08
        x0 = max(0, int((xmin - pad_x) * w))
        y0 = max(0, int((ymin - pad_y) * h))
        x1 = min(w, int((xmax + pad_x) * w))
        y1 = min(h, int((ymax + pad_y) * h))
        if (x1 - x0) < 48 or (y1 - y0) < 48:
            return None
        cropped = img.crop((x0, y0, x1, y1))
        if max(cropped.size) > 768:
            r = 768 / max(cropped.size)
            cropped = cropped.resize((round(cropped.width * r), round(cropped.height * r)), Image.Resampling.LANCZOS)
        buf = BytesIO()
        cropped.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        logger.debug("Auto-crop failed for bbox %s", bbox, exc_info=True)
        return None


async def _auto_crop_asset_thumbnails(
    db: AsyncSession,
    episode_id: str,
    discovered_pairs: list[tuple[Asset, dict]],
    character_sightings: list[dict],
    matched_chars_by_name: dict[str, Asset],
    raw_pages: dict[int, bytes],
) -> int:
    """Automatically crop and attach visual reference thumbnails for assets that have no images yet."""
    if not raw_pages:
        return 0

    candidates: list[tuple[Asset, int | None, list | None]] = []
    seen_ids: set[str] = set()

    for asset, meta in discovered_pairs:
        if asset.id not in seen_ids:
            seen_ids.add(asset.id)
            candidates.append((asset, meta.get("source_page"), meta.get("bbox")))

    for cs in character_sightings:
        norm = generation_service._normalize_name(cs.get("name", ""))
        asset = matched_chars_by_name.get(norm)
        if asset and asset.id not in seen_ids and cs.get("bbox"):
            seen_ids.add(asset.id)
            candidates.append((asset, cs.get("source_page"), cs.get("bbox")))

    created = 0
    for asset, source_page, bbox in candidates:
        if not source_page or not bbox:
            continue
        page_bytes = raw_pages.get(int(source_page))
        if not page_bytes:
            continue
        existing_count = (
            await db.execute(select(func.count()).select_from(AssetImage).where(AssetImage.asset_id == asset.id))
        ).scalar() or 0
        if existing_count > 0:
            continue

        cropped = _crop_bbox_bytes(page_bytes, bbox)
        if not cropped:
            continue

        object_key = storage_service.generate_object_key(f"assets/{asset.id}", "auto_ref.png")
        storage_service.upload_file(settings.MINIO_BUCKET, object_key, cropped, content_type="image/png")
        db.add(
            AssetImage(
                id=str(uuid.uuid4()),
                asset_id=asset.id,
                kind="thumbnail",
                image_path=object_key,
                meta={"auto_cropped": True, "episode_id": episode_id, "page_number": int(source_page)},
            )
        )
        created += 1

    if created:
        await db.commit()
    return created


async def _ensure_project_style_asset(
    db: AsyncSession,
    project_id: str,
    episode_id: str,
    art_style_notes: str,
    raw_pages: dict[int, bytes],
) -> None:
    """Maintain a project-level style asset with art style notes and 1 representative manga page."""
    if not art_style_notes.strip() and not raw_pages:
        return
    existing = (
        await db.execute(select(Asset).where(Asset.project_id == project_id, Asset.type == "style").limit(1))
    ).scalar_one_or_none()

    if existing is None:
        existing = Asset(
            id=str(uuid.uuid4()),
            project_id=project_id,
            type="style",
            name="原作画风基准",
            description=art_style_notes.strip() or "Original manga visual style reference",
            tags={"visual_tags": [t.strip() for t in art_style_notes.split(",") if t.strip()][:8]},
            episode_ids={episode_id: True},
        )
        db.add(existing)
        await db.flush()
    else:
        if art_style_notes.strip() and len(art_style_notes.strip()) > len(existing.description or ""):
            existing.description = art_style_notes.strip()
        existing.episode_ids = {**(existing.episode_ids or {}), episode_id: True}

    img_count = (
        await db.execute(select(func.count()).select_from(AssetImage).where(AssetImage.asset_id == existing.id))
    ).scalar() or 0
    if img_count == 0 and raw_pages:
        sorted_keys = sorted(raw_pages.keys())
        sample_page = raw_pages[sorted_keys[len(sorted_keys) // 2]]
        scaled, mime = _downscale_with_mime(sample_page, "image/jpeg")
        ext = "png" if "png" in mime else "jpg"
        object_key = storage_service.generate_object_key(f"assets/{existing.id}", f"style_sample.{ext}")
        storage_service.upload_file(settings.MINIO_BUCKET, object_key, scaled, content_type=mime)
        db.add(
            AssetImage(
                id=str(uuid.uuid4()),
                asset_id=existing.id,
                kind="reference",
                image_path=object_key,
                meta={"auto_style_sample": True, "episode_id": episode_id},
            )
        )
    await db.commit()


def _rule_is_duplicate(candidate: str, existing_pool: list[str]) -> bool:
    from difflib import SequenceMatcher

    for ex in existing_pool:
        if candidate == ex:
            return True
        if SequenceMatcher(None, candidate[:140], ex[:140]).ratio() >= 0.88:
            return True
    return False


async def _update_project_story_bible(
    db: AsyncSession,
    project: Project | None,
    episode_label: str,
    understanding_dict: dict,
) -> None:
    """Persist main plotline, current arc, art style, and tiered worldbuilding rules
    (permanent foundational core_rules + rolling recent discovered_rules)."""
    if not project:
        return
    canon = dict(project.canon_rules or {})
    bible = dict(canon.get("story_bible") or {})
    prev_mp = dict(bible.get("main_plot") or {})
    new_mp = dict(understanding_dict.get("main_plot") or {})

    merged_mp = {
        "core_conflict": new_mp.get("core_conflict") or prev_mp.get("core_conflict") or "",
        "current_arc": new_mp.get("current_arc") or prev_mp.get("current_arc") or "",
        "protagonist_goal": new_mp.get("protagonist_goal") or prev_mp.get("protagonist_goal") or "",
        "arc_progress": new_mp.get("arc_progress") or prev_mp.get("arc_progress") or "",
        "next_hook": new_mp.get("next_hook") or prev_mp.get("next_hook") or "",
    }
    bible["main_plot"] = merged_mp

    art_notes = (understanding_dict.get("art_style_notes") or "").strip()
    if art_notes:
        bible["art_style"] = art_notes

    core_rules = [str(r).strip() for r in (bible.get("core_rules") or []) if str(r).strip()]
    recent_rules = [str(r).strip() for r in (bible.get("discovered_rules") or []) if str(r).strip()]

    # Backfill core_rules from earliest discovered_rules on upgraded projects
    if not core_rules and recent_rules:
        core_rules = recent_rules[:15]

    for rule in understanding_dict.get("world_rules_discovered") or []:
        rule_str = str(rule).strip()
        if not rule_str or _rule_is_duplicate(rule_str, [*core_rules, *recent_rules]):
            continue
        if len(core_rules) < 15:
            core_rules.append(rule_str)
        recent_rules.append(rule_str)

    # Keep foundational 15 core rules forever + latest 35 evolving rules (up to 50 distinct rules)
    rolling_tail = [r for r in recent_rules if r not in core_rules][-35:]
    bible["core_rules"] = core_rules[:15]
    bible["discovered_rules"] = [*bible["core_rules"], *rolling_tail]
    bible["last_updated_episode"] = str(episode_label)

    canon["story_bible"] = bible
    project.canon_rules = canon
    await db.commit()


async def run_multimodal_understanding(
    db: AsyncSession,
    episode: Episode,
    page_refs: list[tuple[int, str]],
    fallback_text: str = "",
    target_status: str | None = "understood",
    authoritative_storyboard: dict | None = None,
) -> dict:
    """Understand one episode from its page images (multimodal) and write back
    memories, story bible (main plot), character/item/location assets, auto-cropped
    visual thumbnails, and pit lifecycle changes.
    """
    from app.models.episode import Episode as EpisodeModel

    project = (await db.execute(select(Project).where(Project.id == episode.project_id).limit(1))).scalar_one_or_none()

    recent_branch_eps = list(
        (
            await db.execute(
                select(EpisodeModel)
                .where(
                    EpisodeModel.project_id == episode.project_id,
                    EpisodeModel.branch_id == episode.branch_id,
                    EpisodeModel.number < episode.number,
                )
                .order_by(EpisodeModel.number.desc())
                .limit(8)
            )
        )
        .scalars()
        .all()
    )
    recent_ep_ids: set[str] = set()
    for rep in recent_branch_eps:
        recent_ep_ids.add(rep.id)
        if rep.parent_episode_id:
            recent_ep_ids.add(rep.parent_episode_id)

    known_assets = list((await db.execute(select(Asset).where(Asset.project_id == episode.project_id))).scalars().all())

    def _understanding_asset_rank(a: Asset) -> tuple[int, int]:
        ep_keys = set((a.episode_ids or {}).keys())
        in_recent = 1 if (ep_keys & recent_ep_ids) else 0
        return (-in_recent, -len(ep_keys))

    ranked_chars = sorted([a for a in known_assets if a.type == "character"], key=_understanding_asset_rank)
    ranked_others = sorted(
        [a for a in known_assets if a.type in ("item", "location", "outfit")],
        key=_understanding_asset_rank,
    )

    # Cap prompt rosters at 45 each (blending core cast + active arc assets) so 60+ chapter runs stay crisp
    core_chars = sorted(
        [a for a in known_assets if a.type == "character"],
        key=lambda a: -len(a.episode_ids or {}),
    )[:15]
    selected_chars: list[Asset] = []
    seen_cids: set[str] = set()
    for a in [*core_chars, *ranked_chars]:
        if a.id not in seen_cids:
            seen_cids.add(a.id)
            selected_chars.append(a)
        if len(selected_chars) >= 45:
            break

    known_characters = [
        {
            "asset_id": a.id,
            "name": a.name,
            "type": a.type,
            "aliases": (a.tags or {}).get("aliases", []),
            "description": (a.description or "")[:300],
        }
        for a in selected_chars
    ]
    known_other_assets = [
        {
            "asset_id": a.id,
            "name": a.name,
            "type": a.type,
            "description": (a.description or "")[:240],
        }
        for a in ranked_others[:45]
    ]

    open_pits = list(
        (
            await db.execute(
                select(Pit)
                .where(Pit.project_id == episode.project_id, Pit.status == "open")
                .order_by(Pit.priority.desc())
            )
        )
        .scalars()
        .all()
    )
    open_pits.sort(
        key=lambda p: (
            -(1 if p.introduced_episode_id in recent_ep_ids else 0) * 4 - p.priority,
        )
    )
    open_pit_refs = [
        {
            "id": pit.id,
            "description": pit.description or pit.title,
            "priority": "high" if pit.priority >= 8 else ("medium" if pit.priority >= 4 else "low"),
            "trigger_hint": pit.trigger_hint,
        }
        for pit in open_pits[:30]
    ]

    # Build multi-scale previous context strictly from earlier episodes on this branch
    previous_summary = await memory_service.get_branch_history_before(
        db,
        episode.project_id,
        episode.branch_id,
        episode.number,
        fallback_long_summary=project.long_summary if project else "",
    )
    story_bible = ((project.canon_rules or {}).get("story_bible") or {}) if project else {}
    current_main_plot = story_bible.get("main_plot") or {}

    reference_blocks = await _character_reference_blocks(db, known_assets, recent_ep_ids=recent_ep_ids)

    raw_pages: dict[int, bytes] = {}
    page_blocks: list[tuple[str, str]] = []
    # When authoritative_storyboard is supplied (writeback of generated episode), cap vision pages to 3
    # to keep writeback fast while still allowing visual inspection & thumbnail cropping.
    refs_to_load = page_refs[:3] if authoritative_storyboard else page_refs
    for page_number, object_key in refs_to_load:
        data = storage_service.get_object_bytes(settings.MINIO_BUCKET, object_key)
        if data is None:
            logger.warning("Page image missing in object storage: %s (page %s)", object_key, page_number)
            continue
        raw_pages[int(page_number)] = data
        page_blocks.extend(_prepare_page_blocks(page_number, data, object_key))

    if not page_blocks and not fallback_text:
        raise ValueError("Episode has no page images and no text content to understand")

    vision_cfg = get_active_llm_config("vision_llm")
    client = get_llm_client(role="vision_llm")

    # Windowed multimodal analysis when a chapter has many pages (> _MAX_PAGES_PER_CHUNK)
    if len(page_blocks) <= _MAX_PAGES_PER_CHUNK:
        windows = [page_blocks]
    else:
        windows = [page_blocks[i : i + _CHUNK_SIZE] for i in range(0, len(page_blocks), _CHUNK_SIZE)]

    chunk_results: list[dict] = []
    intra_context_lines: list[str] = []

    for idx, window_blocks in enumerate(windows):
        chunk_info = f"Part {idx + 1}/{len(windows)}" if len(windows) > 1 else ""
        user_prompt = Template(SUMMARIZE_USER_PROMPT).render(
            episode_number=episode.label or episode.number,
            episode_title=episode.title or "",
            chunk_info=chunk_info,
            main_plot=current_main_plot,
            previous_summary=previous_summary,
            intra_episode_context="\n".join(intra_context_lines) if intra_context_lines else "",
            known_characters=known_characters,
            known_other_assets=known_other_assets,
            has_reference_sheets=bool(reference_blocks),
            open_pits=open_pit_refs,
            pages=window_blocks,
            ocr_text="",
            raw_text=fallback_text if (authoritative_storyboard or not window_blocks) else "",
        )

        content: list[dict] = [{"type": "text", "text": user_prompt}]
        for label, url in reference_blocks:
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {"url": url}})
        for label, url in window_blocks:
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {"url": url}})

        logger.info(
            "Understanding episode %s (%s) with %d image blocks and %d character refs",
            episode.id,
            chunk_info or "full",
            len(window_blocks),
            len(reference_blocks),
        )

        from app.core.telemetry import usage_context

        with usage_context(project_id=episode.project_id, episode_id=episode.id, operation="understand"):
            chunk_model = await client.chat.completions.create(
                model=vision_cfg.model,
                messages=[
                    {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                response_model=EpisodeUnderstanding,
                max_tokens=vision_cfg.max_tokens,
                max_retries=2,
            )
        chunk_dict = chunk_model.model_dump()
        chunk_results.append(chunk_dict)
        if len(windows) > 1 and chunk_dict.get("summary"):
            intra_context_lines.append(f"- Segment {idx + 1}: {chunk_dict['summary']}")

    understanding_dict = _merge_chunk_understandings(chunk_results)
    return await persist_episode_understanding(
        db=db,
        episode=episode,
        understanding_dict=understanding_dict,
        raw_pages=raw_pages,
        target_status=target_status,
        authoritative_storyboard=authoritative_storyboard,
    )


async def persist_episode_understanding(
    db: AsyncSession,
    episode: Episode,
    understanding_dict: dict,
    raw_pages: dict[int, bytes] | None = None,
    target_status: str | None = "understood",
    authoritative_storyboard: dict | None = None,
) -> dict:
    """Persist an EpisodeUnderstanding dict into Assets, AssetImages, Pits, Story Bible, and EpisodeMemory."""
    raw_pages = raw_pages or {}
    project = (await db.execute(select(Project).where(Project.id == episode.project_id).limit(1))).scalar_one_or_none()
    known_assets = (await db.execute(select(Asset).where(Asset.project_id == episode.project_id))).scalars().all()
    known_char_ids = {a.id for a in known_assets if a.type == "character"}

    # Backfill exact dialogue from authoritative_storyboard when writeback didn't need to re-OCR every page
    if authoritative_storyboard and not understanding_dict.get("page_dialogues"):
        sb_pages = []
        for pg in authoritative_storyboard.get("pages") or []:
            lines = []
            for pan in pg.get("panels") or []:
                for dlg in pan.get("dialogue") or []:
                    if dlg.get("text"):
                        lines.append(
                            {
                                "speaker": dlg.get("speaker", ""),
                                "text": dlg.get("text", ""),
                                "line_type": dlg.get("type", "speech"),
                            }
                        )
            if lines:
                sb_pages.append({"page_number": pg.get("page_number", 1), "lines": lines})
        understanding_dict["page_dialogues"] = sb_pages

    # Ensure any unrecognized character in characters[] is also registered in new_assets[]
    synthesized_new_assets = list(understanding_dict.get("new_assets") or [])
    existing_new_names = {
        generation_service._normalize_name(na.get("name", ""))
        for na in synthesized_new_assets
        if na.get("asset_type") == "character"
    }
    for c in understanding_dict.get("characters") or []:
        cname = (c.get("name") or "").strip()
        cid = c.get("asset_id")
        if not cname or (cid and cid in known_char_ids):
            continue
        norm_c = generation_service._normalize_name(cname)
        if norm_c and norm_c not in existing_new_names:
            synthesized_new_assets.append(
                {
                    "name": cname,
                    "asset_type": "character",
                    "description": c.get("appearance") or f"{cname} ({c.get('role') or 'character'})",
                    "visual_tags": [],
                    "aliases": c.get("aliases") or [],
                    "speech_style": c.get("speech_style"),
                    "role": c.get("role"),
                    "source_page": c.get("source_page"),
                    "bbox": c.get("bbox"),
                }
            )
            existing_new_names.add(norm_c)
    understanding_dict["new_assets"] = synthesized_new_assets

    # 1. Discover/merge new assets first so character sightings can link to newly created assets too
    discovered_pairs: list[tuple[Asset, dict]] = []
    if understanding_dict.get("new_assets"):
        discovered_pairs = await generation_service.auto_discover_assets(
            db, episode.project_id, episode.id, understanding_dict["new_assets"]
        )

    # 2. Record character & item/location sightings + backfill asset_id + sync vital_status transitions
    ep_label_early = episode.label or str(episode.number)
    matched_chars = await generation_service.record_character_sightings(
        db,
        episode.project_id,
        episode.id,
        understanding_dict.get("characters", []),
        episode_label=ep_label_early,
    )
    if understanding_dict.get("state_changes"):
        await generation_service.sync_character_vital_statuses(
            db, episode.project_id, ep_label_early, understanding_dict.get("state_changes", [])
        )
    for c in understanding_dict.get("characters") or []:
        if not c.get("asset_id"):
            norm = generation_service._normalize_name(c.get("name", ""))
            if norm in matched_chars:
                c["asset_id"] = matched_chars[norm].id

    if understanding_dict.get("asset_sightings"):
        await generation_service.record_asset_sightings(
            db, episode.project_id, episode.id, understanding_dict["asset_sightings"]
        )

    # 3. Auto-crop visual reference thumbnails for newly seen characters/items/locations + style guide
    await _auto_crop_asset_thumbnails(
        db,
        episode.id,
        discovered_pairs,
        understanding_dict.get("characters", []),
        matched_chars,
        raw_pages,
    )
    await _ensure_project_style_asset(
        db,
        episode.project_id,
        episode.id,
        understanding_dict.get("art_style_notes", ""),
        raw_pages,
    )

    # 4. Persist episode memories (summary + ocr_dump, replacing prior understanding memories)
    await save_understanding_memories(db, episode.id, understanding_dict)

    # 5. Pit lifecycle: create new pits, record clue progressions, resolve addressed ones
    ep_label = episode.label or str(episode.number)
    if understanding_dict.get("pit_discoveries"):
        await generation_service.auto_discover_pits(
            db, episode.project_id, episode.id, understanding_dict["pit_discoveries"]
        )
    if understanding_dict.get("pit_progressions"):
        await generation_service.advance_pits(db, episode.project_id, ep_label, understanding_dict["pit_progressions"])
    if understanding_dict.get("resolved_pits"):
        await generation_service.resolve_pits(db, episode.project_id, episode.id, understanding_dict["resolved_pits"])

    # 6. Update Story Bible (main plotline, current arc, world rules, art style)
    await _update_project_story_bible(db, project, ep_label, understanding_dict)

    # 7. Vector memory (no-op when no embedding model is configured)
    await memory_service.vectorize_and_store_episode_memory(
        db, episode.project_id, episode.id, episode.number, understanding_dict
    )

    # 8. Rolling long summary (idempotent per episode + LLM compression when exceeding budget)
    summary_text = understanding_dict.get("summary", "")
    if summary_text and project:
        await memory_service.append_episode_summary(db, project.id, ep_label, summary_text)

    if target_status:
        await generation_service.update_episode_status(db, episode.id, target_status)

    return understanding_dict


async def save_understanding_memories(db: AsyncSession, episode_id: str, understanding: dict) -> list[str]:
    """Store the understanding as episode memories (upserting summary and ocr_dump)."""
    await db.execute(
        delete(EpisodeMemory).where(
            EpisodeMemory.episode_id == episode_id,
            EpisodeMemory.type.in_(["summary", "ocr_dump"]),
        )
    )

    memories = ["summary"]
    db.add(EpisodeMemory(id=str(uuid.uuid4()), episode_id=episode_id, type="summary", content=understanding))

    page_dialogues = understanding.get("page_dialogues", [])
    if page_dialogues:
        flat_lines = []
        for page in page_dialogues:
            for line in page.get("lines", []):
                speaker = line.get("speaker", "")
                text = line.get("text", "")
                flat_lines.append(
                    f"p{page.get('page_number')}: {speaker}: {text}"
                    if speaker
                    else f"p{page.get('page_number')}: {text}"
                )
        db.add(
            EpisodeMemory(
                id=str(uuid.uuid4()),
                episode_id=episode_id,
                type="ocr_dump",
                content={"text": "\n".join(flat_lines), "pages": page_dialogues},
            )
        )
        memories.append("ocr_dump")

    await db.commit()
    return memories
