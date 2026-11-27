from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from io import BytesIO
from typing import TYPE_CHECKING, Any

from jinja2 import Template
from PIL import Image, ImageDraw
from sqlalchemy import delete, func, select

from app.config import settings
from app.core.llm import get_active_llm_config, get_raw_openai_client
from app.models.asset import Asset
from app.models.asset_image import AssetImage
from app.models.episode_memory import EpisodeMemory
from app.models.pit import Pit
from app.models.project import Project
from app.prompts.summarize import (
    READ_PAGES_SYSTEM_PROMPT,
    READ_SHARED_PREFIX_PROMPT,
    READ_WINDOW_TAIL_PROMPT,
    SYNTHESIZE_EPISODE_SYSTEM_PROMPT,
    SYNTHESIZE_EPISODE_USER_PROMPT,
    resolve_language_label,
)
from app.schemas.understanding import EpisodeUnderstanding
from app.services import generation_service, memory_service, storage_service
from app.services.manga_vision_utils import (
    crop_pixel_box,
    encode_highres_page_webp,
    encode_reference_portrait_webp,
    prepare_manga_page_blocks,
    render_crop_contact_sheet,
    render_pixel_grid,
    render_zoom_refinement_grid,
    sanitize_understanding,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.episode import Episode

logger = logging.getLogger(__name__)

# Vision reading parameters (crisp 768x1200 WebP, up to 6 pages/window = 3-4 windows/episode).
_MAX_IMAGE_EDGE = 768
_MAX_PAGES_PER_WINDOW = 6
_MAX_WINDOW_B64_CHARS = 1_100_000
_MAX_ZOOM_REREADS_PER_EPISODE = 2
_MAX_ROLLING_NOTES_CHARS = 3800
_MAX_NEW_PITS_PER_EPISODE = 2

# Per-operation timeouts: generous enough for slow vision gateways, faster than 240s dead-socket hangs
_TIMEOUT_READ_SEC = 150.0
_TIMEOUT_SYNTH_SEC = 100.0
_TIMEOUT_CROP_SEC = 75.0

_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}

# Character reference portraits & multi-stage cropping thresholds
_MAX_CHARACTER_REFS = 6
_MAX_AUTO_PORTRAITS = 3
_MIN_PORTRAIT_SCORE = 6.5
_MIN_ASSET_SCORE = 6.0
_MAX_CROP_PAGES_PER_EPISODE = 6
_REF_KIND_PRIORITY = ("reference", "turnaround", "thumbnail", "lora_dataset")

_CROP_HINT_RE = re.compile(
    r"★\s*裁剪候选\s*\[?(character|item|location|outfit)\]?\s*([^@\n：:]+?)\s*@\s*p0*(\d+)(?:\s*([RL]))?(?:\s*[:：\-]\s*(.+))?$",
    re.IGNORECASE | re.MULTILINE,
)
_ZOOM_HINT_RE = re.compile(
    r"\?\s*需放大复核\s*@\s*p0*(\d+)(?:\s*([RL]))?(?:\s*[:：\-]\s*(.+))?$",
    re.IGNORECASE | re.MULTILINE,
)


def _glm_no_thinking_kwargs(provider_key: str | None, model: str | None) -> dict[str, Any]:
    if provider_key in ("glm_coding", "glm") or "glm-" in (model or "").lower():
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def _is_content_filter_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("contentfilter", "content_filter", "1301", "敏感内容", "inappropriate"))


def _is_timeout_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return "timeout" in name or "timed out" in msg or "readtimeout" in msg


async def _create_completion_text(client: Any, *, stream: bool = True, **kwargs: Any) -> str:
    """Execute chat.completions.create with optional streaming so long Phase A/B responses
    keep the TCP socket alive chunk-by-chunk and never time out mid-generation."""
    if not stream:
        resp = await client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()

    resp = await client.chat.completions.create(stream=True, **kwargs)
    if not hasattr(resp, "__aiter__"):
        return (resp.choices[0].message.content or "").strip()
    parts: list[str] = []
    async for chunk in resp:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        piece = getattr(delta, "content", None) if delta is not None else None
        if piece:
            parts.append(str(piece))
    return "".join(parts).strip()


def _escape_inner_quotes_in_json(text: str) -> str:
    """Heuristically escape stray unescaped ASCII `\"` inside JSON string values
    (e.g. Chinese dialogue `\"他说\"你好\"然后走了\"`) while preserving valid structural quotes."""
    out: list[str] = []
    in_str = False
    escaped = False
    n = len(text)
    for i, ch in enumerate(text):
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_str:
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            if not in_str:
                in_str = True
                out.append(ch)
            else:
                # Look ahead to next non-whitespace char: if it's valid after a closing string quote, close it!
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                nxt = text[j] if j < n else ""
                if nxt in ("", ",", "}", "]", ":"):
                    in_str = False
                    out.append(ch)
                else:
                    out.append('\\"')
        else:
            out.append(ch)
    return "".join(out)


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    """Strip markdown fences or stray prose and parse the outermost JSON object with
    deterministic recovery for trailing commas, control chars, and unescaped inner quotes."""
    txt = (raw_text or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt)

    candidates = [txt]
    start = txt.find("{")
    end = txt.rfind("}")
    if start != -1 and end > start:
        sliced = txt[start : end + 1]
        if sliced != txt:
            candidates.append(sliced)

    last_err: Exception | None = None
    for cand in candidates:
        for variant in (
            cand,
            re.sub(r",\s*([}\]])", r"\1", cand),
            re.sub(r",\s*([}\]])", r"\1", _escape_inner_quotes_in_json(cand)),
        ):
            try:
                parsed = json.loads(variant, strict=False)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError as exc:
                last_err = exc
    if last_err is not None:
        raise last_err
    raise ValueError("LLM response did not contain a valid JSON object")


def _parse_crop_hints_from_notes(notes_text: str) -> dict[str, list[dict[str, Any]]]:
    """Extract `★裁剪候选 [type] name @ pXX [R|L]: visual hint` lines from Phase A notes."""
    hints: dict[str, list[dict[str, Any]]] = {}
    for m in _CROP_HINT_RE.finditer(notes_text or ""):
        atype = m.group(1).strip().lower()
        name = m.group(2).strip()
        page_num = int(m.group(3))
        side = (m.group(4) or "").strip().upper()
        desc = (m.group(5) or "").strip()
        split_label = f"p{page_num:02d} {side}" if side else ""
        norm = generation_service._normalize_name(name)
        if not norm:
            continue
        hints.setdefault(norm, []).append(
            {
                "asset_type": atype,
                "name": name,
                "page_num": page_num,
                "split_label": split_label,
                "hint": desc,
            }
        )
    return hints


