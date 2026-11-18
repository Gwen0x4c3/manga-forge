from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

CJK_REGULAR_FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]

CJK_BOLD_FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


class FontManager:
    _cache: dict[str, ImageFont.FreeTypeFont]

    def __init__(self, default_size: int = 50) -> None:
        self._cache = {}
        self._default_size = default_size
        self._regular_path = self._find_font(CJK_REGULAR_FONT_PATHS)
        self._bold_path = self._find_font(CJK_BOLD_FONT_PATHS) or self._regular_path

    @staticmethod
    def _find_font(paths: list[str]) -> str | None:
        for path in paths:
            if os.path.isfile(path):
                return path
        return None

    def get_font(self, size: int | None = None, bold: bool = False) -> ImageFont.FreeTypeFont:
        actual_size = size or self._default_size
        key = f"{actual_size}_{bold}"
        if key in self._cache:
            return self._cache[key]
        font = self._load_font(actual_size, bold)
        self._cache[key] = font
        return font

    def _load_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        target_path = self._bold_path if bold else self._regular_path
        if target_path:
            try:
                return ImageFont.truetype(target_path, size, index=0)
            except Exception:
                pass
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


@dataclass
class PanelImage:
    image_data: bytes
    panel_id: str
    dialogues: list[dict] = field(default_factory=list)
    position_hint: str = "center"
    face_zones: list[dict] = field(default_factory=list)


@dataclass
class ComposedPage:
    image_data: bytes
    page_number: int
    layout: str


# Default corner rotation so multiple dialogue bubbles in a panel don't stack on top of faces.
_CORNER_ROTATION = ("top-right", "top-left", "bottom-right", "bottom-left")


