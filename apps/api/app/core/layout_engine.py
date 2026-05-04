from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont


CJK_FONT_PATHS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


class FontManager:
    _cache: dict[str, ImageFont.FreeTypeFont]

    def __init__(self, default_size: int = 28) -> None:
        self._cache = {}
        self._default_size = default_size
        self._cjk_path = self._find_cjk_font()

    def _find_cjk_font(self) -> str | None:
        for path in CJK_FONT_PATHS:
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
        if self._cjk_path:
            try:
                return ImageFont.truetype(self._cjk_path, size, index=0)
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


class LayoutEngine:
    PAGE_WIDTH: int = 2480
    PAGE_HEIGHT: int = 3508
    GAP: int = 8
    MARGIN: int = 16
    BUBBLE_MAX_WIDTH_RATIO: float = 0.6
    BUBBLE_PADDING: int = 8
    OUTLINE_WIDTH: int = 2
    DEFAULT_FONT_SIZE: int = 28

    def __init__(self) -> None:
        self._font_manager = FontManager(default_size=self.DEFAULT_FONT_SIZE)

    def compose_page(self, layout: str, panels: list[PanelImage], page_number: int) -> ComposedPage:
        canvas = Image.new("RGB", (self.PAGE_WIDTH, self.PAGE_HEIGHT), (255, 255, 255))
        bounding_boxes = self._apply_layout(layout, len(panels))

        for panel, (px, py, pw, ph) in zip(panels, bounding_boxes):
            panel_img = Image.open(io.BytesIO(panel.image_data))
            fitted = self._fit_image_to_area(panel_img, pw, ph)
            canvas.paste(fitted, (px, py))

            if panel.dialogues:
                draw = ImageDraw.Draw(canvas)
                max_bubble_w = int(pw * self.BUBBLE_MAX_WIDTH_RATIO)
                bubble_y = py + 16
                for dialogue in panel.dialogues:
                    text = dialogue.get("text", "")
                    if not text:
                        continue
                    bubble_type = dialogue.get("type", "speech")
                    speaker_position = dialogue.get("speaker_position", panel.position_hint)
                    font = self._font_manager.get_font()
                    if bubble_type == "sfx":
                        font = self._font_manager.get_font(size=self.DEFAULT_FONT_SIZE + 8, bold=True)
                    lines = self._wrap_text(text, font, max_bubble_w - 2 * self.BUBBLE_PADDING)
                    bubble_w, bubble_h = self._measure_bubble(lines, font)
                    bubble_x = self._resolve_bubble_x(speaker_position, px, pw, bubble_w)
                    bubble_x, bubble_y = self._avoid_faces(
                        bubble_x, bubble_y, bubble_w, bubble_h, panel.face_zones
                    )
                    self._draw_bubble(
                        draw, text, bubble_x, bubble_y, max_bubble_w,
                        bubble_type, speaker_position, font,
                    )
                    bubble_y += bubble_h + 12

        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        return ComposedPage(image_data=buf.getvalue(), page_number=page_number, layout=layout)

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
        pw, ph, gp, mg = self.PAGE_WIDTH, self.PAGE_HEIGHT, self.GAP, self.MARGIN

        if layout in ("1x1", "splash"):
            return [(mg, mg, pw - 2 * mg, ph - 2 * mg)]

        if layout in ("2x2", "4_panels"):
            half_w = (pw - gp) // 2
            half_h = (ph - gp) // 2
            return [
                (0, 0, half_w, half_h),
                (half_w + gp, 0, pw - half_w - gp, half_h),
                (0, half_h + gp, half_w, ph - half_h - gp),
                (half_w + gp, half_h + gp, pw - half_w - gp, ph - half_h - gp),
            ]

        if layout == "3_panels":
            top_h = int(ph * 0.6) - gp // 2
            bottom_h = ph - top_h - gp
            half_w = (pw - gp) // 2
            return [
                (0, 0, pw, top_h),
                (0, top_h + gp, half_w, bottom_h),
                (half_w + gp, top_h + gp, pw - half_w - gp, bottom_h),
            ]

        return [(mg, mg, pw - 2 * mg, ph - 2 * mg)]

    def _fit_image_to_area(self, img: Image.Image, width: int, height: int) -> Image.Image:
        img_ratio = img.width / img.height
        area_ratio = width / height

        if img_ratio > area_ratio:
            new_h = height
            new_w = int(height * img_ratio)
        else:
            new_w = width
            new_h = int(width / img_ratio)

        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - width) // 2
        top = (new_h - height) // 2
        return resized.crop((left, top, left + width, top + height))

    def _draw_bubble(
        self,
        draw: ImageDraw.Draw,
        text: str,
        x: int,
        y: int,
        max_width: int,
        bubble_type: str = "speech",
        position_hint: str = "center",
        font: ImageFont.FreeTypeFont | None = None,
    ) -> None:
        if font is None:
            font = self._font_manager.get_font()
        lines = self._wrap_text(text, font, max_width - 2 * self.BUBBLE_PADDING)
        bubble_w, bubble_h = self._measure_bubble(lines, font)

        if bubble_type == "speech":
            self._draw_speech_bubble(draw, lines, x, y, bubble_w, bubble_h, position_hint, font)
        elif bubble_type == "thought":
            self._draw_thought_bubble(draw, lines, x, y, bubble_w, bubble_h, position_hint, font)
        elif bubble_type == "narration":
            self._draw_narration_bubble(draw, lines, x, y, bubble_w, bubble_h, font)
        elif bubble_type == "sfx":
            self._draw_sfx_text(draw, lines, x, y, bubble_w, bubble_h, font)
        else:
            self._draw_speech_bubble(draw, lines, x, y, bubble_w, bubble_h, position_hint, font)

    def _draw_speech_bubble(
        self,
        draw: ImageDraw.Draw,
        lines: list[str],
        x: int,
        y: int,
        bubble_w: int,
        bubble_h: int,
        position_hint: str,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        radius = 16
        draw.rounded_rectangle(
            [x, y, x + bubble_w, y + bubble_h],
            radius=radius,
            fill=(255, 255, 255),
            outline=(0, 0, 0),
            width=self.OUTLINE_WIDTH,
        )

        tail_size = 14
        tail_x, tail_y = self._compute_tail_anchor(position_hint, x, y, bubble_w, bubble_h)

        if position_hint in ("top-left", "bottom-left"):
            tail_pts = [
                (tail_x - tail_size // 2, tail_y),
                (tail_x + tail_size // 2, tail_y),
                (tail_x - tail_size, tail_y + tail_size),
            ]
        elif position_hint in ("top-right", "bottom-right"):
            tail_pts = [
                (tail_x - tail_size // 2, tail_y),
                (tail_x + tail_size // 2, tail_y),
                (tail_x + tail_size, tail_y + tail_size),
            ]
        elif position_hint == "top-center":
            tail_pts = [
                (tail_x - tail_size // 2, tail_y),
                (tail_x + tail_size // 2, tail_y),
                (tail_x, tail_y + tail_size),
            ]
        elif position_hint == "bottom-center":
            tail_pts = [
                (tail_x - tail_size // 2, y),
                (tail_x + tail_size // 2, y),
                (tail_x, y - tail_size),
            ]
        else:
            tail_pts = [
                (tail_x - tail_size // 2, tail_y),
                (tail_x + tail_size // 2, tail_y),
                (tail_x, tail_y + tail_size),
            ]

        draw.polygon(tail_pts, fill=(255, 255, 255), outline=(0, 0, 0))
        self._draw_text_lines(draw, lines, x, y, font)

    def _draw_thought_bubble(
        self,
        draw: ImageDraw.Draw,
        lines: list[str],
        x: int,
        y: int,
        bubble_w: int,
        bubble_h: int,
        position_hint: str,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        radius = 20
        draw.rounded_rectangle(
            [x, y, x + bubble_w, y + bubble_h],
            radius=radius,
            fill=(255, 255, 255),
            outline=(0, 0, 0),
            width=self.OUTLINE_WIDTH,
        )

        tail_x, tail_y = self._compute_tail_anchor(position_hint, x, y, bubble_w, bubble_h)
        small_r = 5
        mid_r = 8

        if position_hint in ("top-left", "bottom-left", "top-right", "bottom-right", "top-center"):
            draw.ellipse(
                [tail_x - mid_r, tail_y + 4, tail_x + mid_r, tail_y + 4 + 2 * mid_r],
                fill=(255, 255, 255), outline=(0, 0, 0), width=self.OUTLINE_WIDTH,
            )
            offset_x = -6 if "left" in position_hint else (6 if "right" in position_hint else 0)
            draw.ellipse(
                [
                    tail_x + offset_x - small_r,
                    tail_y + 4 + 2 * mid_r + 4,
                    tail_x + offset_x + small_r,
                    tail_y + 4 + 2 * mid_r + 4 + 2 * small_r,
                ],
                fill=(255, 255, 255), outline=(0, 0, 0), width=self.OUTLINE_WIDTH,
            )
        elif position_hint == "bottom-center":
            draw.ellipse(
                [tail_x - mid_r, tail_y - 4 - 2 * mid_r, tail_x + mid_r, tail_y - 4],
                fill=(255, 255, 255), outline=(0, 0, 0), width=self.OUTLINE_WIDTH,
            )
            draw.ellipse(
                [
                    tail_x - small_r,
                    tail_y - 4 - 2 * mid_r - 4 - 2 * small_r,
                    tail_x + small_r,
                    tail_y - 4 - 2 * mid_r - 4,
                ],
                fill=(255, 255, 255), outline=(0, 0, 0), width=self.OUTLINE_WIDTH,
            )
        else:
            draw.ellipse(
                [tail_x - mid_r, tail_y + 4, tail_x + mid_r, tail_y + 4 + 2 * mid_r],
                fill=(255, 255, 255), outline=(0, 0, 0), width=self.OUTLINE_WIDTH,
            )
            draw.ellipse(
                [
                    tail_x - small_r,
                    tail_y + 4 + 2 * mid_r + 4,
                    tail_x + small_r,
                    tail_y + 4 + 2 * mid_r + 4 + 2 * small_r,
                ],
                fill=(255, 255, 255), outline=(0, 0, 0), width=self.OUTLINE_WIDTH,
            )

        self._draw_text_lines(draw, lines, x, y, font)

    def _draw_narration_bubble(
        self,
        draw: ImageDraw.Draw,
        lines: list[str],
        x: int,
        y: int,
        bubble_w: int,
        bubble_h: int,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        overlay = Image.new("RGBA", (bubble_w, bubble_h), (255, 255, 240, 200))
        temp_draw = ImageDraw.Draw(overlay)
        temp_draw.rectangle(
            [0, 0, bubble_w - 1, bubble_h - 1],
            fill=(255, 255, 240, 200),
            outline=(0, 0, 0),
            width=self.OUTLINE_WIDTH,
        )

        canvas_img = draw._image
        if canvas_img.mode != "RGBA":
            canvas_rgba = canvas_img.convert("RGBA")
        else:
            canvas_rgba = canvas_img
        canvas_rgba.paste(overlay, (x, y), overlay)
        if canvas_img.mode != "RGBA":
            canvas_img.paste(canvas_rgba.convert("RGB"))

        self._draw_text_lines(draw, lines, x, y, font)

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
        text_x = x + self.BUBBLE_PADDING + 4
        text_y = y + self.BUBBLE_PADDING + 4
        outline_color = (0, 0, 0)
        fill_color = (255, 255, 255)
        outline_width = 3
        for line in lines:
            bbox = font.getbbox(line)
            line_h = bbox[3] - bbox[1]
            for dx in range(-outline_width, outline_width + 1):
                for dy in range(-outline_width, outline_width + 1):
                    if dx * dx + dy * dy <= outline_width * outline_width:
                        draw.text(
                            (text_x + dx, text_y + dy), line,
                            fill=outline_color, font=font,
                        )
            draw.text((text_x, text_y), line, fill=fill_color, font=font)
            text_y += line_h + 4

    def _compute_tail_anchor(
        self, position_hint: str, x: int, y: int, bubble_w: int, bubble_h: int,
    ) -> tuple[int, int]:
        if position_hint in ("top-left", "bottom-left"):
            return x + bubble_w // 4, y + bubble_h
        elif position_hint in ("top-right", "bottom-right"):
            return x + 3 * bubble_w // 4, y + bubble_h
        elif position_hint == "top-center":
            return x + bubble_w // 2, y + bubble_h
        elif position_hint == "bottom-center":
            return x + bubble_w // 2, y
        else:
            return x + bubble_w // 2, y + bubble_h

    def _draw_text_lines(
        self,
        draw: ImageDraw.Draw,
        lines: list[str],
        bubble_x: int,
        bubble_y: int,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        text_x = bubble_x + self.BUBBLE_PADDING + 4
        text_y = bubble_y + self.BUBBLE_PADDING + 4
        for line in lines:
            bbox = font.getbbox(line)
            line_h = bbox[3] - bbox[1]
            draw.text((text_x, text_y), line, fill=(0, 0, 0), font=font)
            text_y += line_h + 4

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
                    (0, -(bh + 8)),
                    (0, fh + 8),
                    (-(bw + 8), 0),
                    (fw + 8, 0),
                ]
                for dx, dy in shifts:
                    nx, ny = bx + dx, by + dy
                    if not self._rects_overlap(nx, ny, bw, bh, fx, fy, fw, fh):
                        return nx, ny
        return bx, by

    def _rects_overlap(
        self,
        ax: int, ay: int, aw: int, ah: int,
        bx: int, by: int, bw: int, bh: int,
    ) -> bool:
        return not (
            ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay
        )

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
        if max_width <= 0:
            return [text]

        lines: list[str] = []
        current_line = ""
        for char in text:
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
            return (2 * self.BUBBLE_PADDING + 8, 2 * self.BUBBLE_PADDING + 8)

        line_widths: list[int] = []
        line_heights: list[int] = []
        for line in lines:
            bbox = font.getbbox(line)
            line_widths.append(bbox[2] - bbox[0])
            line_heights.append(bbox[3] - bbox[1])

        text_w = max(line_widths)
        text_h = sum(line_heights) + 4 * (len(lines) - 1)
        return (text_w + 2 * self.BUBBLE_PADDING + 8, text_h + 2 * self.BUBBLE_PADDING + 8)

    def _resolve_bubble_x(self, hint: str, panel_x: int, panel_w: int, bubble_w: int, padding: int = 16) -> int:
        if hint in ("top-left", "bottom-left"):
            return panel_x + padding
        if hint in ("top-right", "bottom-right"):
            return panel_x + panel_w - bubble_w - padding
        return panel_x + (panel_w - bubble_w) // 2