def _parse_zoom_requests_from_notes(notes_text: str) -> list[tuple[int, str, str]]:
    """Extract `?需放大复核 @ pXX [R|L]: reason` requests from a Phase A window note."""
    reqs: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str]] = set()
    for m in _ZOOM_HINT_RE.finditer(notes_text or ""):
        page_num = int(m.group(1))
        side = (m.group(2) or "").strip().upper()
        reason = (m.group(3) or "小字或细节放大确认").strip()
        split_label = f"p{page_num:02d} {side}" if side else ""
        key = (page_num, split_label)
        if key not in seen:
            seen.add(key)
            reqs.append((page_num, split_label, reason))
    return reqs


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
    """(label, WebP data_url) pairs for the best reference portrait of each character,
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

    by_freq = sorted(candidates, key=lambda pair: -len(pair[0].episode_ids or {}))
    by_recent = sorted(candidates, key=_ref_rank)
    picked: list[tuple[Asset, AssetImage]] = []
    seen_aids: set[str] = set()
    for pair in [*by_freq[:4], *by_recent]:
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
                encode_reference_portrait_webp(data, max_edge=240, quality=74),
            )
        )
    return blocks


def image_to_data_url(
    data: bytes,
    object_key: str,
    *,
    max_edge: int = _MAX_IMAGE_EDGE,
    quality: int = 78,
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
    quality: int = 78,
) -> tuple[bytes, str]:
    """Downscale and JPEG-compress an image for compact reference/style storage."""
    try:
        img = Image.open(BytesIO(data))
        if max(img.size) <= max_edge and mime == "image/jpeg" and len(data) <= 140_000:
            return data, mime
        ratio = min(1.0, max_edge / max(img.size))
        target_size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
        rgb = img.convert("RGB")
        if ratio < 1.0:
            rgb = rgb.resize(target_size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        logger.warning("Image downscale failed, sending original bytes", exc_info=True)
        return data, mime


def _build_webp_windows(
    page_blocks: list[tuple[str, str]],
    ref_blocks: list[tuple[str, str]],
) -> list[list[tuple[str, str]]]:
    """Pack WebP page blocks into sequential reading windows respecting count & base64 byte budgets."""
    if not page_blocks:
        return []
    ref_chars = sum(len(url) for _, url in ref_blocks)
    page_budget = max(240_000, _MAX_WINDOW_B64_CHARS - ref_chars)
    windows: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_chars = 0
    for block in page_blocks:
        b_len = len(block[1])
        if current and (len(current) >= _MAX_PAGES_PER_WINDOW or current_chars + b_len > page_budget):
            windows.append(current)
            current = []
            current_chars = 0
        current.append(block)
        current_chars += b_len
    if current:
        windows.append(current)
    return windows


# =============================================================================
# Visual Grounding, 2-Stage Coarse-to-Fine Pixel Grid, Self-Inspection & Guard
# =============================================================================


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
        cell = 280
        pad = 14
        a_im.thumbnail((cell, cell), Image.Resampling.LANCZOS)
        c_im.thumbnail((cell, cell), Image.Resampling.LANCZOS)
        pair = Image.new("RGB", (cell * 2 + pad * 3, cell + pad * 2 + 26), (24, 24, 27))
        draw = ImageDraw.Draw(pair)
        pair.paste(a_im, (pad + (cell - a_im.width) // 2, 26 + pad + (cell - a_im.height) // 2))
        pair.paste(c_im, (pad * 2 + cell + (cell - c_im.width) // 2, 26 + pad + (cell - c_im.height) // 2))
        draw.text((pad, 6), "LEFT: ESTABLISHED ANCHOR", fill=(244, 244, 245))
        draw.text((pad * 2 + cell, 6), "RIGHT: NEW CANDIDATE", fill=(255, 220, 40))
        buf = BytesIO()
        pair.save(buf, format="WEBP", quality=82, method=4)
        b64 = base64.b64encode(buf.getvalue()).decode()

        llm_cfg = get_active_llm_config("vision_llm")
        client = get_raw_openai_client(role="vision_llm")
        extra_kwargs = _glm_no_thinking_kwargs(llm_cfg.provider_key, llm_cfg.model)

        prompt = (
            f"Verify visual identity for manga character '{character_name}' ({character_desc[:120]}).\n"
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
                            {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=180,
                timeout=_TIMEOUT_CROP_SEC,
                **extra_kwargs,
            )
        parsed = _extract_json_object(resp.choices[0].message.content or "")
        return bool(parsed.get("same_character", False))
    except Exception:
        logger.debug("Anchor visual verification failed for %s", character_name, exc_info=True)
        return False


async def _coarse_locate_assets_on_page(
    page_bytes: bytes,
    targets: list[tuple[Asset, str, str]],
    project_id: str | None = None,
    episode_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Stage 1 coarse localization on a RED-X / CYAN-Y TRUE-PIXEL coordinate grid."""
    if not targets:
        return {}
    try:
        grid_bytes, orig_w, orig_h = render_pixel_grid(page_bytes, step=100)
        b64 = base64.b64encode(grid_bytes).decode()
        lines = "\n".join(
            f"- id={a.id} | type={a.type} | {a.name} ({desc[:95]})" + (f" | hint: {hint[:80]}" if hint else "")
            for a, desc, hint in targets
        )
        prompt = (
            f"This manga page has ORIGINAL pixel dimensions {orig_w}x{orig_h} (width={orig_w}, height={orig_h}).\n"
            "It has a TRUE-PIXEL coordinate grid overlaid:\n"
            "- RED vertical lines = X coordinates (yellow labels at top/bottom, "
            f"0..{orig_w}, major every 200px, minor every 100px).\n"
            "- CYAN horizontal lines = Y coordinates (cyan labels at left/right, "
            f"0..{orig_h}, major every 200px, minor every 100px).\n\n"
            "For EACH listed visual asset, locate its CLEAREST, BEST appearance on this page in ORIGINAL PIXELS:\n"
            "- For type=character: frame the character's FULL HEAD & FACE "
            "(entire hair top, both eyes, nose, mouth, chin, ears), "
            "with normal recognizable expression. NEVER box speech bubbles, scenery, "
            "a 1-eye slit, or a DIFFERENT character.\n"
            "- For type=item|outfit|location: frame the clear complete object, outfit, or setting panel.\n"
            "- Score visual clarity 0..10 (9-10 = iconic clear front/3/4 view; "
            "6-8 = clear; <6 = occluded/tiny/unclear).\n"
            "- If an asset is NOT clearly drawn on this page, OMIT it completely.\n"
            "- Return ONLY valid JSON:\n"
            '{"crops": [{"id": "<asset_id>", "x0": 100, "y0": 200, "x1": 450, "y1": 580, '
            '"score": 8.5, "full_view": true, "classic_look": true}]}\n\n'
            f"Assets to locate:\n{lines}"
        )

        llm_cfg = get_active_llm_config("vision_llm")
        client = get_raw_openai_client(role="vision_llm")
        extra_kwargs = _glm_no_thinking_kwargs(llm_cfg.provider_key, llm_cfg.model)

        from app.core.telemetry import usage_context

        with usage_context(project_id=project_id, episode_id=episode_id, operation="asset_ground_coarse"):
            resp = await client.chat.completions.create(
                model=llm_cfg.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=900,
                timeout=_TIMEOUT_CROP_SEC,
                **extra_kwargs,
            )
        parsed = _extract_json_object(resp.choices[0].message.content or "")
        type_by_id = {a.id: a.type for a, _, _ in targets}
        out: dict[str, dict[str, Any]] = {}
        for item in parsed.get("crops") or []:
            aid = str(item.get("id") or "")
            if not aid or aid not in type_by_id:
                continue
            x0 = max(0, min(orig_w, int(item.get("x0", 0))))
            y0 = max(0, min(orig_h, int(item.get("y0", 0))))
            x1 = max(0, min(orig_w, int(item.get("x1", 0))))
            y1 = max(0, min(orig_h, int(item.get("y1", 0))))
            score = float(item.get("score") or 0.0)
            full_view = bool(item.get("full_view", item.get("full_face", True)))
            classic_look = bool(item.get("classic_look", True))
            min_score = _MIN_PORTRAIT_SCORE if type_by_id[aid] == "character" else _MIN_ASSET_SCORE
            if x1 - x0 >= 48 and y1 - y0 >= 48 and full_view and score >= min_score:
                out[aid] = {
                    "box": (x0, y0, x1, y1),
                    "orig_size": (orig_w, orig_h),
                    "score": score,
                    "classic_look": classic_look,
                }
        return out
    except Exception:
        logger.debug("Stage 1 coarse pixel-grid localization failed", exc_info=True)
        return {}


