from __future__ import annotations

import base64
import logging
import re
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageStat

logger = logging.getLogger(__name__)

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
)

# Scanlation / non-story keywords that must never leak into story summaries, characters, or pits.
_SCANLATION_BLACKLIST = (
    "dead-chan",
    "deadchan",
    "stripease",
    "striptease",
    "discord.gg",
    "scanlation",
    "汉化组",
    "英化组",
    "招募翻译",
    "嵌字人员",
    "das unknown",
)

_GENERIC_EXTRA_NAMES = {
    "路人",
    "旁白",
    "群众",
    "村民",
    "护士",
    "医生",
    "黑影",
    "路过的小学生",
    "背景人物",
    "passerby",
    "passer-by",
    "narrator",
    "nurse",
    "crowd",
    "villager",
    "villagers",
}


def load_bold_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _encode_webp_with_banner(
    img: Image.Image,
    banner_label: str,
    *,
    max_w: int = 960,
    max_h: int = 1500,
    quality: int = 78,
) -> str:
    """Resize to crisp readable dimensions, stamp a 28px white header label on top, and WebP-encode."""
    rgb = img.convert("RGB")
    if rgb.width > max_w or rgb.height > max_h:
        rgb.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

    banner_h = 28
    canvas = Image.new("RGB", (rgb.width, rgb.height + banner_h), (255, 255, 255))
    canvas.paste(rgb, (0, banner_h))
    draw = ImageDraw.Draw(canvas)
    font = load_bold_font(18)
    draw.text((8, 4), banner_label, fill=(24, 24, 27), font=font)
    draw.line([(0, banner_h - 1), (rgb.width, banner_h - 1)], fill=(210, 210, 214), width=1)

    buf = BytesIO()
    canvas.save(buf, format="WEBP", quality=quality, method=4)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def encode_highres_page_webp(raw_bytes: bytes, label: str, *, max_w: int = 1360, max_h: int = 1960) -> str:
    """High-res single-page WebP encoding for zoomed agentic re-reading of dense/critical pages."""
    img = Image.open(BytesIO(raw_bytes))
    return _encode_webp_with_banner(img, f"{label} [HD]", max_w=max_w, max_h=max_h, quality=84)


def encode_reference_portrait_webp(raw_bytes: bytes, *, max_edge: int = 240, quality: int = 74) -> str:
    """Compact ~8KB WebP portrait encoding for character reference sheets."""
    try:
        img = Image.open(BytesIO(raw_bytes)).convert("RGB")
        if max(img.size) > max_edge:
            img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=quality, method=4)
        return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return "data:image/jpeg;base64," + base64.b64encode(raw_bytes).decode()


def prepare_manga_page_blocks(
    page_number: int,
    raw_bytes: bytes,
    object_key: str = "",
    *,
    rtl: bool = True,
    max_w: int = 768,
    max_h: int = 1200,
    quality: int = 75,
) -> tuple[list[tuple[str, str]], dict[str, bytes]]:
    """Preprocess one raw manga page into 1+ crisp WebP vision blocks with stamped headers.

    - Double-page spreads (w > h * 1.18 and w >= 1100) are split cleanly into Right and Left halves
      in reading order (R -> L for Japanese/Chinese RTL manga; L -> R for LTR comics).
    - Ultra-tall webtoon strips (h / w > 3.2 and h > 2200) are sliced vertically with 8% overlap.
    - Returns `(blocks, split_raw_map)` where `blocks` are `(label, data_url)` pairs.
    """
    _ = object_key
    blocks: list[tuple[str, str]] = []
    split_raw_map: dict[str, bytes] = {}
    try:
        img = Image.open(BytesIO(raw_bytes)).convert("RGB")
        w, h = img.size

        # 1. Double-page spread auto-split
        if h > 0 and w > int(h * 1.18) and w >= 1100:
            mid = w // 2
            left_im = img.crop((0, 0, mid, h))
            right_im = img.crop((mid, 0, w, h))
            ordered = (
                [(f"p{page_number:02d} R", right_im), (f"p{page_number:02d} L", left_im)]
                if rtl
                else [(f"p{page_number:02d} L", left_im), (f"p{page_number:02d} R", right_im)]
            )
            for lbl, half in ordered:
                blocks.append((lbl, _encode_webp_with_banner(half, lbl, max_w=max_w, max_h=max_h, quality=quality)))
                pbuf = BytesIO()
                half.save(pbuf, format="PNG")
                split_raw_map[lbl] = pbuf.getvalue()
            return blocks, split_raw_map

        # 2. Ultra-tall webtoon vertical strip slicing
        if w > 0 and h / w > 3.2 and h > 2200:
            slice_h = int(w * 2.1)
            overlap = int(slice_h * 0.08)
            step = max(400, slice_h - overlap)
            top = 0
            part = 1
            while top < h:
                bottom = min(h, top + slice_h)
                cropped = img.crop((0, top, w, bottom))
                lbl = f"p{page_number:02d} #{part}"
                blocks.append((lbl, _encode_webp_with_banner(cropped, lbl, max_w=max_w, max_h=max_h, quality=quality)))
                if bottom >= h:
                    break
                top += step
                part += 1
            return blocks, split_raw_map

        # 3. Standard single page
        lbl = f"p{page_number:02d}"
        blocks.append((lbl, _encode_webp_with_banner(img, lbl, max_w=max_w, max_h=max_h, quality=quality)))
        return blocks, split_raw_map
    except Exception:
        logger.warning("WebP page preprocessing failed for page %s, using fallback", page_number, exc_info=True)
        lbl = f"p{page_number:02d}"
        b64 = "data:image/jpeg;base64," + base64.b64encode(raw_bytes).decode()
        return [(lbl, b64)], split_raw_map


