from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid
from io import BytesIO
from typing import TYPE_CHECKING

from jinja2 import Template
from PIL import Image, ImageDraw, ImageStat
from sqlalchemy import delete, func, select

from app.config import settings
from app.core.llm import get_active_llm_config, get_llm_client, get_raw_openai_client
from app.models.asset import Asset
from app.models.asset_image import AssetImage
from app.models.episode_memory import EpisodeMemory
from app.models.pit import Pit
from app.models.project import Project
from app.prompts.summarize import (
    SUMMARIZE_CHUNK_TAIL_PROMPT,
    SUMMARIZE_SHARED_PREFIX_PROMPT,
    SUMMARIZE_SYSTEM_PROMPT,
    resolve_language_label,
)
from app.schemas.understanding import EpisodeUnderstanding
from app.services import generation_service, memory_service, storage_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.episode import Episode

logger = logging.getLogger(__name__)

# Long-edge cap and byte budget for images sent to multimodal LLMs.
# Keeping each request's total image base64 <= ~210KB prevents gateway/MTU stalls
# while 560px JPEG preserves crisp manga dialogue and packs ~4 pages per chunk.
_MAX_IMAGE_EDGE = 560
_REF_IMAGE_EDGE = 200
_MAX_PAGES_PER_CHUNK = 4
_CHUNK_SIZE = 4
_MAX_CHUNK_B64_CHARS = 215_000
_CHUNK_CONCURRENCY = 3
_MAX_NEW_PITS_PER_EPISODE = 2

_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}

# Up to 6 compact 200px character reference portraits (~40KB total) so core cast always fits.
_MAX_CHARACTER_REFS = 6
_MAX_AUTO_PORTRAITS = 3
_MIN_PORTRAIT_SCORE = 6.0
_MIN_ASSET_SCORE = 5.5
_REF_KIND_PRIORITY = ("reference", "turnaround", "thumbnail", "lora_dataset")


def _image_rank_key(img: AssetImage) -> tuple[int, int, float]:
    meta = img.meta or {}
    is_primary = 0 if meta.get("is_primary") else 1
    kind_rank = _REF_KIND_PRIORITY.index(img.kind) if img.kind in _REF_KIND_PRIORITY else 99
    score = float(meta.get("portrait_score") or 0.0)
    return (is_primary, kind_rank, -score)


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
        best = min(images, key=_image_rank_key)
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
        aliases = [str(x).strip() for x in ((asset.tags or {}).get("aliases") or []) if str(x).strip()][:4]
        alias_suffix = f"（别名: {' / '.join(aliases)}）" if aliases else ""
        blocks.append(
            (
                f"参考图 [{asset.id}] {asset.name}{alias_suffix}",
                image_to_data_url(data, image.image_path, max_edge=_REF_IMAGE_EDGE, quality=66),
            )
        )
    return blocks


def image_to_data_url(
    data: bytes,
    object_key: str,
    *,
    max_edge: int = _MAX_IMAGE_EDGE,
    quality: int = 65,
) -> str:
    ext = object_key.rsplit(".", 1)[-1].lower() if "." in object_key else "png"
    mime = _MIME_BY_EXT.get(ext, "image/png")
    data, out_mime = _downscale_with_mime(data, mime, max_edge=max_edge, quality=quality)
    return f"data:{out_mime};base64," + base64.b64encode(data).decode()