async def _refine_crop_with_zoom_grid(
    page_bytes: bytes,
    asset: Asset,
    desc: str,
    rough_box: tuple[int, int, int, int],
    project_id: str | None = None,
    episode_id: str | None = None,
) -> tuple[int, int, int, int]:
    """Stage 2 zoom refinement: crop expanded region around Stage-1 rough box, overlay fine 50px
    RED/CYAN grid labeled in ORIGINAL page pixel coordinates, and return tight refined box."""
    try:
        zoom_bytes, (zx0, zy0, zx1, zy1) = render_zoom_refinement_grid(
            page_bytes, rough_box, expand_ratio=0.28, step=50
        )
        b64 = base64.b64encode(zoom_bytes).decode()
        framing_guide = (
            "Center THIS character's FULL HEAD & FACE cleanly in ~3:4 to 1:1 framing (include top of hair, "
            "ears, both eyes, nose, mouth, chin; STRICTLY EXCLUDE black panel borders, white gutters, "
            "neighboring panel slivers, speech bubbles/tails, and other characters)."
            if asset.type == "character"
            else (
                f"Frame the COMPLETE, unclipped {asset.type} strictly INSIDE its panel border "
                "(exclude white gutters, neighboring panels, and intrusive speech bubbles)."
            )
        )
        prompt = (
            f"Zoomed refinement view for {asset.type} '{asset.name}' ({desc[:100]}).\n"
            f"This zoomed crop spans ORIGINAL page pixels X={zx0}..{zx1}, Y={zy0}..{zy1}.\n"
            "RED vertical lines = X (yellow labels every 100px, thin lines every 50px).\n"
            "CYAN horizontal lines = Y (cyan labels every 100px, thin lines every 50px).\n"
            f"{framing_guide}\n"
            "Return ONLY tight pixel coordinates in ORIGINAL page coordinates:\n"
            '{"x0": 0, "y0": 0, "x1": 0, "y1": 0}'
        )

        llm_cfg = get_active_llm_config("vision_llm")
        client = get_raw_openai_client(role="vision_llm")
        extra_kwargs = _glm_no_thinking_kwargs(llm_cfg.provider_key, llm_cfg.model)

        from app.core.telemetry import usage_context

        with usage_context(project_id=project_id, episode_id=episode_id, operation="asset_ground_refine"):
            resp = await client.chat.completions.create(
                model=llm_cfg.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=180,
                timeout=_TIMEOUT_CROP_SEC,
                **extra_kwargs,
            )
        parsed = _extract_json_object(resp.choices[0].message.content or "")
        nx0 = max(zx0, min(zx1, int(parsed.get("x0", rough_box[0]))))
        ny0 = max(zy0, min(zy1, int(parsed.get("y0", rough_box[1]))))
        nx1 = max(zx0, min(zx1, int(parsed.get("x1", rough_box[2]))))
        ny1 = max(zy0, min(zy1, int(parsed.get("y1", rough_box[3]))))
        if nx1 - nx0 >= 48 and ny1 - ny0 >= 48:
            return (nx0, ny0, nx1, ny1)
    except Exception:
        logger.debug("Stage 2 zoom refinement fell back to Stage 1 box for %s", asset.name, exc_info=True)
    return rough_box


async def _self_inspect_crops_contact_sheet(
    candidates: list[dict[str, Any]],
    project_id: str | None = None,
    episode_id: str | None = None,
) -> list[dict[str, Any]]:
    """Stage 3 contact-sheet self-inspection: visually verify all newly cropped tiles in ONE call,
    reject wrong/blank crops, and auto-adjust clipped boxes once."""
    if not candidates:
        return []
    sheet_items = [
        (idx, f"{c['asset'].name} ({c['asset'].type})", c["crop_bytes"])
        for idx, c in enumerate(candidates, start=1)
    ]
    sheet_bytes = render_crop_contact_sheet(sheet_items, cell=320, cols=3)
    if not sheet_bytes:
        return candidates

    b64 = base64.b64encode(sheet_bytes).decode()
    desc_lines = "\n".join(
        f"- #{idx}: [{c['asset'].type}] {c['asset'].name} — expected: {(c['desc'] or '')[:90]} "
        f"| current box={list(c['box'])} on page {c['orig_size'][0]}x{c['orig_size'][1]}"
        for idx, c in enumerate(candidates, start=1)
    )
    prompt = (
        "Strict visual QA self-inspection of newly cropped manga asset thumbnails (#1..#N).\n"
        "Inspect EACH numbered tile carefully against its expected asset:\n"
        "- verdict='ok': target is cleanly centered & unclipped (full head/face for character; whole object/scene "
        "for item/outfit/location) with minimal speech-bubble or border clutter (score >= 7.0).\n"
        "- verdict='adjust': right subject, but edges clip part of the object/face OR include intrusive "
        "speech bubbles, black panel borders, or white gutters from an adjacent panel — provide signed pixel "
        "shifts dx0, dy0, dx1, dy1 to trim/expand cleanly (e.g. dy0=-60 expands top upward when forehead/eyes/"
        "glasses are cut off; dy0=+35 trims top gutter down; dx1=-40 trims right speech bubble inward).\n"
        "- verdict='reject': WRONG character centered, target face cut in half on an edge, forehead/eyes/glasses "
        "cut off by top edge without room to recover, scenery/building instead of face, half-cut unidentifiable "
        "object, blank speech bubble, or score < 6.0.\n"
        'Return ONLY valid JSON: {"reviews": [{"num": 1, "what": "what is actually drawn", '
        '"verdict": "ok|adjust|reject", "dx0": 0, "dy0": 0, "dx1": 0, "dy1": 0, "score": 8.8}]}\n\n'
        f"Expected tiles:\n{desc_lines}"
    )

    try:
        llm_cfg = get_active_llm_config("vision_llm")
        client = get_raw_openai_client(role="vision_llm")
        extra_kwargs = _glm_no_thinking_kwargs(llm_cfg.provider_key, llm_cfg.model)

        from app.core.telemetry import usage_context

        with usage_context(project_id=project_id, episode_id=episode_id, operation="crop_inspect"):
            resp = await client.chat.completions.create(
                model=llm_cfg.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=1000,
                timeout=_TIMEOUT_CROP_SEC,
                **extra_kwargs,
            )
        parsed = _extract_json_object(resp.choices[0].message.content or "")
        review_by_num = {int(r.get("num")): r for r in (parsed.get("reviews") or []) if str(r.get("num")).isdigit()}
    except Exception:
        logger.debug("Stage 3 contact-sheet self-inspection failed; keeping Stage 2 crops", exc_info=True)
        return candidates

    verified: list[dict[str, Any]] = []
    for idx, cand in enumerate(candidates, start=1):
        rev = review_by_num.get(idx)
        if not rev:
            verified.append(cand)
            continue
        verdict = str(rev.get("verdict") or "ok").strip().lower()
        if rev.get("score") is not None:
            try:
                cand["score"] = float(rev["score"])
            except (TypeError, ValueError):
                pass
        min_score = _MIN_PORTRAIT_SCORE if cand["asset"].type == "character" else _MIN_ASSET_SCORE
        if verdict == "reject" or (verdict != "adjust" and cand["score"] < min_score):
            logger.info(
                "Self-inspection rejected crop #%d for %s (%s, score=%.1f): %s",
                idx,
                cand["asset"].name,
                cand["asset"].type,
                cand["score"],
                rev.get("what", ""),
            )
            continue
        if verdict == "adjust":
            x0, y0, x1, y1 = cand["box"]
            w, h = cand["orig_size"]
            dx0 = int(rev.get("dx0") or 0)
            dy0 = int(rev.get("dy0") or 0)
            dx1 = int(rev.get("dx1") or 0)
            dy1 = int(rev.get("dy1") or 0)
            adj_box = (
                max(0, min(w - 48, x0 + dx0)),
                max(0, min(h - 48, y0 + dy0)),
                max(48, min(w, x1 + dx1)),
                max(48, min(h, y1 + dy1)),
            )
            re_crop = crop_pixel_box(
                cand["page_bytes"],
                adj_box,
                pad_ratio=0.0,
                check_portrait_aspect=(cand["asset"].type == "character"),
            )
            if re_crop:
                cand["box"] = adj_box
                cand["crop_bytes"] = re_crop
            elif cand["score"] < min_score:
                continue
        verified.append(cand)
    return verified