def render_pixel_grid(page_bytes: bytes, *, step: int = 100) -> tuple[bytes, int, int]:
    """Stage 1 coarse localization grid: RED vertical X lines (yellow labels) and
    CYAN horizontal Y lines (cyan labels) marked in TRUE ORIGINAL PIXEL coordinates."""
    im = Image.open(BytesIO(page_bytes)).convert("RGB")
    orig_w, orig_h = im.size
    ov = Image.new("RGBA", (orig_w, orig_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    font = load_bold_font(max(20, min(32, orig_w // 42)))

    for x in range(0, orig_w, step):
        major = x % (step * 2) == 0
        d.line([(x, 0), (x, orig_h)], fill=(255, 45, 45, 200 if major else 95), width=3 if major else 1)
        if major or orig_w <= 900:
            d.text((x + 3, 4), str(x), fill=(255, 240, 0, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))
            d.text(
                (x + 3, max(4, orig_h - 36)),
                str(x),
                fill=(255, 240, 0, 255),
                font=font,
                stroke_width=2,
                stroke_fill=(0, 0, 0, 255),
            )

    for y in range(0, orig_h, step):
        major = y % (step * 2) == 0
        d.line([(0, y), (orig_w, y)], fill=(0, 185, 255, 200 if major else 95), width=3 if major else 1)
        if major or orig_h <= 1200:
            d.text((4, y + 3), str(y), fill=(0, 255, 255, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))
            d.text(
                (max(4, orig_w - 72), y + 3),
                str(y),
                fill=(0, 255, 255, 255),
                font=font,
                stroke_width=2,
                stroke_fill=(0, 0, 0, 255),
            )

    out = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
    out.thumbnail((768, 1120), Image.Resampling.LANCZOS)
    buf = BytesIO()
    out.save(buf, format="WEBP", quality=82, method=4)
    return buf.getvalue(), orig_w, orig_h


def render_zoom_refinement_grid(
    page_bytes: bytes,
    rough_box: tuple[int, int, int, int],
    *,
    expand_ratio: float = 0.28,
    step: int = 50,
) -> tuple[bytes, tuple[int, int, int, int]]:
    """Stage 2 zoom refinement grid: expands Stage-1 rough box by `expand_ratio`, crops the
    zoomed sub-region, and draws a fine 50px red/cyan grid labeled in ORIGINAL page pixel coordinates."""
    im = Image.open(BytesIO(page_bytes)).convert("RGB")
    orig_w, orig_h = im.size
    rx0, ry0, rx1, ry1 = rough_box
    bw = max(60, rx1 - rx0)
    bh = max(60, ry1 - ry0)
    mx = max(50, int(bw * expand_ratio))
    my = max(50, int(bh * expand_ratio))
    zx0 = max(0, rx0 - mx)
    zy0 = max(0, ry0 - my)
    zx1 = min(orig_w, rx1 + mx)
    zy1 = min(orig_h, ry1 + my)

    sub = im.crop((zx0, zy0, zx1, zy1))
    sw, sh = sub.size
    ov = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    font = load_bold_font(max(14, min(22, sw // 28)))

    start_x = (zx0 // step) * step
    for x in range(start_x, zx1 + 1, step):
        if x < zx0:
            continue
        px = x - zx0
        major = x % 100 == 0
        d.line([(px, 0), (px, sh)], fill=(255, 45, 45, 225 if major else 105), width=2 if major else 1)
        if major:
            d.text((px + 2, 2), str(x), fill=(255, 240, 0, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))

    start_y = (zy0 // step) * step
    for y in range(start_y, zy1 + 1, step):
        if y < zy0:
            continue
        py = y - zy0
        major = y % 100 == 0
        d.line([(0, py), (sw, py)], fill=(0, 185, 255, 225 if major else 105), width=2 if major else 1)
        if major:
            d.text((2, py + 2), str(y), fill=(0, 255, 255, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))

    out = Image.alpha_composite(sub.convert("RGBA"), ov).convert("RGB")
    out.thumbnail((960, 960), Image.Resampling.LANCZOS)
    buf = BytesIO()
    out.save(buf, format="WEBP", quality=85, method=4)
    return buf.getvalue(), (zx0, zy0, zx1, zy1)


def is_meaningful_crop(cropped: Image.Image) -> bool:
    """Reject nearly blank white speech bubbles or solid dark sky patches."""
    gray = cropped.convert("L")
    stat = ImageStat.Stat(gray)
    stddev = stat.stddev[0] if stat.stddev else 0.0
    return stddev >= 22.0


def crop_pixel_box(
    page_bytes: bytes,
    box: tuple[int, int, int, int],
    *,
    pad_ratio: float = 0.0,
    square_portrait: bool = False,
    check_portrait_aspect: bool = False,
) -> bytes | None:
    """Crop an exact pixel box `(x0, y0, x1, y1)` from `page_bytes` with optional framing checks."""
    try:
        im = Image.open(BytesIO(page_bytes)).convert("RGB")
        w, h = im.size
        x0, y0, x1, y1 = [int(v) for v in box]
        x0, x1 = max(0, min(w, x0)), max(0, min(w, x1))
        y0, y1 = max(0, min(h, y0)), max(0, min(h, y1))
        if x1 <= x0 or y1 <= y0:
            return None
        bw, bh = x1 - x0, y1 - y0
        if bw < 48 or bh < 48:
            return None
        if square_portrait or check_portrait_aspect:
            aspect = bw / max(1.0, float(bh))
            if aspect < 0.45 or aspect > 2.3:
                return None

        if pad_ratio > 0:
            px = int(bw * pad_ratio)
            py = int(bh * pad_ratio)
            x0 = max(0, x0 - px)
            y0 = max(0, y0 - py)
            x1 = min(w, x1 + px)
            y1 = min(h, y1 + py)

        if square_portrait:
            cw, ch = x1 - x0, y1 - y0
            target_w = int(ch * 0.85)
            if cw < target_w:
                delta = (target_w - cw) // 2
                x0 = max(0, x0 - delta)
                x1 = min(w, x1 + delta)

        cropped = im.crop((x0, y0, x1, y1))
        if not is_meaningful_crop(cropped):
            return None
        if max(cropped.size) > 768:
            r = 768 / max(cropped.size)
            cropped = cropped.resize((round(cropped.width * r), round(cropped.height * r)), Image.Resampling.LANCZOS)
        buf = BytesIO()
        cropped.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        logger.debug("Pixel crop failed for box %s", box, exc_info=True)
        return None


def render_crop_contact_sheet(
    items: list[tuple[int, str, bytes]],
    *,
    cell: int = 320,
    cols: int = 3,
) -> bytes:
    """Render cropped assets into a labeled contact sheet (`#1 Name WxH`) for self-inspection."""
    if not items:
        return b""
    cols = max(1, min(cols, len(items)))
    rows = (len(items) + cols - 1) // cols
    pad = 12
    header_h = 28
    sheet = Image.new(
        "RGB",
        (cols * (cell + pad) + pad, rows * (cell + header_h + pad) + pad),
        (30, 30, 34),
    )
    draw = ImageDraw.Draw(sheet)
    font = load_bold_font(16)

    for idx, (num, label, raw_bytes) in enumerate(items):
        r, c = divmod(idx, cols)
        ox = pad + c * (cell + pad)
        oy = pad + r * (cell + header_h + pad)
        try:
            pil = Image.open(BytesIO(raw_bytes)).convert("RGB")
            orig_w, orig_h = pil.size
            thumb = pil.copy()
            thumb.thumbnail((cell, cell), Image.Resampling.LANCZOS)
            px = ox + (cell - thumb.width) // 2
            py = oy + header_h + (cell - thumb.height) // 2
            draw.rectangle([ox, oy + header_h, ox + cell, oy + header_h + cell], fill=(18, 18, 20))
            sheet.paste(thumb, (px, py))
            draw.rectangle([ox, oy, ox + cell, oy + header_h], fill=(45, 45, 50))
            draw.text((ox + 6, oy + 4), f"#{num} {label[:18]} ({orig_w}x{orig_h})", fill=(255, 240, 0), font=font)
        except Exception:
            continue

    buf = BytesIO()
    sheet.save(buf, format="WEBP", quality=82, method=4)
    return buf.getvalue()


def _contains_scanlation_noise(text: str | None) -> bool:
    low = (text or "").lower()
    return any(term in low for term in _SCANLATION_BLACKLIST)


def sanitize_understanding(
    data: dict[str, Any],
    *,
    valid_pages: set[int] | None = None,
    max_new_pits: int = 2,
) -> dict[str, Any]:
    """Deterministic post-validator inspired by omp's validate.py:
    removes scanlation leakage, unnamed generic extras, duplicate entities, and enforces pit limits."""
    out = dict(data)

    # 1. Clean characters
    clean_chars: list[dict] = []
    seen_char_keys: set[str] = set()
    for ch in out.get("characters") or []:
        name = str(ch.get("name") or "").strip()
        if not name or _contains_scanlation_noise(name) or name.lower() in _GENERIC_EXTRA_NAMES:
            continue
        norm = re.sub(r"[\s_\-·・（）()]+", "", name).lower()
        if not norm or norm in seen_char_keys:
            continue
        seen_char_keys.add(norm)
        item = dict(ch)
        item["aliases"] = [
            str(a).strip()
            for a in (item.get("aliases") or [])
            if str(a).strip()
            and not _contains_scanlation_noise(str(a))
            and str(a).strip() != name
            and not any(m in str(a) for m in ("的同学", "的小学同学", "的妈妈", "的爸爸", "的朋友", "的老师"))
        ]
        if valid_pages and item.get("source_page") is not None:
            try:
                sp = int(item["source_page"])
                if sp not in valid_pages:
                    item["source_page"] = None
            except (TypeError, ValueError):
                item["source_page"] = None
        clean_chars.append(item)
    out["characters"] = clean_chars

    # 2. Clean new_assets
    clean_assets: list[dict] = []
    seen_asset_keys: set[str] = set()
    for na in out.get("new_assets") or []:
        name = str(na.get("name") or "").strip()
        desc = str(na.get("description") or "").strip()
        atype = str(na.get("asset_type") or "item").strip().lower()
        if not name or _contains_scanlation_noise(name) or _contains_scanlation_noise(desc):
            continue
        if atype == "character" and name.lower() in _GENERIC_EXTRA_NAMES:
            continue
        norm = f"{atype}:{re.sub(r'[\\s_\\-·・（）()]+', '', name).lower()}"
        if norm in seen_asset_keys:
            continue
        seen_asset_keys.add(norm)
        item = dict(na)
        if valid_pages and item.get("source_page") is not None:
            try:
                sp = int(item["source_page"])
                if sp not in valid_pages:
                    item["source_page"] = None
            except (TypeError, ValueError):
                item["source_page"] = None
        clean_assets.append(item)
    out["new_assets"] = clean_assets

    # 3. Clean & cap pit_discoveries
    prio_rank = {"high": 0, "medium": 1, "low": 2}
    clean_pits: list[dict] = []
    seen_pit_sigs: set[str] = set()
    raw_pits = [
        p
        for p in (out.get("pit_discoveries") or [])
        if not _contains_scanlation_noise(p.get("title")) and not _contains_scanlation_noise(p.get("description"))
    ]
    raw_pits.sort(key=lambda p: prio_rank.get(str(p.get("priority") or "medium").lower(), 1))
    for p in raw_pits:
        sig = re.sub(r"[\s_\-·・（）()]+", "", str(p.get("title") or p.get("description", "")[:24])).lower()
        if not sig or sig in seen_pit_sigs:
            continue
        seen_pit_sigs.add(sig)
        clean_pits.append(p)
        if len(clean_pits) >= max_new_pits:
            break
    out["pit_discoveries"] = clean_pits

    # 4. Clean summary & events of scanlation mentions
    out["events"] = [
        e for e in (out.get("events") or []) if not _contains_scanlation_noise(e.get("description"))
    ]
    out["world_rules_discovered"] = [
        r for r in (out.get("world_rules_discovered") or []) if r and not _contains_scanlation_noise(str(r))
    ]
    return out