def _downscale_with_mime(
    data: bytes,
    mime: str,
    *,
    max_edge: int = _MAX_IMAGE_EDGE,
    quality: int = 65,
) -> tuple[bytes, str]:
    """Downscale and JPEG-compress manga pages so each image stays crisp yet compact (<~90KB)."""
    try:
        img = Image.open(BytesIO(data))
        if max(img.size) <= max_edge and mime == "image/jpeg" and len(data) <= 85_000:
            return data, mime
        ratio = min(1.0, max_edge / max(img.size))
        target_size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
        rgb = img.convert("RGB")
        if ratio < 1.0:
            rgb = rgb.resize(target_size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        # Extra guard: if a very noisy page still exceeds 120KB, re-encode slightly smaller
        if len(out) > 120_000 and max(rgb.size) > 480:
            rgb.thumbnail((540, 540), Image.Resampling.LANCZOS)
            buf2 = BytesIO()
            rgb.save(buf2, format="JPEG", quality=62, optimize=True)
            out = buf2.getvalue()
        return out, "image/jpeg"
    except Exception:
        logger.warning("Image downscale failed, sending original bytes", exc_info=True)
        return data, mime


def _build_byte_budgeted_windows(
    page_blocks: list[tuple[str, str]],
    ref_blocks: list[tuple[str, str]],
) -> list[list[tuple[str, str]]]:
    """Pack manga pages into chunks respecting both page count and base64 byte budget."""
    if not page_blocks:
        return []
    ref_chars = sum(len(url) for _, url in ref_blocks)
    page_budget = max(80_000, _MAX_CHUNK_B64_CHARS - ref_chars)
    windows: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_chars = 0
    for block in page_blocks:
        b_len = len(block[1])
        if current and (len(current) >= _CHUNK_SIZE or current_chars + b_len > page_budget):
            windows.append(current)
            current = []
            current_chars = 0
        current.append(block)
        current_chars += b_len
    if current:
        windows.append(current)
    return windows


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

    def _char_keys(char_obj: dict) -> set[str]:
        ks: set[str] = set()
        if char_obj.get("asset_id"):
            ks.add(f"id:{char_obj['asset_id']}")
        nm = generation_service._normalize_name(char_obj.get("name", ""))
        if nm:
            ks.add(f"n:{nm}")
        for al in char_obj.get("aliases") or []:
            na = generation_service._normalize_name(str(al))
            if na:
                ks.add(f"n:{na}")
        return ks

    char_entries: list[tuple[set[str], dict]] = []

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
            ckeys = _char_keys(char)
            if not ckeys:
                continue
            matched_entry = None
            for existing_keys, existing_char in char_entries:
                if existing_keys & ckeys:
                    matched_entry = (existing_keys, existing_char)
                    break
            if matched_entry is None:
                char_entries.append((set(ckeys), dict(char)))
            else:
                existing_keys, prev = matched_entry
                existing_keys.update(ckeys)
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
                extra_alias = [char["name"]] if char.get("name") and char["name"] != prev.get("name") else []
                prev["aliases"] = list(
                    dict.fromkeys([*(prev.get("aliases") or []), *(char.get("aliases") or []), *extra_alias])
                )

        for sight in chunk.get("asset_sightings") or []:
            aid = sight.get("asset_id") or sight.get("name", "")
            if aid:
                asset_sightings_by_id[aid] = sight

        for na in chunk.get("new_assets") or []:
            atype = na.get("asset_type", "item")
            na_norm = generation_service._normalize_name(na.get("name", ""))
            na_aliases = {
                generation_service._normalize_name(str(a))
                for a in (na.get("aliases") or [])
                if str(a).strip()
            }
            na_all = {k for k in ({na_norm} | na_aliases) if k}
            if not na_all:
                continue
            matched_nkey = None
            for k, existing in new_assets_by_key.items():
                if not k.startswith(f"{atype}:"):
                    continue
                ex_all = {
                    generation_service._normalize_name(existing.get("name", "")),
                    *(generation_service._normalize_name(str(a)) for a in (existing.get("aliases") or [])),
                }
                if ex_all & na_all:
                    matched_nkey = k
                    break
            if matched_nkey is None:
                nkey = f"{atype}:{na_norm}"
                new_assets_by_key[nkey] = dict(na)
            else:
                existing = new_assets_by_key[matched_nkey]
                if len(na.get("description") or "") > len(existing.get("description") or ""):
                    existing["description"] = na["description"]
                existing["visual_tags"] = list(
                    dict.fromkeys([*(existing.get("visual_tags") or []), *(na.get("visual_tags") or [])])
                )
                extra_a = [na["name"]] if na.get("name") and na["name"] != existing.get("name") else []
                existing["aliases"] = list(
                    dict.fromkeys([*(existing.get("aliases") or []), *(na.get("aliases") or []), *extra_a])
                )
                if na.get("bbox") and not existing.get("bbox"):
                    existing["bbox"] = na["bbox"]
                    existing["source_page"] = na.get("source_page")

    characters_by_key = {str(i): c for i, (_, c) in enumerate(char_entries)}

    # Keep only the highest-priority, non-duplicate foreshadowing threads (strictly capped per episode)
    prio_rank = {"high": 0, "medium": 1, "low": 2}
    dedup_pits: list[dict] = []
    seen_pit_sigs: set[str] = set()
    for p in sorted(pit_discoveries, key=lambda item: prio_rank.get(str(item.get("priority") or "medium").lower(), 1)):
        sig = generation_service._normalize_name(p.get("title") or p.get("description", "")[:32])
        if not sig or sig in seen_pit_sigs:
            continue
        seen_pit_sigs.add(sig)
        dedup_pits.append(p)
        if len(dedup_pits) >= _MAX_NEW_PITS_PER_EPISODE:
            break
    pit_discoveries = dedup_pits

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


def _is_meaningful_crop(cropped: Image.Image) -> bool:
    """Reject nearly blank white speech bubbles or solid dark sky patches."""
    gray = cropped.convert("L")
    stat = ImageStat.Stat(gray)
    stddev = stat.stddev[0] if stat.stddev else 0.0
    return stddev >= 22.0


def _crop_bbox_bytes(
    page_bytes: bytes,
    bbox: list | None,
    *,
    pad_ratio: float = 0.14,
    square_portrait: bool = False,
) -> bytes | None:
    """Crop [ymin, xmin, ymax, xmax] (0..1000 or 0..1 normalized) from page_bytes with margin & variance check."""
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
    bw, bh = xmax - xmin, ymax - ymin
    if bw < 0.04 or bh < 0.04:
        return None

    try:
        img = Image.open(BytesIO(page_bytes)).convert("RGB")
        w, h = img.size
        raw_px_w = bw * w
        raw_px_h = bh * h
        if square_portrait:
            aspect = raw_px_w / max(1.0, raw_px_h)
            if aspect < 0.48 or aspect > 2.3:
                return None

        pad_x = max(bw * pad_ratio, 0.035)
        pad_y = max(bh * pad_ratio, 0.035)
        x0 = max(0, int((xmin - pad_x) * w))
        y0 = max(0, int((ymin - pad_y) * h))
        x1 = min(w, int((xmax + pad_x) * w))
        y1 = min(h, int((ymax + pad_y) * h))

        # Gently widen overly narrow portrait boxes toward ~0.88:1 so face sides/glasses aren't clipped
        if square_portrait:
            cw, ch = x1 - x0, y1 - y0
            target_w = int(ch * 0.88)
            if cw < target_w:
                delta = (target_w - cw) // 2
                x0 = max(0, x0 - delta)
                x1 = min(w, x1 + delta)

        if (x1 - x0) < 64 or (y1 - y0) < 64:
            return None
        cropped = img.crop((x0, y0, x1, y1))
        if not _is_meaningful_crop(cropped):
            return None
        if max(cropped.size) > 768:
            r = 768 / max(cropped.size)
            cropped = cropped.resize((round(cropped.width * r), round(cropped.height * r)), Image.Resampling.LANCZOS)
        buf = BytesIO()
        cropped.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        logger.debug("Auto-crop failed for bbox %s", bbox, exc_info=True)
        return None


def _render_outer_ruler_grid(page_bytes: bytes) -> bytes:
    """Render a compact JPEG copy of a manga page framed by an outer 0..1000 coordinate ruler
    so multimodal LLMs can read exact face coordinates without covering artwork."""
    orig = Image.open(BytesIO(page_bytes)).convert("RGB")
    orig.thumbnail((760, 760), Image.Resampling.LANCZOS)
    w, h = orig.size
    margin = 34
    canvas = Image.new("RGBA", (w + margin * 2, h + margin * 2), (24, 24, 27, 255))
    canvas.paste(orig.convert("RGBA"), (margin, margin))

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # Border around the exact 0..1000 artwork rectangle
    draw.rectangle([margin, margin, margin + w, margin + h], outline=(230, 75, 53, 210), width=2)
    for step in range(0, 1001, 100):
        x = margin + int(w * step / 1000)
        y = margin + int(h * step / 1000)
        if 0 < step < 1000:
            draw.line([(x, margin), (x, margin + h)], fill=(230, 75, 53, 95), width=1)
            draw.line([(margin, y), (margin + w, y)], fill=(230, 75, 53, 95), width=1)
        lbl = str(step)
        draw.text((max(2, x - 10), 10), lbl, fill=(244, 244, 245, 255))
        draw.text((max(2, x - 10), margin + h + 10), lbl, fill=(244, 244, 245, 255))
        draw.text((4, max(2, y - 6)), lbl, fill=(244, 244, 245, 255))
        draw.text((margin + w + 5, max(2, y - 6)), lbl, fill=(244, 244, 245, 255))

    combined = Image.alpha_composite(canvas, overlay).convert("RGB")
    buf = BytesIO()
    combined.save(buf, format="JPEG", quality=74, optimize=True)
    return buf.getvalue()


async def _verify_same_character_as_anchor(
    anchor_bytes: bytes,
    candidate_bytes: bytes,
    character_name: str,
    character_desc: str,
    project_id: str | None = None,
    episode_id: str | None = None,
) -> bool:
    """Side-by-side visual identity guard: reject candidate crops that depict a different character
    (e.g. Mabel vs Elf, Fujimiya vs Elf, Uncle vs Takafumi) BEFORE polluting the character's image pool."""
    try:
        a_im = Image.open(BytesIO(anchor_bytes)).convert("RGB")
        c_im = Image.open(BytesIO(candidate_bytes)).convert("RGB")
        cell = 260
        pad = 14
        a_im.thumbnail((cell, cell), Image.Resampling.LANCZOS)
        c_im.thumbnail((cell, cell), Image.Resampling.LANCZOS)
        pair = Image.new("RGB", (cell * 2 + pad * 3, cell + pad * 2 + 24), (24, 24, 27))
        draw = ImageDraw.Draw(pair)
        pair.paste(a_im, (pad + (cell - a_im.width) // 2, 24 + pad + (cell - a_im.height) // 2))
        pair.paste(c_im, (pad * 2 + cell + (cell - c_im.width) // 2, 24 + pad + (cell - c_im.height) // 2))
        draw.text((pad, 6), "LEFT: ESTABLISHED ANCHOR", fill=(244, 244, 245))
        draw.text((pad * 2 + cell, 6), "RIGHT: NEW CANDIDATE", fill=(230, 75, 53))
        buf = BytesIO()
        pair.save(buf, format="JPEG", quality=76, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()

        llm_cfg = get_active_llm_config("main_llm")
        client = get_raw_openai_client()
        extra_kwargs: dict = {}
        if llm_cfg.provider_key in ("glm_coding", "glm") or "glm-" in (llm_cfg.model or "").lower():
            extra_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        prompt = (
            f"Verify visual identity for manga character '{character_name}' ({character_desc[:100]}).\n"
            "LEFT is the confirmed anchor portrait of this character. RIGHT is a newly cropped candidate.\n"
            "Does RIGHT clearly show the EXACT SAME character's face as LEFT "
            "(matching gender, age, hair style/tone, face shape, ear shape, glasses)?\n"
            "Be STRICT: reject if RIGHT is a different character, a cropped half-face of someone else, or scenery.\n"
            'Return ONLY valid JSON: {"same_character": true, "reason": "short reason"}'
        )

        from app.core.telemetry import usage_context

        with usage_context(project_id=project_id, episode_id=episode_id, operation="portrait_verify"):
            resp = await client.chat.completions.create(
                model=llm_cfg.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=160,
                **extra_kwargs,
            )
        raw_txt = (resp.choices[0].message.content or "").strip()
        if raw_txt.startswith("```"):
            raw_txt = re.sub(r"^```(?:json)?\s*", "", raw_txt)
            raw_txt = re.sub(r"\s*```$", "", raw_txt)
        parsed = json.loads(raw_txt)
        return bool(parsed.get("same_character", False))
    except Exception:
        logger.debug("Anchor visual verification failed for %s", character_name, exc_info=True)
        return False


async def _ground_assets_on_page(
    page_bytes: bytes,
    targets: list[tuple[Asset, str]],
    project_id: str | None = None,
    episode_id: str | None = None,
) -> dict[str, dict]:
    """Use a single-page outer-ruler-grid call to locate faces (characters) or clear visual crops
    (items, locations, outfits) with quality scores."""
    if not targets:
        return {}
    try:
        grid_bytes = _render_outer_ruler_grid(page_bytes)
        b64 = base64.b64encode(grid_bytes).decode()
        lines = "\n".join(f"- id={a.id} | type={a.type} | {a.name} ({desc[:95]})" for a, desc in targets)
        prompt = (
            "The manga page inside the red border is framed by an outer 0..1000 coordinate ruler "
            "(horizontal X from 0 left to 1000 right; vertical Y from 0 top to 1000 bottom).\n"
            "For each listed visual asset, locate its CLEAREST visual appearance on this page:\n"
            "- For type=character: frame the character's FULL HEAD & FACE (both eyes, nose, mouth, hair), "
            "NOT speech bubbles, NOT scenery, NOT a narrow 1-eye strip, NOT a different character.\n"
            "- For type=item|outfit|location: frame the panel or tight region clearly showing that object, "
            "outfit, or setting.\n"
            "- Score visual clarity 0..10 (9-10 = iconic clear view; 6-8 = clear; <6 = occluded/tiny/unclear).\n"
            "- If an asset is NOT clearly drawn on this page, OMIT it completely.\n"
            "- Return ONLY valid JSON:\n"
            '{"crops": [{"id": "<asset_id>", "xmin": 0, "ymin": 0, "xmax": 0, "ymax": 0, '
            '"score": 8.5, "full_view": true, "classic_look": true}]}\n\n'
            f"Assets to locate:\n{lines}"
        )
        llm_cfg = get_active_llm_config("main_llm")
        client = get_raw_openai_client()
        extra_kwargs: dict = {}
        if llm_cfg.provider_key in ("glm_coding", "glm") or "glm-" in (llm_cfg.model or "").lower():
            extra_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        from app.core.telemetry import usage_context

        with usage_context(project_id=project_id, episode_id=episode_id, operation="asset_ground"):
            resp = await client.chat.completions.create(
                model=llm_cfg.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=800,
                **extra_kwargs,
            )
        raw_txt = (resp.choices[0].message.content or "").strip()
        if raw_txt.startswith("```"):
            raw_txt = re.sub(r"^```(?:json)?\s*", "", raw_txt)
            raw_txt = re.sub(r"\s*```$", "", raw_txt)
        parsed = json.loads(raw_txt)
        type_by_id = {a.id: a.type for a, _ in targets}
        out: dict[str, dict] = {}
        for item in parsed.get("crops") or []:
            aid = str(item.get("id") or "")
            if not aid or aid not in type_by_id:
                continue
            xmin = int(item.get("xmin", 0))
            ymin = int(item.get("ymin", 0))
            xmax = int(item.get("xmax", 0))
            ymax = int(item.get("ymax", 0))
            score = float(item.get("score") or 0.0)
            full_view = bool(item.get("full_view", item.get("full_face", True)))
            classic_look = bool(item.get("classic_look", True))
            min_score = _MIN_PORTRAIT_SCORE if type_by_id[aid] == "character" else _MIN_ASSET_SCORE
            if xmax > xmin and ymax > ymin and full_view and score >= min_score:
                out[aid] = {
                    "bbox": [ymin, xmin, ymax, xmax],
                    "score": score,
                    "classic_look": classic_look,
                }
        return out
    except Exception:
        logger.debug("Grid asset grounding skipped/failed", exc_info=True)
        return {}


# Backward-compatible alias
_ground_character_portraits_on_page = _ground_assets_on_page


async def elect_best_character_portrait(db: AsyncSession, asset: Asset) -> AssetImage | None:
    """Run a fast 2x2 contact-sheet tournament over a character's candidate portraits
    to promote the clearest, most iconic front/3/4 face to primary `reference`."""
    images = list(
        (await db.execute(select(AssetImage).where(AssetImage.asset_id == asset.id).order_by(AssetImage.created_at)))
        .scalars()
        .all()
    )
    if len(images) < 2:
        return images[0] if images else None

    # Respect manual user-selected primary or user-uploaded reference sheets
    for im in images:
        meta = im.meta or {}
        if meta.get("manual_primary") or (im.kind in ("reference", "turnaround") and not meta.get("auto_cropped")):
            return im

    candidates = images[:4]
    tiles: list[tuple[int, AssetImage, Image.Image]] = []
    for idx, im in enumerate(candidates, start=1):
        raw = storage_service.get_object_bytes(settings.MINIO_BUCKET, im.image_path)
        if not raw:
            continue
        try:
            pil = Image.open(BytesIO(raw)).convert("RGB")
            tiles.append((idx, im, pil))
        except Exception:
            continue

    if len(tiles) < 2:
        return candidates[0]

    # Build a crisp 2x2 contact sheet (~70-100KB JPEG) with #1..#4 badges
    cell = 280
    pad = 16
    cols = 2
    rows = (len(tiles) + 1) // 2
    sheet = Image.new("RGB", (cols * cell + (cols + 1) * pad, rows * cell + (rows + 1) * pad), (24, 24, 27))
    draw = ImageDraw.Draw(sheet)
    for pos_i, (num, _im, pil) in enumerate(tiles):
        r, c = divmod(pos_i, cols)
        ox = pad + c * (cell + pad)
        oy = pad + r * (cell + pad)
        thumb = pil.copy()
        thumb.thumbnail((cell, cell), Image.Resampling.LANCZOS)
        px = ox + (cell - thumb.width) // 2
        py = oy + (cell - thumb.height) // 2
        sheet.paste(thumb, (px, py))
        draw.rectangle([ox, oy, ox + 42, oy + 24], fill=(230, 75, 53))
        draw.text((ox + 10, oy + 5), f"#{num}", fill=(255, 255, 255))

    buf = BytesIO()
    sheet.save(buf, format="JPEG", quality=76, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()

    try:
        llm_cfg = get_active_llm_config("main_llm")
        client = get_raw_openai_client()
        extra_kwargs: dict = {}
        if llm_cfg.provider_key in ("glm_coding", "glm") or "glm-" in (llm_cfg.model or "").lower():
            extra_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        prompt = (
            f"Audit these candidate portraits (#1 to #{len(tiles)}) for manga character '{asset.name}' "
            f"({(asset.description or '')[:140]}).\n"
            "Step 1: For EACH tile (#1..#N), briefly describe what is ACTUALLY visible in that tile "
            "(scenery/buildings/bubbles, a DIFFERENT character of wrong gender/hair, or THIS character's face?).\n"
            "Step 2: Put any tile with scenery/no-face, the wrong character, or heavy clipping in `invalid_nums`.\n"
            "Step 3: Among the VALID tiles showing THIS character's clear, unclipped front or 3/4 face with classic "
            "normal appearance, pick the SINGLE BEST `winner` (or null if none are valid).\n"
            'Return ONLY valid JSON: {"audit": [{"num": 1, "what": "...", "valid": true}], '
            '"invalid_nums": [3], "winner": 2}'
        )

        from app.core.telemetry import usage_context

        with usage_context(project_id=asset.project_id, operation="portrait_elect"):
            resp = await client.chat.completions.create(
                model=llm_cfg.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=500,
                **extra_kwargs,
            )
        raw_txt = (resp.choices[0].message.content or "").strip()
        if raw_txt.startswith("```"):
            raw_txt = re.sub(r"^```(?:json)?\s*", "", raw_txt)
            raw_txt = re.sub(r"\s*```$", "", raw_txt)
        parsed = json.loads(raw_txt)
        invalid_nums = {int(n) for n in (parsed.get("invalid_nums") or []) if str(n).isdigit()}
        win_num = parsed.get("winner")
        valid_tiles = [(num, im) for num, im, _ in tiles if num not in invalid_nums]
        winner = (
            next((im for num, im in valid_tiles if num == int(win_num)), None)
            if win_num is not None
            else None
        )
        if winner is None and valid_tiles:
            winner = valid_tiles[0][1]

        # Auto-purge clearly invalid auto-cropped tiles (buildings / wrong character / blank)
        deleted_ids: set[str] = set()
        for num, im, _ in tiles:
            if num in invalid_nums and (im.meta or {}).get("auto_cropped"):
                if winner is None or im.id != winner.id:
                    await db.delete(im)
                    deleted_ids.add(im.id)
        if winner is None:
            await db.commit()
            return None
        images = [im for im in images if im.id not in deleted_ids]
    except Exception:
        logger.debug("Portrait election fell back to highest score for asset %s", asset.id, exc_info=True)
        winner = min(candidates, key=_image_rank_key)

    for im in images:
        meta = dict(im.meta or {})
        if im.id == winner.id:
            im.kind = "reference"
            meta["is_primary"] = True
            meta["auto_elected"] = True
        else:
            if meta.get("auto_cropped"):
                im.kind = "thumbnail"
            meta["is_primary"] = False
        im.meta = meta
    await db.commit()
    return winner


async def _auto_crop_asset_thumbnails(
    db: AsyncSession,
    episode_id: str,
    discovered_pairs: list[tuple[Asset, dict]],
    character_sightings: list[dict],
    matched_chars_by_name: dict[str, Asset],
    raw_pages: dict[int, bytes],
) -> int:
    """Collect up to _MAX_AUTO_PORTRAITS high-quality portraits per character across episodes,
    and automatically elect the most iconic front/3/4 face as primary reference."""
    if not raw_pages:
        return 0

    candidates: list[tuple[Asset, int | None, list | None, str]] = []
    seen_ids: set[str] = set()

    for asset, meta in discovered_pairs:
        if asset.id not in seen_ids:
            seen_ids.add(asset.id)
            candidates.append((asset, meta.get("source_page"), meta.get("bbox"), asset.description or ""))

    for cs in character_sightings:
        norm = generation_service._normalize_name(cs.get("name", ""))
        asset = matched_chars_by_name.get(norm)
        if asset and asset.id not in seen_ids and (cs.get("source_page") or cs.get("bbox")):
            seen_ids.add(asset.id)
            desc = cs.get("appearance") or asset.description or ""
            candidates.append((asset, cs.get("source_page"), cs.get("bbox"), desc))

    pending: list[tuple[Asset, int, list | None, str, list[AssetImage]]] = []
    for asset, source_page, bbox, desc in candidates:
        if not source_page or int(source_page) not in raw_pages:
            continue
        existing_imgs = list(
            (await db.execute(select(AssetImage).where(AssetImage.asset_id == asset.id))).scalars().all()
        )
        if asset.type == "character":
            # Stop auto-collecting once user manually uploaded a reference or set manual primary
            has_manual = any(
                (im.meta or {}).get("manual_primary")
                or (im.kind in ("reference", "turnaround") and not (im.meta or {}).get("auto_cropped"))
                for im in existing_imgs
            )
            if has_manual:
                continue
            # Avoid duplicate crops from the same episode
            if any((im.meta or {}).get("episode_id") == episode_id for im in existing_imgs):
                continue
            auto_imgs = [im for im in existing_imgs if (im.meta or {}).get("auto_cropped")]
            top_score = max((float((im.meta or {}).get("portrait_score") or 0.0) for im in auto_imgs), default=0.0)
            if len(auto_imgs) >= _MAX_AUTO_PORTRAITS and top_score >= 8.5:
                continue
            pending.append((asset, int(source_page), bbox, desc, existing_imgs))
        else:
            if not existing_imgs:
                pending.append((asset, int(source_page), bbox, desc, existing_imgs))

    if not pending:
        return 0

    # Group ALL pending visual assets (characters + items + locations + outfits) by page
    assets_by_page: dict[int, list[tuple[Asset, str]]] = {}
    for asset, page_num, _bbox, desc, _existing in pending:
        if asset.type in ("character", "item", "location", "outfit"):
            assets_by_page.setdefault(page_num, []).append((asset, desc))

    grounded_map: dict[str, dict] = {}
    for page_num, targets in list(assets_by_page.items())[:6]:
        page_boxes = await _ground_assets_on_page(
            raw_pages[page_num],
            targets,
            project_id=targets[0][0].project_id if targets else None,
            episode_id=episode_id,
        )
        grounded_map.update(page_boxes)

    created = 0
    assets_to_elect: list[Asset] = []
    for asset, page_num, fallback_bbox, desc, existing_imgs in pending:
        page_bytes = raw_pages.get(page_num)
        if not page_bytes:
            continue
        ginfo = grounded_map.get(asset.id)
        if asset.type == "character":
            if not ginfo:
                continue
            cropped = _crop_bbox_bytes(page_bytes, ginfo["bbox"], pad_ratio=0.25, square_portrait=True)
            if not cropped:
                continue
            # Visual anchor guard: if this character already has a confirmed portrait, verify same identity!
            if existing_imgs:
                anchor = min(existing_imgs, key=_image_rank_key)
                anchor_bytes = storage_service.get_object_bytes(settings.MINIO_BUCKET, anchor.image_path)
                if anchor_bytes:
                    same = await _verify_same_character_as_anchor(
                        anchor_bytes,
                        cropped,
                        asset.name,
                        desc,
                        project_id=asset.project_id,
                        episode_id=episode_id,
                    )
                    if not same:
                        logger.info(
                            "Rejected mismatched candidate portrait for %s on ep=%s p=%s",
                            asset.name,
                            episode_id,
                            page_num,
                        )
                        continue
            auto_imgs = [im for im in existing_imgs if (im.meta or {}).get("auto_cropped")]
            if len(auto_imgs) >= _MAX_AUTO_PORTRAITS:
                worst = min(auto_imgs, key=lambda im: float((im.meta or {}).get("portrait_score") or 0.0))
                if ginfo["score"] <= float((worst.meta or {}).get("portrait_score") or 0.0):
                    continue
                await db.delete(worst)
            meta_payload = {
                "auto_cropped": True,
                "grounded": True,
                "episode_id": episode_id,
                "page_number": page_num,
                "portrait_score": ginfo["score"],
                "classic_look": ginfo["classic_look"],
            }
        else:
            use_box = ginfo["bbox"] if ginfo else fallback_bbox
            if not use_box:
                continue
            cropped = _crop_bbox_bytes(page_bytes, use_box, pad_ratio=0.14)
            if not cropped:
                continue
            meta_payload = {
                "auto_cropped": True,
                "grounded": bool(ginfo),
                "episode_id": episode_id,
                "page_number": page_num,
                "portrait_score": ginfo["score"] if ginfo else 0.0,
            }

        object_key = storage_service.generate_object_key(f"assets/{asset.id}", "auto_ref.png")
        storage_service.upload_file(settings.MINIO_BUCKET, object_key, cropped, content_type="image/png")
        db.add(
            AssetImage(
                id=str(uuid.uuid4()),
                asset_id=asset.id,
                kind="thumbnail",
                image_path=object_key,
                meta=meta_payload,
            )
        )
        created += 1
        if asset.type == "character" and len(existing_imgs) + 1 >= 2:
            assets_to_elect.append(asset)

    if created:
        await db.commit()
    for char_asset in assets_to_elect:
        await elect_best_character_portrait(db, char_asset)
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

    # Windowed multimodal analysis respecting both page count and payload byte budget
    windows = _build_byte_budgeted_windows(page_blocks, reference_blocks)

    from app.core.telemetry import usage_context

    extra_kwargs: dict = {}
    if vision_cfg.provider_key in ("glm_coding", "glm") or "glm-" in (vision_cfg.model or "").lower():
        # Disable long hidden reasoning traces during high-volume manga page vision extraction
        extra_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    sem = asyncio.Semaphore(_CHUNK_CONCURRENCY)

    preferred_language = resolve_language_label(project.language if project else "zh")

    def _is_content_filter_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(k in msg for k in ("contentfilter", "content_filter", "1301", "敏感内容", "inappropriate"))

    # Render the episode-wide shared prefix ONCE so every chunk sends byte-identical
    # prefix blocks (text + character reference portraits) for maximum LLM Prompt Cache hits!
    shared_prefix_text = Template(SUMMARIZE_SHARED_PREFIX_PROMPT).render(
        preferred_language=preferred_language,
        episode_number=episode.label or episode.number,
        episode_title=episode.title or "",
        main_plot=current_main_plot,
        previous_summary=previous_summary,
        known_characters=known_characters,
        known_other_assets=known_other_assets,
        has_reference_sheets=bool(reference_blocks),
        open_pits=open_pit_refs,
    )
    shared_prefix_blocks: list[dict] = [{"type": "text", "text": shared_prefix_text}]
    for label, url in reference_blocks:
        shared_prefix_blocks.append({"type": "text", "text": label})
        shared_prefix_blocks.append({"type": "image_url", "image_url": {"url": url}})

    async def _call_window_once(chunk_info: str, blocks: list[tuple[str, str]]) -> dict:
        tail_prompt = Template(SUMMARIZE_CHUNK_TAIL_PROMPT).render(
            preferred_language=preferred_language,
            chunk_info=chunk_info,
            intra_episode_context="",
            pages=blocks,
            ocr_text="",
            raw_text=fallback_text if (authoritative_storyboard or not blocks) else "",
        )

        content: list[dict] = [*shared_prefix_blocks, {"type": "text", "text": tail_prompt}]
        for label, url in blocks:
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {"url": url}})

        async with sem:
            logger.info(
                "Understanding episode %s (%s) with %d image blocks and %d character refs",
                episode.id,
                chunk_info or "full",
                len(blocks),
                len(reference_blocks),
            )
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
                    **extra_kwargs,
                )
            return chunk_model.model_dump()

    async def _analyze_window(idx: int, window_blocks: list[tuple[str, str]]) -> dict:
        chunk_info = f"Part {idx + 1}/{len(windows)}" if len(windows) > 1 else ""
        try:
            return await _call_window_once(chunk_info, window_blocks)
        except Exception as exc:
            if not _is_content_filter_error(exc):
                raise
            # Content-filter resilience: isolate and skip ONLY the single flagged page(s)
            if len(window_blocks) <= 1:
                logger.warning("Skipping single page %s due to upstream content filter", window_blocks[0][0])
                return {}
            logger.warning(
                "Window %s hit upstream content filter; retrying %d pages individually to isolate flagged page",
                chunk_info or "full",
                len(window_blocks),
            )
            sub_results: list[dict] = []
            for p_idx, single_block in enumerate(window_blocks):
                try:
                    sub_results.append(await _call_window_once(f"{chunk_info}.{p_idx + 1}", [single_block]))
                except Exception as sub_exc:
                    if _is_content_filter_error(sub_exc):
                        logger.warning("Skipped flagged page %s (content filter)", single_block[0])
                    else:
                        raise
            return _merge_chunk_understandings(sub_results) if sub_results else {}

    # Warm the provider's KV prefix cache with Part 1 first, then run Part 2..N in parallel
    # so every subsequent chunk reuses the cached Story Bible + history + character portraits!
    raw_results: list[dict] = []
    if windows:
        first_res = await _analyze_window(0, windows[0])
        if first_res:
            raw_results.append(first_res)
        if len(windows) > 1:
            rest = await asyncio.gather(*(_analyze_window(i, wb) for i, wb in enumerate(windows[1:], start=1)))
            raw_results.extend(r for r in rest if r)
    chunk_results: list[dict] = raw_results

    understanding_dict = _merge_chunk_understandings(chunk_results)
    # Hard guard on single-chunk episodes too: keep at most _MAX_NEW_PITS_PER_EPISODE new pits
    if len(understanding_dict.get("pit_discoveries") or []) > _MAX_NEW_PITS_PER_EPISODE:
        prio_rank = {"high": 0, "medium": 1, "low": 2}
        understanding_dict["pit_discoveries"] = sorted(
            understanding_dict["pit_discoveries"],
            key=lambda item: prio_rank.get(str(item.get("priority") or "medium").lower(), 1),
        )[:_MAX_NEW_PITS_PER_EPISODE]

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