async def elect_best_character_portrait(db: AsyncSession, asset: Asset) -> AssetImage | None:
    """Run a contact-sheet audit & election over a character's candidate portraits to purge invalid
    tiles and promote the clearest, most iconic front/3/4 face to primary `reference`."""
    images = list(
        (await db.execute(select(AssetImage).where(AssetImage.asset_id == asset.id).order_by(AssetImage.created_at)))
        .scalars()
        .all()
    )
    if len(images) < 2:
        return images[0] if images else None

    for im in images:
        meta = im.meta or {}
        if meta.get("manual_primary") or (im.kind in ("reference", "turnaround") and not meta.get("auto_cropped")):
            return im

    candidates = images[:4]
    tiles: list[tuple[int, AssetImage, bytes]] = []
    for idx, im in enumerate(candidates, start=1):
        raw = storage_service.get_object_bytes(settings.MINIO_BUCKET, im.image_path)
        if raw:
            tiles.append((idx, im, raw))

    if len(tiles) < 2:
        return candidates[0]

    sheet_bytes = render_crop_contact_sheet(
        [(num, f"{asset.name}", raw) for num, _im, raw in tiles],
        cell=300,
        cols=2,
    )
    if not sheet_bytes:
        return candidates[0]
    b64 = base64.b64encode(sheet_bytes).decode()

    try:
        llm_cfg = get_active_llm_config("vision_llm")
        client = get_raw_openai_client(role="vision_llm")
        extra_kwargs = _glm_no_thinking_kwargs(llm_cfg.provider_key, llm_cfg.model)

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
                            {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=500,
                timeout=_TIMEOUT_CROP_SEC,
                **extra_kwargs,
            )
        parsed = _extract_json_object(resp.choices[0].message.content or "")
        invalid_nums = {int(n) for n in (parsed.get("invalid_nums") or []) if str(n).isdigit()}
        win_num = parsed.get("winner")
        valid_tiles = [(num, im) for num, im, _ in tiles if num not in invalid_nums]
        winner = (
            next((im for num, im in valid_tiles if num == int(win_num)), None) if win_num is not None else None
        )
        if winner is None and valid_tiles:
            winner = valid_tiles[0][1]

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
    *,
    split_raw_map: dict[str, bytes] | None = None,
    crop_hints: dict[str, list[dict[str, Any]]] | None = None,
    prune_ungrounded_new_assets: bool = False,
    crop_concurrency: int = 2,
) -> int:
    """2-stage coarse-to-fine pixel-grid localization + contact-sheet self-inspection +
    visual-anchor identity guard + automatic primary portrait election."""
    if not raw_pages:
        return 0

    split_map = split_raw_map or {}
    hints_map = crop_hints or {}

    def _find_hint(asset: Asset, preferred_page: int | None) -> tuple[int | None, str, str]:
        names = [asset.name, *((asset.tags or {}).get("aliases") or [])]
        matched: list[dict[str, Any]] = []
        for nm in names:
            norm = generation_service._normalize_name(str(nm or ""))
            if norm and norm in hints_map:
                matched.extend(hints_map[norm])
        if not matched:
            return preferred_page, "", ""
        if preferred_page is not None:
            for item in matched:
                if item["page_num"] == int(preferred_page):
                    return item["page_num"], item["split_label"], item["hint"]
        best = matched[0]
        return best["page_num"], best["split_label"], best["hint"]

    raw_candidates: list[tuple[Asset, int | None, str, str, str]] = []
    seen_ids: set[str] = set()

    for asset, meta in discovered_pairs:
        if asset.id in seen_ids:
            continue
        seen_ids.add(asset.id)
        sp, split_lbl, hint_txt = _find_hint(asset, meta.get("source_page"))
        raw_candidates.append((asset, sp, split_lbl, asset.description or "", hint_txt))

    for cs in character_sightings:
        norm = generation_service._normalize_name(cs.get("name", ""))
        asset = matched_chars_by_name.get(norm)
        if not asset or asset.id in seen_ids:
            continue
        seen_ids.add(asset.id)
        sp, split_lbl, hint_txt = _find_hint(asset, cs.get("source_page"))
        desc = cs.get("appearance") or asset.description or ""
        raw_candidates.append((asset, sp, split_lbl, desc, hint_txt))

    pending: list[dict[str, Any]] = []
    for asset, source_page, split_lbl, desc, hint_txt in raw_candidates:
        if not source_page or int(source_page) not in raw_pages:
            continue
        existing_imgs = list(
            (await db.execute(select(AssetImage).where(AssetImage.asset_id == asset.id))).scalars().all()
        )
        if asset.type == "character":
            has_manual = any(
                (im.meta or {}).get("manual_primary")
                or (im.kind in ("reference", "turnaround") and not (im.meta or {}).get("auto_cropped"))
                for im in existing_imgs
            )
            if has_manual:
                continue
            if any((im.meta or {}).get("episode_id") == episode_id for im in existing_imgs):
                continue
            auto_imgs = [im for im in existing_imgs if (im.meta or {}).get("auto_cropped")]
            top_score = max((float((im.meta or {}).get("portrait_score") or 0.0) for im in auto_imgs), default=0.0)
            has_strong_primary = any(
                (im.meta or {}).get("is_primary") and float((im.meta or {}).get("portrait_score") or 0.0) >= 8.5
                for im in auto_imgs
            )
            if (
                has_strong_primary
                or (len(auto_imgs) >= 2 and top_score >= 8.0)
                or len(auto_imgs) >= _MAX_AUTO_PORTRAITS
            ):
                continue
        elif existing_imgs:
            continue

        page_num = int(source_page)
        page_key = split_lbl if (split_lbl and split_lbl in split_map) else f"p{page_num:02d}"
        page_bytes = split_map[split_lbl] if (split_lbl and split_lbl in split_map) else raw_pages[page_num]
        pending.append(
            {
                "asset": asset,
                "page_num": page_num,
                "page_key": page_key,
                "page_bytes": page_bytes,
                "desc": desc,
                "hint": hint_txt,
                "existing_imgs": existing_imgs,
            }
        )

    # Stage 1: Coarse localization grouped by page image
    by_page_key: dict[str, list[dict[str, Any]]] = {}
    for item in pending:
        if item["asset"].type in ("character", "item", "location", "outfit"):
            by_page_key.setdefault(item["page_key"], []).append(item)

    coarse_map: dict[str, dict[str, Any]] = {}
    sem_crop = asyncio.Semaphore(max(1, min(8, int(crop_concurrency or 2))))

    async def _run_coarse(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        async with sem_crop:
            return await _coarse_locate_assets_on_page(
                items[0]["page_bytes"],
                [(it["asset"], it["desc"], it["hint"]) for it in items],
                project_id=items[0]["asset"].project_id,
                episode_id=episode_id,
            )

    page_groups = list(by_page_key.values())[:_MAX_CROP_PAGES_PER_EPISODE]
    if page_groups:
        coarse_results = await asyncio.gather(*(_run_coarse(grp) for grp in page_groups))
        for res in coarse_results:
            coarse_map.update(res)

    # Stage 2: Fine 50px zoom refinement for characters and smaller visual items/outfits
    async def _build_refined_candidate(item: dict[str, Any]) -> dict[str, Any] | None:
        asset: Asset = item["asset"]
        ginfo = coarse_map.get(asset.id)
        if not ginfo:
            return None
        rough_box = ginfo["box"]
        orig_w, orig_h = ginfo["orig_size"]
        # Stage 2 fine zoom refinement is reserved for characters (pixel-perfect face avatars);
        # items/locations/outfits rely on Stage 1 coarse grid + Stage 3 contact-sheet adjust.
        needs_zoom = asset.type == "character"
        final_box = rough_box
        if needs_zoom:
            async with sem_crop:
                final_box = await _refine_crop_with_zoom_grid(
                    item["page_bytes"],
                    asset,
                    item["desc"],
                    rough_box,
                    project_id=asset.project_id,
                    episode_id=episode_id,
                )
        crop_bytes = crop_pixel_box(
            item["page_bytes"],
            final_box,
            pad_ratio=0.0 if needs_zoom else 0.03,
            check_portrait_aspect=(asset.type == "character"),
        )
        if not crop_bytes:
            # Fallback to Stage-1 rough box if refined box failed size/stddev check
            crop_bytes = crop_pixel_box(
                item["page_bytes"],
                rough_box,
                pad_ratio=0.04,
                check_portrait_aspect=(asset.type == "character"),
            )
            final_box = rough_box
        if not crop_bytes:
            return None
        return {
            **item,
            "box": final_box,
            "orig_size": (orig_w, orig_h),
            "score": ginfo["score"],
            "classic_look": ginfo["classic_look"],
            "crop_bytes": crop_bytes,
        }

    refined_raw = await asyncio.gather(*(_build_refined_candidate(it) for it in pending))
    refined_candidates = [c for c in refined_raw if c is not None]

    # Stage 3: Single contact-sheet self-inspection + 1x auto-adjust retry across all crops
    if refined_candidates:
        verified_candidates = await _self_inspect_crops_contact_sheet(
            refined_candidates,
            project_id=refined_candidates[0]["asset"].project_id,
            episode_id=episode_id,
        )
    else:
        verified_candidates = []

    # Stage 4: Visual-anchor same-character guard + MinIO/DB persistence + portrait election
    created = 0
    cropped_asset_ids: set[str] = set()
    assets_to_elect: list[Asset] = []

    for cand in verified_candidates:
        asset: Asset = cand["asset"]
        existing_imgs: list[AssetImage] = cand["existing_imgs"]
        crop_bytes: bytes = cand["crop_bytes"]
        page_num: int = cand["page_num"]

        if asset.type == "character":
            if existing_imgs:
                anchor = min(existing_imgs, key=_image_rank_key)
                anchor_bytes = storage_service.get_object_bytes(settings.MINIO_BUCKET, anchor.image_path)
                if anchor_bytes:
                    same = await _verify_same_character_as_anchor(
                        anchor_bytes,
                        crop_bytes,
                        asset.name,
                        cand["desc"],
                        project_id=asset.project_id,
                        episode_id=episode_id,
                    )
                    if not same:
                        logger.info(
                            "Anchor guard rejected mismatched portrait for %s on ep=%s p=%s",
                            asset.name,
                            episode_id,
                            page_num,
                        )
                        continue
            auto_imgs = [im for im in existing_imgs if (im.meta or {}).get("auto_cropped")]
            if len(auto_imgs) >= _MAX_AUTO_PORTRAITS:
                worst = min(auto_imgs, key=lambda im: float((im.meta or {}).get("portrait_score") or 0.0))
                if cand["score"] <= float((worst.meta or {}).get("portrait_score") or 0.0):
                    continue
                await db.delete(worst)
            meta_payload = {
                "auto_cropped": True,
                "grounded": True,
                "refined_2stage": True,
                "episode_id": episode_id,
                "page_number": page_num,
                "portrait_score": cand["score"],
                "classic_look": cand["classic_look"],
            }
        else:
            meta_payload = {
                "auto_cropped": True,
                "grounded": True,
                "refined_2stage": True,
                "episode_id": episode_id,
                "page_number": page_num,
                "portrait_score": cand["score"],
            }

        object_key = storage_service.generate_object_key(f"assets/{asset.id}", "auto_ref.png")
        storage_service.upload_file(settings.MINIO_BUCKET, object_key, crop_bytes, content_type="image/png")
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
        cropped_asset_ids.add(asset.id)
        if asset.type == "character" and len(existing_imgs) + 1 >= 2:
            assets_to_elect.append(asset)

    # Prune newly discovered non-character assets that had NO verifiable visual crop on the manga pages
    # (prevents unillustrated text-only clutter in the Asset Library while keeping all characters intact).
    if prune_ungrounded_new_assets:
        for asset, _meta in discovered_pairs:
            if asset.type not in ("item", "location", "outfit"):
                continue
            if asset.id in cropped_asset_ids:
                continue
            if len(asset.episode_ids or {}) > 1:
                continue
            img_cnt = (
                await db.execute(select(func.count()).select_from(AssetImage).where(AssetImage.asset_id == asset.id))
            ).scalar() or 0
            if img_cnt == 0:
                logger.info(
                    "Pruning ungrounded newly discovered %s '%s' (no valid visual crop on ep=%s)",
                    asset.type,
                    asset.name,
                    episode_id,
                )
                await db.delete(asset)

    if created or prune_ungrounded_new_assets:
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

    if not core_rules and recent_rules:
        core_rules = recent_rules[:15]

    for rule in understanding_dict.get("world_rules_discovered") or []:
        rule_str = str(rule).strip()
        if not rule_str or _rule_is_duplicate(rule_str, [*core_rules, *recent_rules]):
            continue
        if len(core_rules) < 15:
            core_rules.append(rule_str)
        recent_rules.append(rule_str)

    rolling_tail = [r for r in recent_rules if r not in core_rules][-35:]
    bible["core_rules"] = core_rules[:15]
    bible["discovered_rules"] = [*bible["core_rules"], *rolling_tail]
    bible["last_updated_episode"] = str(episode_label)

    canon["story_bible"] = bible
    project.canon_rules = canon
    await db.commit()


# =============================================================================
# Phase A: Sequential High-Res Page Reading Notes (90%+ KV Prefix Cache Hit)
# Phase B: Whole-Episode Coherent Structured Synthesis (Zero Fragmentation)
# =============================================================================


async def _read_episode_pages_sequential(
    *,
    episode: Episode,
    preferred_language: str,
    shared_prefix_blocks: list[dict[str, Any]],
    windows: list[list[tuple[str, str]]],
    raw_pages: dict[int, bytes],
    split_raw_map: dict[str, bytes],
    concurrency: int = 1,
    progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> str:
    """Read episode windows sequentially (concurrency=1, zero blind spots) or with Window-1 warmup
    followed by bounded concurrent windows (concurrency>=2, for high-concurrency API providers)."""
    vision_cfg = get_active_llm_config("vision_llm")
    vision_client = get_raw_openai_client(role="vision_llm")
    extra_kwargs = _glm_no_thinking_kwargs(vision_cfg.provider_key, vision_cfg.model)

    from app.core.telemetry import usage_context

    all_notes: list[str] = []
    zoom_count = 0
    total_windows = len(windows)
    eff_conc = max(1, min(8, int(concurrency or 1)))

    async def _emit(payload: dict[str, Any]) -> None:
        if progress_callback:
            try:
                await progress_callback(payload)
            except Exception:
                logger.debug("Progress callback failed", exc_info=True)

    # Separate shared prefix into its own message turn so providers with message-boundary
    # KV prefix caching (OpenAI, Claude, Gemini, DeepSeek, GLM-5.3-flash) cache the entire
    # Story Bible + Known Cast + 6 WebP reference portraits cleanly across every window!
    prefix_turns: list[dict[str, Any]] = [
        {"role": "system", "content": READ_PAGES_SYSTEM_PROMPT},
        {"role": "user", "content": shared_prefix_blocks},
        {"role": "assistant", "content": "已读取全书设定、前情摘要与角色参考图，请发送接下来的漫画页。"},
    ]

    async def _read_once(window_label: str, blocks: list[tuple[str, str]], earlier_notes: str) -> str:
        tail_prompt = Template(READ_WINDOW_TAIL_PROMPT).render(
            preferred_language=preferred_language,
            window_label=window_label,
            earlier_notes=earlier_notes,
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": tail_prompt}]
        for label, url in blocks:
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {"url": url}})

        logger.info(
            "Phase A reading ep=%s (%s) with %d WebP blocks (concurrency=%d)",
            episode.id,
            window_label,
            len(blocks),
            eff_conc,
        )
        with usage_context(project_id=episode.project_id, episode_id=episode.id, operation="understand_read"):
            return await _create_completion_text(
                vision_client,
                stream=True,
                model=vision_cfg.model,
                messages=[*prefix_turns, {"role": "user", "content": content}],
                max_tokens=2048,
                timeout=_TIMEOUT_READ_SEC,
                **extra_kwargs,
            )

    async def _read_window_resilient(idx: int, wb: list[tuple[str, str]], earlier: str) -> str:
        first_lbl, last_lbl = wb[0][0], wb[-1][0]
        window_label = f"Window {idx + 1}/{total_windows}: {first_lbl} ~ {last_lbl}"
        try:
            return await _read_once(window_label, wb, earlier)
        except Exception as exc:
            if _is_timeout_error(exc) and len(wb) >= 2:
                # Auto-bisect timed-out multi-page windows into smaller halves instead of failing the episode
                mid = len(wb) // 2
                logger.warning(
                    "Window %s timed out with %d blocks; auto-splitting into %d + %d blocks",
                    window_label,
                    len(wb),
                    mid,
                    len(wb) - mid,
                )
                left_note = await _read_once(f"{window_label}.a", wb[:mid], earlier)
                right_earlier = f"{earlier}\n\n{left_note}"[-_MAX_ROLLING_NOTES_CHARS:] if left_note else earlier
                right_note = await _read_once(f"{window_label}.b", wb[mid:], right_earlier)
                return "\n\n".join(n for n in (left_note, right_note) if n)
            if not _is_content_filter_error(exc):
                raise
            if len(wb) <= 1:
                logger.warning("Skipping single page %s due to upstream content filter", wb[0][0])
                return f"- {wb[0][0]}: 内容审核拦截 -> 跳过"
            logger.warning(
                "Window %s hit upstream content filter; reading %d pages individually",
                window_label,
                len(wb),
            )
            sub_notes: list[str] = []
            for p_idx, single_block in enumerate(wb):
                try:
                    sub_notes.append(await _read_once(f"{window_label}.{p_idx + 1}", [single_block], earlier))
                except Exception as sub_exc:
                    if _is_content_filter_error(sub_exc):
                        logger.warning("Skipped flagged page %s (content filter)", single_block[0])
                        sub_notes.append(f"- {single_block[0]}: 内容审核拦截 -> 跳过")
                    else:
                        raise
            return "\n".join(n for n in sub_notes if n)

    async def _zoom_reread_page(page_num: int, split_label: str, reason: str) -> str:
        raw = split_raw_map.get(split_label) if split_label else raw_pages.get(page_num)
        if not raw:
            return ""
        lbl = split_label or f"p{page_num:02d}"
        hd_url = encode_highres_page_webp(raw, lbl, max_w=1360, max_h=1960)
        prompt = (
            f"Zoomed HD re-read of {lbl} (reason: {reason}).\n"
            f"Carefully transcribe any small text, exact names/terms, or visual details on {lbl} "
            f"in {preferred_language}. Output 2-5 concise factual bullets only."
        )
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": hd_url}},
        ]
        try:
            with usage_context(project_id=episode.project_id, episode_id=episode.id, operation="understand_zoom"):
                txt = await _create_completion_text(
                    vision_client,
                    stream=True,
                    model=vision_cfg.model,
                    messages=[*prefix_turns, {"role": "user", "content": content}],
                    max_tokens=800,
                    timeout=_TIMEOUT_READ_SEC,
                    **extra_kwargs,
                )
            return f"### [高清放大复核 {lbl}]\n{txt}" if txt else ""
        except Exception:
            logger.debug("Zoom HD re-read skipped for %s", lbl, exc_info=True)
            return ""

    if not windows:
        return ""

    if eff_conc <= 1 or total_windows == 1:
        for idx, wb in enumerate(windows):
            first_lbl, last_lbl = wb[0][0], wb[-1][0]
            pct_start = 10 + int((idx / max(1, total_windows)) * 55)
            await _emit(
                {
                    "phase": "read",
                    "label": f"Phase A 逐页读图 ({idx + 1}/{total_windows} 窗 · {first_lbl}~{last_lbl})",
                    "window_done": idx,
                    "window_total": total_windows,
                    "episode_pct": pct_start,
                }
            )
            earlier = "\n\n".join(all_notes)[-_MAX_ROLLING_NOTES_CHARS:] if all_notes else ""
            note = await _read_window_resilient(idx, wb, earlier)
            if note:
                all_notes.append(note)
                if zoom_count < _MAX_ZOOM_REREADS_PER_EPISODE:
                    for page_num, split_lbl, reason in _parse_zoom_requests_from_notes(note):
                        if zoom_count >= _MAX_ZOOM_REREADS_PER_EPISODE:
                            break
                        await _emit(
                            {
                                "phase": "zoom",
                                "label": f"高清放大复核 {split_lbl or f'p{page_num:02d}'}",
                                "window_done": idx + 1,
                                "window_total": total_windows,
                                "episode_pct": min(68, 10 + int(((idx + 1) / max(1, total_windows)) * 55)),
                            }
                        )
                        hd_note = await _zoom_reread_page(page_num, split_lbl, reason)
                        zoom_count += 1
                        if hd_note:
                            all_notes.append(hd_note)
    else:
        w0_first, w0_last = windows[0][0][0], windows[0][-1][0]
        await _emit(
            {
                "phase": "read",
                "label": f"Phase A 逐页读图 (热身 1/{total_windows} 窗 · {w0_first}~{w0_last})",
                "window_done": 0,
                "window_total": total_windows,
                "episode_pct": 10,
            }
        )
        first_note = await _read_window_resilient(0, windows[0], "")
        done_count = 1
        await _emit(
            {
                "phase": "read",
                "label": f"Phase A 并发读图 ({done_count}/{total_windows} 窗完成 · 并发 x{eff_conc})",
                "window_done": done_count,
                "window_total": total_windows,
                "episode_pct": 10 + int((done_count / max(1, total_windows)) * 55),
            }
        )
        opening_ctx = first_note[-_MAX_ROLLING_NOTES_CHARS:] if first_note else ""
        sem_read = asyncio.Semaphore(eff_conc)

        async def _run_parallel_win(idx: int, wb: list[tuple[str, str]]) -> str:
            nonlocal done_count
            async with sem_read:
                res = await _read_window_resilient(idx, wb, opening_ctx)
            done_count += 1
            await _emit(
                {
                    "phase": "read",
                    "label": f"Phase A 并发读图 ({done_count}/{total_windows} 窗完成 · 并发 x{eff_conc})",
                    "window_done": done_count,
                    "window_total": total_windows,
                    "episode_pct": 10 + int((done_count / max(1, total_windows)) * 55),
                }
            )
            return res

        rest_notes = await asyncio.gather(*(_run_parallel_win(i, wb) for i, wb in enumerate(windows[1:], start=1)))
        ordered_notes = [n for n in [first_note, *rest_notes] if n]
        all_notes.extend(ordered_notes)
        for page_num, split_lbl, reason in _parse_zoom_requests_from_notes("\n\n".join(ordered_notes)):
            if zoom_count >= _MAX_ZOOM_REREADS_PER_EPISODE:
                break
            await _emit(
                {
                    "phase": "zoom",
                    "label": f"高清放大复核 {split_lbl or f'p{page_num:02d}'}",
                    "window_done": total_windows,
                    "window_total": total_windows,
                    "episode_pct": 68,
                }
            )
            hd_note = await _zoom_reread_page(page_num, split_lbl, reason)
            zoom_count += 1
            if hd_note:
                all_notes.append(hd_note)

    return "\n\n".join(all_notes).strip()