class LayoutEngine:
    PAGE_WIDTH: int = 2480
    PAGE_HEIGHT: int = 3508
    GAP: int = 36
    MARGIN: int = 64
    FOOTER_HEIGHT: int = 52
    PANEL_BORDER_WIDTH: int = 5
    BUBBLE_MAX_WIDTH_RATIO: float = 0.48
    BUBBLE_PADDING_X: int = 26
    BUBBLE_PADDING_Y: int = 20
    OUTLINE_WIDTH: int = 4
    DEFAULT_FONT_SIZE: int = 48

    def __init__(self) -> None:
        self._font_manager = FontManager(default_size=self.DEFAULT_FONT_SIZE)

    def compose_page(self, layout: str, panels: list[PanelImage], page_number: int) -> ComposedPage:
        canvas = Image.new("RGBA", (self.PAGE_WIDTH, self.PAGE_HEIGHT), (255, 255, 255, 255))
        if not panels:
            rgb = canvas.convert("RGB")
            buf = io.BytesIO()
            rgb.save(buf, format="PNG", optimize=True)
            return ComposedPage(image_data=buf.getvalue(), page_number=page_number, layout=layout)

        bounding_boxes = self._apply_layout(layout, len(panels))
        draw = ImageDraw.Draw(canvas)

        for panel, (px, py, pw, ph) in zip(panels, bounding_boxes):
            panel_img = Image.open(io.BytesIO(panel.image_data)).convert("RGB")
            fitted = self._fit_image_to_area(panel_img, pw, ph)
            canvas.paste(fitted, (px, py))

            # Crisp manga ink border around each panel
            draw.rectangle(
                [px, py, px + pw - 1, py + ph - 1],
                outline=(18, 18, 22, 255),
                width=self.PANEL_BORDER_WIDTH,
            )

            if panel.dialogues:
                self._render_panel_dialogues(canvas, panel, px, py, pw, ph)
                draw = ImageDraw.Draw(canvas)

        # Subtle manga page number in footer
        folio_font = self._font_manager.get_font(size=32, bold=False)
        folio_text = f"— {page_number} —"
        fb = folio_font.getbbox(folio_text)
        fw = fb[2] - fb[0]
        draw.text(
            ((self.PAGE_WIDTH - fw) // 2, self.PAGE_HEIGHT - self.MARGIN + 10),
            folio_text,
            fill=(110, 110, 120, 255),
            font=folio_font,
        )

        rgb = canvas.convert("RGB")
        buf = io.BytesIO()
        rgb.save(buf, format="PNG", optimize=True)
        return ComposedPage(image_data=buf.getvalue(), page_number=page_number, layout=layout)

    def _render_panel_dialogues(
        self,
        canvas: Image.Image,
        panel: PanelImage,
        px: int,
        py: int,
        pw: int,
        ph: int,
    ) -> None:
        """Place speech/thought/narration/sfx bubbles cleanly inside panel corners without overlapping."""
        # Adapt font size slightly for compact panels
        scale = min(1.0, max(0.72, min(pw / 950.0, ph / 850.0)))
        base_font_size = max(34, int(self.DEFAULT_FONT_SIZE * scale))
        max_bubble_w = max(280, min(int(pw * self.BUBBLE_MAX_WIDTH_RATIO), pw - 48))

        placed_rects: list[tuple[int, int, int, int]] = []
        valid_dialogues = [d for d in panel.dialogues if (d.get("text") or "").strip()]

        for idx, dialogue in enumerate(valid_dialogues):
            text = str(dialogue.get("text", "")).strip()
            bubble_type = str(dialogue.get("type", "speech")).lower()
            raw_hint = str(dialogue.get("speaker_position") or "").strip().lower()
            if not raw_hint or raw_hint == "center":
                if bubble_type == "narration":
                    speaker_position = "top-left" if idx == 0 else "bottom-left"
                elif bubble_type == "sfx":
                    speaker_position = "bottom-right"
                else:
                    speaker_position = _CORNER_ROTATION[idx % len(_CORNER_ROTATION)]
            else:
                speaker_position = raw_hint

            if bubble_type == "sfx":
                font = self._font_manager.get_font(size=int(base_font_size * 1.28), bold=True)
            elif bubble_type == "narration":
                font = self._font_manager.get_font(size=max(32, int(base_font_size * 0.92)), bold=False)
            else:
                font = self._font_manager.get_font(size=base_font_size, bold=False)

            inner_max_w = max(160, max_bubble_w - 2 * self.BUBBLE_PADDING_X)
            lines = self._wrap_text(text, font, inner_max_w)
            bubble_w, bubble_h = self._measure_bubble(lines, font)

            # Clamp bubble dimensions to fit panel
            bubble_w = min(bubble_w, pw - 36)
            bubble_h = min(bubble_h, ph - 36)

            bx, by = self._place_bubble_in_panel(
                speaker_position, px, py, pw, ph, bubble_w, bubble_h, placed_rects, panel.face_zones
            )
            placed_rects.append((bx, by, bubble_w, bubble_h))

            self._draw_bubble_on_canvas(
                canvas,
                lines=lines,
                x=bx,
                y=by,
                bubble_w=bubble_w,
                bubble_h=bubble_h,
                bubble_type=bubble_type,
                position_hint=speaker_position,
                font=font,
                speaker=str(dialogue.get("speaker") or "").strip(),
            )

    def _place_bubble_in_panel(
        self,
        hint: str,
        px: int,
        py: int,
        pw: int,
        ph: int,
        bw: int,
        bh: int,
        placed: list[tuple[int, int, int, int]],
        face_zones: list[dict],
    ) -> tuple[int, int]:
        pad = 22
        tail_margin = 22

        # Candidate anchor positions inside the panel
        left_x = px + pad
        right_x = max(px + pad, px + pw - bw - pad)
        center_x = px + max(pad, (pw - bw) // 2)
        top_y = py + pad
        bottom_y = max(py + pad, py + ph - bh - pad - tail_margin)

        anchor_map = {
            "right": (right_x, top_y),
            "left": (left_x, top_y),
            "top-right": (right_x, top_y),
            "top-left": (left_x, top_y),
            "bottom-right": (right_x, bottom_y),
            "bottom-left": (left_x, bottom_y),
            "top-center": (center_x, top_y),
            "bottom-center": (center_x, bottom_y),
        }
        bx, by = anchor_map.get(hint, (right_x, top_y))

        # Shift vertically if colliding with an already-placed bubble in the same panel
        for _ in range(6):
            collision = next(
                (r for r in placed if self._rects_overlap(bx, by, bw, bh + 16, r[0], r[1], r[2], r[3] + 16)),
                None,
            )
            if not collision:
                break
            _, ry, _, rh = collision
            if "bottom" in hint:
                by = ry - bh - 20
            else:
                by = ry + rh + 24

        # Avoid annotated face zones if provided
        bx, by = self._avoid_faces(bx, by, bw, bh, face_zones)

        # Strict clamp inside panel bounds
        bx = max(px + 14, min(bx, px + pw - bw - 14))
        by = max(py + 14, min(by, py + ph - bh - 18))
        return bx, by

    def compose_episode(self, pages_data: list[dict]) -> list[ComposedPage]:
        results: list[ComposedPage] = []
        for page_info in pages_data:
            layout = page_info.get("layout", "2x2")
            panels = [
                PanelImage(
                    image_data=p["image_data"],
                    panel_id=p["panel_id"],
                    dialogues=p.get("dialogues", []),
                    position_hint=p.get("position_hint", "center"),
                    face_zones=p.get("face_zones", []),
                )
                for p in page_info.get("panels", [])
            ]
            page_number = page_info.get("page_number", 1)
            results.append(self.compose_page(layout, panels, page_number))
        return results

    def _apply_layout(self, layout: str, num_panels: int) -> list[tuple[int, int, int, int]]:
        """Compute exact panel bounding boxes matching `num_panels` so panels are never dropped."""
        mg = self.MARGIN
        gp = self.GAP
        x0 = mg
        y0 = mg
        usable_w = self.PAGE_WIDTH - 2 * mg
        usable_h = self.PAGE_HEIGHT - 2 * mg - self.FOOTER_HEIGHT

        if num_panels <= 1:
            return [(x0, y0, usable_w, usable_h)]

        if num_panels == 2:
            if layout in ("2_horizontal", "2x1"):
                half_w = (usable_w - gp) // 2
                return [
                    (x0, y0, half_w, usable_h),
                    (x0 + half_w + gp, y0, usable_w - half_w - gp, usable_h),
                ]
            if layout == "2_cinematic":
                top_h = int(usable_h * 0.42) - gp // 2
                return [
                    (x0, y0, usable_w, top_h),
                    (x0, y0 + top_h + gp, usable_w, usable_h - top_h - gp),
                ]
            half_h = (usable_h - gp) // 2
            return [
                (x0, y0, usable_w, half_h),
                (x0, y0 + half_h + gp, usable_w, usable_h - half_h - gp),
            ]

        if num_panels == 3:
            if layout in ("3_vertical", "3-vertical", "3-stack", "3_stack", "1x3"):
                row_h = (usable_h - 2 * gp) // 3
                return [
                    (x0, y0, usable_w, row_h),
                    (x0, y0 + row_h + gp, usable_w, row_h),
                    (x0, y0 + 2 * (row_h + gp), usable_w, usable_h - 2 * (row_h + gp)),
                ]
            # Classic manga 3-panel: wide dramatic top + 2 bottom reaction/action panels
            top_h = int(usable_h * 0.52) - gp // 2
            bot_h = usable_h - top_h - gp
            half_w = (usable_w - gp) // 2
            return [
                (x0, y0, usable_w, top_h),
                (x0, y0 + top_h + gp, half_w, bot_h),
                (x0 + half_w + gp, y0 + top_h + gp, usable_w - half_w - gp, bot_h),
            ]

        if num_panels == 4:
            if layout == "4_manga_dynamic":
                # Row 1: wide top; Row 2: 2 asymmetric middle panels; Row 3: wide bottom
                h1 = int(usable_h * 0.28)
                h2 = int(usable_h * 0.40)
                h3 = usable_h - h1 - h2 - 2 * gp
                w_left = int(usable_w * 0.56) - gp // 2
                w_right = usable_w - w_left - gp
                return [
                    (x0, y0, usable_w, h1),
                    (x0, y0 + h1 + gp, w_left, h2),
                    (x0 + w_left + gp, y0 + h1 + gp, w_right, h2),
                    (x0, y0 + h1 + h2 + 2 * gp, usable_w, h3),
                ]
            # Clean 2x2 grid (with slight manga proportion: 48% top, 52% bottom)
            top_h = int(usable_h * 0.48) - gp // 2
            bot_h = usable_h - top_h - gp
            left_w = (usable_w - gp) // 2
            right_w = usable_w - left_w - gp
            return [
                (x0, y0, left_w, top_h),
                (x0 + left_w + gp, y0, right_w, top_h),
                (x0, y0 + top_h + gp, left_w, bot_h),
                (x0 + left_w + gp, y0 + top_h + gp, right_w, bot_h),
            ]

        if num_panels == 5:
            # Classic 5-panel manga page: 2 top + 1 wide cinematic middle + 2 bottom
            h1 = int(usable_h * 0.32)
            h2 = int(usable_h * 0.32)
            h3 = usable_h - h1 - h2 - 2 * gp
            w_top_l = int(usable_w * 0.55) - gp // 2
            w_top_r = usable_w - w_top_l - gp
            w_bot_l = int(usable_w * 0.45) - gp // 2
            w_bot_r = usable_w - w_bot_l - gp
            return [
                (x0, y0, w_top_l, h1),
                (x0 + w_top_l + gp, y0, w_top_r, h1),
                (x0, y0 + h1 + gp, usable_w, h2),
                (x0, y0 + h1 + h2 + 2 * gp, w_bot_l, h3),
                (x0 + w_bot_l + gp, y0 + h1 + h2 + 2 * gp, w_bot_r, h3),
            ]

        if num_panels == 6:
            # 3 rows x 2 columns manga grid
            row_h = (usable_h - 2 * gp) // 3
            last_h = usable_h - 2 * (row_h + gp)
            half_w = (usable_w - gp) // 2
            right_w = usable_w - half_w - gp
            boxes: list[tuple[int, int, int, int]] = []
            for r_idx in range(3):
                ry = y0 + r_idx * (row_h + gp)
                rh = last_h if r_idx == 2 else row_h
                boxes.append((x0, ry, half_w, rh))
                boxes.append((x0 + half_w + gp, ry, right_w, rh))
            return boxes

        # Fallback for 7+ panels: dynamic 2-column grid covering all panels
        rows = (num_panels + 1) // 2
        row_h = (usable_h - (rows - 1) * gp) // rows
        boxes = []
        idx = 0
        for r_idx in range(rows):
            ry = y0 + r_idx * (row_h + gp)
            rh = (usable_h - r_idx * (row_h + gp)) if r_idx == rows - 1 else row_h
            remaining = num_panels - idx
            if remaining == 1:
                boxes.append((x0, ry, usable_w, rh))
                idx += 1
            else:
                half_w = (usable_w - gp) // 2
                boxes.append((x0, ry, half_w, rh))
                boxes.append((x0 + half_w + gp, ry, usable_w - half_w - gp, rh))
                idx += 2
        return boxes

    def _fit_image_to_area(self, img: Image.Image, width: int, height: int) -> Image.Image:
        img_ratio = img.width / img.height
        area_ratio = width / height

        if img_ratio > area_ratio:
            new_h = height
            new_w = max(width, int(height * img_ratio))
        else:
            new_w = width
            new_h = max(height, int(width / img_ratio))

        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = max(0, (new_w - width) // 2)
        top = max(0, int((new_h - height) * 0.35))  # bias slightly upward to preserve heads/faces
        return resized.crop((left, top, left + width, top + height))

    def _draw_bubble_on_canvas(
        self,
        canvas: Image.Image,
        lines: list[str],
        x: int,
        y: int,
        bubble_w: int,
        bubble_h: int,
        bubble_type: str,
        position_hint: str,
        font: ImageFont.FreeTypeFont,
        speaker: str = "",
    ) -> None:
        if bubble_type == "narration":
            self._draw_narration_bubble(canvas, lines, x, y, bubble_w, bubble_h, font)
        elif bubble_type == "thought":
            self._draw_thought_bubble(canvas, lines, x, y, bubble_w, bubble_h, position_hint, font)
        elif bubble_type == "sfx":
            draw = ImageDraw.Draw(canvas)
            self._draw_sfx_text(draw, lines, x, y, bubble_w, bubble_h, font)
        else:
            self._draw_speech_bubble(canvas, lines, x, y, bubble_w, bubble_h, position_hint, font)

    def _draw_speech_bubble(
        self,
        canvas: Image.Image,
        lines: list[str],
        x: int,
        y: int,
        bubble_w: int,
        bubble_h: int,
        position_hint: str,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        """Draw unified speech balloon + tail without a seam line across the tail base."""
        pad = 36
        layer = Image.new("RGBA", (bubble_w + 2 * pad, bubble_h + 2 * pad), (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer)
        bx, by = pad, pad
        radius = min(38, bubble_h // 2, bubble_w // 2)
        ow = self.OUTLINE_WIDTH

        tail_len = 20
        tail_half = 12
        pointing_up = "bottom" in position_hint
        if "left" in position_hint:
            tx = bx + max(radius + 10, bubble_w // 3)
            tip_dx = 10
        elif "right" in position_hint:
            tx = bx + min(bubble_w - radius - 10, (2 * bubble_w) // 3)
            tip_dx = -10
        else:
            tx = bx + bubble_w // 2
            tip_dx = 0

        if pointing_up:
            outer_tail = [
                (tx - tail_half - ow, by + ow),
                (tx + tail_half + ow, by + ow),
                (tx + tip_dx, by - tail_len - ow),
            ]
            inner_tail = [
                (tx - tail_half, by + ow + 2),
                (tx + tail_half, by + ow + 2),
                (tx + tip_dx, by - tail_len + 2),
            ]
        else:
            base_y = by + bubble_h
            outer_tail = [
                (tx - tail_half - ow, base_y - ow),
                (tx + tail_half + ow, base_y - ow),
                (tx + tip_dx, base_y + tail_len + ow),
            ]
            inner_tail = [
                (tx - tail_half, base_y - ow - 2),
                (tx + tail_half, base_y - ow - 2),
                (tx + tip_dx, base_y + tail_len - 2),
            ]

        # Pass 1: outer black stroke shape (balloon + tail)
        ldraw.rounded_rectangle(
            [bx - ow, by - ow, bx + bubble_w + ow, by + bubble_h + ow],
            radius=radius + ow,
            fill=(20, 20, 25, 250),
        )
        ldraw.polygon(outer_tail, fill=(20, 20, 25, 250))

        # Pass 2: inner crisp white fill (balloon + tail merged seamlessly)
        ldraw.rounded_rectangle(
            [bx, by, bx + bubble_w, by + bubble_h],
            radius=radius,
            fill=(255, 255, 255, 246),
        )
        ldraw.polygon(inner_tail, fill=(255, 255, 255, 246))

        self._draw_text_lines(ldraw, lines, bx, by, bubble_w, bubble_h, font)
        canvas.alpha_composite(layer, (max(0, x - pad), max(0, y - pad)))

    def _draw_thought_bubble(
        self,
        canvas: Image.Image,
        lines: list[str],
        x: int,
        y: int,
        bubble_w: int,
        bubble_h: int,
        position_hint: str,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        pad = 44
        layer = Image.new("RGBA", (bubble_w + 2 * pad, bubble_h + 2 * pad), (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer)
        bx, by = pad, pad
        radius = min(44, bubble_h // 2)

        ldraw.rounded_rectangle(
            [bx, by, bx + bubble_w, by + bubble_h],
            radius=radius,
            fill=(255, 255, 255, 242),
            outline=(35, 35, 45, 255),
            width=3,
        )
        # Inner subtle ring for classic manga thought feel
        ldraw.rounded_rectangle(
            [bx + 6, by + 6, bx + bubble_w - 6, by + bubble_h - 6],
            radius=max(12, radius - 6),
            outline=(170, 175, 190, 220),
            width=2,
        )

        tx = bx + bubble_w // 2
        ty = by - 14 if "bottom" in position_hint else by + bubble_h + 8
        step = -18 if "bottom" in position_hint else 18
        ldraw.ellipse([tx - 10, ty, tx + 10, ty + 16], fill=(255, 255, 255, 245), outline=(35, 35, 45, 255), width=3)
        ldraw.ellipse(
            [tx - 6, ty + step, tx + 6, ty + step + 11], fill=(255, 255, 255, 245), outline=(35, 35, 45, 255), width=2
        )

        self._draw_text_lines(ldraw, lines, bx, by, bubble_w, bubble_h, font)
        canvas.alpha_composite(layer, (max(0, x - pad), max(0, y - pad)))

    def _draw_narration_bubble(
        self,
        canvas: Image.Image,
        lines: list[str],
        x: int,
        y: int,
        bubble_w: int,
        bubble_h: int,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        layer = Image.new("RGBA", (bubble_w, bubble_h), (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer)
        ldraw.rectangle(
            [0, 0, bubble_w - 1, bubble_h - 1],
            fill=(252, 250, 242, 236),
            outline=(20, 20, 25, 255),
            width=4,
        )
        ldraw.rectangle(
            [7, 7, bubble_w - 8, bubble_h - 8],
            outline=(90, 90, 100, 180),
            width=1,
        )
        self._draw_text_lines(ldraw, lines, 0, 0, bubble_w, bubble_h, font)
        canvas.alpha_composite(layer, (x, y))

    def _draw_sfx_text(
        self,
        draw: ImageDraw.Draw,
        lines: list[str],
        x: int,
        y: int,
        bubble_w: int,
        bubble_h: int,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        text_x = x + self.BUBBLE_PADDING_X
        text_y = y + self.BUBBLE_PADDING_Y
        outline_color = (15, 15, 20, 255)
        fill_color = (255, 255, 255, 255)
        outline_width = 6
        for line in lines:
            bbox = font.getbbox(line)
            line_h = bbox[3] - bbox[1]
            for dx in range(-outline_width, outline_width + 1, 2):
                for dy in range(-outline_width, outline_width + 1, 2):
                    if dx * dx + dy * dy <= outline_width * outline_width:
                        draw.text((text_x + dx, text_y + dy), line, fill=outline_color, font=font)
            draw.text((text_x, text_y), line, fill=fill_color, font=font)
            text_y += line_h + 10

    def _draw_text_lines(
        self,
        draw: ImageDraw.Draw,
        lines: list[str],
        bubble_x: int,
        bubble_y: int,
        bubble_w: int,
        bubble_h: int,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        if not lines:
            return
        line_metrics = []
        for line in lines:
            bbox = font.getbbox(line)
            line_metrics.append((line, bbox[2] - bbox[0], bbox[3] - bbox[1], bbox[1]))

        line_gap = 10
        total_h = sum(m[2] for m in line_metrics) + line_gap * (len(line_metrics) - 1)
        cur_y = bubble_y + max(self.BUBBLE_PADDING_Y - 4, (bubble_h - total_h) // 2)

        for line, lw, lh, y_offset in line_metrics:
            cur_x = bubble_x + max(self.BUBBLE_PADDING_X - 4, (bubble_w - lw) // 2)
            draw.text((cur_x, cur_y - y_offset), line, fill=(18, 18, 22, 255), font=font)
            cur_y += lh + line_gap

    def _avoid_faces(
        self,
        bx: int,
        by: int,
        bw: int,
        bh: int,
        face_zones: list[dict],
    ) -> tuple[int, int]:
        if not face_zones:
            return bx, by
        for fz in face_zones:
            fx, fy = fz.get("x", 0), fz.get("y", 0)
            fw, fh = fz.get("w", 0), fz.get("h", 0)
            if self._rects_overlap(bx, by, bw, bh, fx, fy, fw, fh):
                shifts = [
                    (0, -(bh + 12)),
                    (0, fh + 12),
                    (-(bw + 12), 0),
                    (fw + 12),
                ]
                for shift in shifts:
                    if isinstance(shift, tuple):
                        dx, dy = shift
                    else:
                        dx, dy = shift, 0
                    nx, ny = bx + dx, by + dy
                    if not self._rects_overlap(nx, ny, bw, bh, fx, fy, fw, fh):
                        return nx, ny
        return bx, by

    def _rects_overlap(
        self,
        ax: int,
        ay: int,
        aw: int,
        ah: int,
        bx: int,
        by: int,
        bw: int,
        bh: int,
    ) -> bool:
        return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
        if max_width <= 0:
            return [text]

        lines: list[str] = []
        for paragraph in text.splitlines() or [text]:
            current_line = ""
            for char in paragraph:
                test_line = current_line + char
                bbox = font.getbbox(test_line)
                line_w = bbox[2] - bbox[0]
                if line_w > max_width and current_line:
                    lines.append(current_line)
                    current_line = char
                else:
                    current_line = test_line
            if current_line:
                lines.append(current_line)
        return lines

    def _measure_bubble(self, lines: list[str], font: ImageFont.FreeTypeFont) -> tuple[int, int]:
        if not lines:
            return (2 * self.BUBBLE_PADDING_X + 16, 2 * self.BUBBLE_PADDING_Y + 16)

        line_widths: list[int] = []
        line_heights: list[int] = []
        for line in lines:
            bbox = font.getbbox(line)
            line_widths.append(bbox[2] - bbox[0])
            line_heights.append(bbox[3] - bbox[1])

        text_w = max(line_widths)
        text_h = sum(line_heights) + 10 * (len(lines) - 1)
        return (text_w + 2 * self.BUBBLE_PADDING_X, text_h + 2 * self.BUBBLE_PADDING_Y)