async def _synthesize_episode_understanding(
    *,
    episode: Episode,
    project_title: str,
    preferred_language: str,
    current_main_plot: dict[str, Any],
    previous_summary: str,
    known_characters: list[dict[str, Any]],
    known_other_assets: list[dict[str, Any]],
    open_pit_refs: list[dict[str, Any]],
    episode_notes: str,
) -> dict[str, Any]:
    """Phase B: Single whole-episode text synthesis over complete reading notes -> zero fragmentation,
    immune to instructor multi-tool-call bugs, with JSON mode + inner-quote recovery + repair retry."""
    main_cfg = get_active_llm_config("main_llm")
    main_client = get_raw_openai_client(role="main_llm")
    extra_kwargs = _glm_no_thinking_kwargs(main_cfg.provider_key, main_cfg.model)

    user_prompt = Template(SYNTHESIZE_EPISODE_USER_PROMPT).render(
        project_title=project_title,
        preferred_language=preferred_language,
        episode_number=episode.label or episode.number,
        main_plot=current_main_plot,
        previous_summary=previous_summary,
        known_characters=known_characters,
        known_other_assets=known_other_assets,
        open_pits=open_pit_refs,
        episode_notes=episode_notes,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYNTHESIZE_EPISODE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    max_tokens = min(8192, max(4096, int(main_cfg.max_tokens or 4096)))

    from app.core.telemetry import usage_context

    last_err: Exception | None = None
    use_json_mode = main_cfg.provider_key not in ("anthropic",)
    for attempt in range(3):
        call_kwargs: dict[str, Any] = {**extra_kwargs}
        if use_json_mode:
            call_kwargs["response_format"] = {"type": "json_object"}
        with usage_context(project_id=episode.project_id, episode_id=episode.id, operation="understand_synthesize"):
            try:
                raw_txt = await _create_completion_text(
                    main_client,
                    stream=True,
                    model=main_cfg.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    timeout=_TIMEOUT_SYNTH_SEC,
                    **call_kwargs,
                )
            except Exception as api_exc:
                if use_json_mode and "response_format" in str(api_exc).lower():
                    use_json_mode = False
                    call_kwargs.pop("response_format", None)
                    raw_txt = await _create_completion_text(
                        main_client,
                        stream=True,
                        model=main_cfg.model,
                        messages=messages,
                        max_tokens=max_tokens,
                        timeout=_TIMEOUT_SYNTH_SEC,
                        **call_kwargs,
                    )
                else:
                    raise
        try:
            parsed = _extract_json_object(raw_txt)
            model_obj = EpisodeUnderstanding.model_validate(parsed)
            return model_obj.model_dump()
        except Exception as exc:
            last_err = exc
            logger.warning(
                "Phase B synthesis JSON/schema error on ep=%s (attempt %d): %s",
                episode.id,
                attempt + 1,
                exc,
            )
            snippet = ""
            if isinstance(exc, json.JSONDecodeError) and exc.pos is not None:
                lo = max(0, exc.pos - 80)
                hi = min(len(raw_txt), exc.pos + 80)
                snippet = f"\nBroken region near char {exc.pos}: ...{raw_txt[lo:hi]}..."
            messages.append({"role": "assistant", "content": raw_txt})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your previous JSON failed validation with error: {exc}{snippet}\n"
                        'CRITICAL: NEVER put unescaped ASCII double quotes (") inside string values '
                        "(use 『』 or 「」 for quotes instead). Return ONLY the single valid JSON object."
                    ),
                }
            )
    raise RuntimeError(f"Phase B synthesis failed after 3 attempts for episode {episode.id}: {last_err}")


async def run_multimodal_understanding(
    db: AsyncSession,
    episode: Episode,
    page_refs: list[tuple[int, str]],
    fallback_text: str = "",
    target_status: str | None = "understood",
    authoritative_storyboard: dict | None = None,
    concurrency: int | None = None,
    progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict:
    """Understand one episode via two-phase sequential WebP reading + whole-episode synthesis +
    deterministic sanitization + 2-stage coarse-to-fine cropping & contact-sheet self-inspection."""
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
        key=lambda p: (-(1 if p.introduced_episode_id in recent_ep_ids else 0) * 4 - p.priority,)
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

    previous_summary = await memory_service.get_branch_history_before(
        db,
        episode.project_id,
        episode.branch_id,
        episode.number,
        fallback_long_summary=project.long_summary if project else "",
    )
    canon_rules = (project.canon_rules or {}) if project else {}
    story_bible = canon_rules.get("story_bible") or {}
    current_main_plot = story_bible.get("main_plot") or {}
    rtl = str(canon_rules.get("reading_direction") or "rtl").lower() != "ltr"
    preferred_language = resolve_language_label(project.language if project else "zh")

    reference_blocks = await _character_reference_blocks(db, known_assets, recent_ep_ids=recent_ep_ids)

    raw_pages: dict[int, bytes] = {}
    split_raw_map: dict[str, bytes] = {}
    page_blocks: list[tuple[str, str]] = []
    refs_to_load = page_refs[:3] if authoritative_storyboard else page_refs
    vision_cfg = get_active_llm_config("vision_llm")
    eff_conc = max(1, min(8, int(concurrency or getattr(vision_cfg, "concurrency", 1) or 1)))

    async def _emit(payload: dict[str, Any]) -> None:
        if progress_callback:
            try:
                await progress_callback({"concurrency": eff_conc, **payload})
            except Exception:
                logger.debug("Progress callback failed", exc_info=True)

    await _emit({"phase": "prepare", "label": f"预处理 {len(refs_to_load)} 页高清 WebP 漫画页", "episode_pct": 5})

    for page_number, object_key in refs_to_load:
        data = storage_service.get_object_bytes(settings.MINIO_BUCKET, object_key)
        if data is None:
            logger.warning("Page image missing in object storage: %s (page %s)", object_key, page_number)
            continue
        raw_pages[int(page_number)] = data
        blocks, splits = prepare_manga_page_blocks(page_number, data, object_key, rtl=rtl)
        page_blocks.extend(blocks)
        split_raw_map.update(splits)

    if not page_blocks and not fallback_text:
        raise ValueError("Episode has no page images and no text content to understand")

    # Build byte-identical shared prefix for Phase A (Series Title + Story Bible + Known Cast + 6 WebP portraits)
    project_title = (project.title or "").strip() if project else ""
    shared_prefix_text = Template(READ_SHARED_PREFIX_PROMPT).render(
        project_title=project_title,
        preferred_language=preferred_language,
        episode_number=episode.label or episode.number,
        episode_title=episode.title or "",
        main_plot=current_main_plot,
        previous_summary=previous_summary,
        known_characters=known_characters,
        known_other_assets=known_other_assets,
        open_pits=open_pit_refs,
    )
    shared_prefix_blocks: list[dict[str, Any]] = [{"type": "text", "text": shared_prefix_text}]
    for label, url in reference_blocks:
        shared_prefix_blocks.append({"type": "text", "text": label})
        shared_prefix_blocks.append({"type": "image_url", "image_url": {"url": url}})

    # Phase A: Crisp WebP reading notes (strictly sequential when concurrency=1; warm+concurrent when >=2)
    episode_notes = ""
    if page_blocks:
        windows = _build_webp_windows(page_blocks, reference_blocks)
        episode_notes = await _read_episode_pages_sequential(
            episode=episode,
            preferred_language=preferred_language,
            shared_prefix_blocks=shared_prefix_blocks,
            windows=windows,
            raw_pages=raw_pages,
            split_raw_map=split_raw_map,
            concurrency=eff_conc,
            progress_callback=_emit,
        )

    if fallback_text:
        episode_notes = (
            f"{episode_notes}\n\n## Authoritative Episode Script / Text\n{fallback_text}".strip()
            if episode_notes
            else fallback_text
        )

    crop_hints = _parse_crop_hints_from_notes(episode_notes)

    # Phase B: Single coherent whole-episode structured synthesis
    await _emit({"phase": "synthesize", "label": "Phase B 整话结构化剧情与设定合成", "episode_pct": 72})
    understanding_dict = await _synthesize_episode_understanding(
        episode=episode,
        project_title=project_title,
        preferred_language=preferred_language,
        current_main_plot=current_main_plot,
        previous_summary=previous_summary,
        known_characters=known_characters,
        known_other_assets=known_other_assets,
        open_pit_refs=open_pit_refs,
        episode_notes=episode_notes,
    )

    # Phase C: Deterministic post-validation & cleanup
    understanding_dict = sanitize_understanding(
        understanding_dict,
        valid_pages=set(raw_pages.keys()) if raw_pages else None,
        max_new_pits=_MAX_NEW_PITS_PER_EPISODE,
    )

    # Backfill missing source_page from Phase A `★裁剪候选` hints before persistence/cropping
    for ch in understanding_dict.get("characters") or []:
        if not ch.get("source_page"):
            for nm in [ch.get("name"), *(ch.get("aliases") or [])]:
                norm = generation_service._normalize_name(str(nm or ""))
                if norm and norm in crop_hints:
                    ch["source_page"] = crop_hints[norm][0]["page_num"]
                    break
    for na in understanding_dict.get("new_assets") or []:
        if not na.get("source_page"):
            for nm in [na.get("name"), *(na.get("aliases") or [])]:
                norm = generation_service._normalize_name(str(nm or ""))
                if norm and norm in crop_hints:
                    na["source_page"] = crop_hints[norm][0]["page_num"]
                    break

    return await persist_episode_understanding(
        db=db,
        episode=episode,
        understanding_dict=understanding_dict,
        raw_pages=raw_pages,
        split_raw_map=split_raw_map,
        crop_hints=crop_hints,
        target_status=target_status,
        authoritative_storyboard=authoritative_storyboard,
        crop_concurrency=max(2, eff_conc),
        progress_callback=_emit,
    )


async def persist_episode_understanding(
    db: AsyncSession,
    episode: Episode,
    understanding_dict: dict,
    raw_pages: dict[int, bytes] | None = None,
    split_raw_map: dict[str, bytes] | None = None,
    crop_hints: dict[str, list[dict[str, Any]]] | None = None,
    target_status: str | None = "understood",
    authoritative_storyboard: dict | None = None,
    crop_concurrency: int = 2,
    progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict:
    """Persist an EpisodeUnderstanding dict into Assets, AssetImages, Pits, Story Bible, and EpisodeMemory."""
    raw_pages = raw_pages or {}
    project = (await db.execute(select(Project).where(Project.id == episode.project_id).limit(1))).scalar_one_or_none()
    known_assets = (await db.execute(select(Asset).where(Asset.project_id == episode.project_id))).scalars().all()
    known_char_ids = {a.id for a in known_assets if a.type == "character"}

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

    # 3. 2-stage coarse-to-fine pixel-grid cropping + contact-sheet self-inspection + style guide
    if progress_callback and raw_pages:
        try:
            await progress_callback({"phase": "crop", "label": "Phase D 2阶段精裁与联系表自检", "episode_pct": 82})
        except Exception:
            pass
    await _auto_crop_asset_thumbnails(
        db,
        episode.id,
        discovered_pairs,
        understanding_dict.get("characters", []),
        matched_chars,
        raw_pages,
        split_raw_map=split_raw_map,
        crop_hints=crop_hints,
        prune_ungrounded_new_assets=bool(raw_pages and not authoritative_storyboard),
        crop_concurrency=crop_concurrency,
    )
    await _ensure_project_style_asset(
        db,
        episode.project_id,
        episode.id,
        understanding_dict.get("art_style_notes", ""),
        raw_pages,
    )

    if progress_callback:
        try:
            await progress_callback({"phase": "persist", "label": "写入角色档案、伏笔与故事圣经", "episode_pct": 95})
        except Exception:
            pass

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
