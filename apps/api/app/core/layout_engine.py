from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont


@dataclass
class PanelImage:
    image_data: bytes
    panel_id: str
    dialogues: list[dict] = field(default_factory=list)
    position_hint: str = "center"


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

    def compose_page(self, layout: str, panels: list[PanelImage], page_number: int) -> ComposedPage:
        canvas = Image.new("RGB", (self.PAGE_WIDTH, self.PAGE_HEIGHT), (255, 255, 255))
        bounding_boxes = self._apply_layout(layout, len(panels))

        for panel, (px, py, pw, ph) in zip(panels, bounding_boxes):
            panel_img = Image.open(io.BytesIO(panel.image_data))
            fitted = self._fit_image_to_area(panel_img, pw, ph)
            canvas.paste(fitted, (px, py))

            if panel.dialogues:
                draw = ImageDraw.Draw(canvas)
                font = ImageFont.load_default()
                max_bubble_w = int(pw * self.BUBBLE_MAX_WIDTH_RATIO)
                bubble_y = py + 16
                for dialogue in panel.dialogues:
                    text = dialogue.get("text", "")
                    if not text:
                        continue
                    lines = self._wrap_text(text, font, max_bubble_w - 2 * self.BUBBLE_PADDING)
                    bubble_w, bubble_h = self._measure_bubble(lines, font)
                    bubble_x = self._resolve_bubble_x(panel.position_hint, px, pw, bubble_w)
                    self._draw_speech_bubble(draw, text, bubble_x, bubble_y, max_bubble_w, panel.position_hint)
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

    def _draw_speech_bubble(
        self,
        draw: ImageDraw.Draw,
        text: str,
        x: int,
        y: int,
        max_width: int,
        position_hint: str = "center",
    ) -> None:
        font = ImageFont.load_default()
        lines = self._wrap_text(text, font, max_width - 2 * self.BUBBLE_PADDING)
        bubble_w, bubble_h = self._measure_bubble(lines, font)

        draw.ellipse(
            [x, y, x + bubble_w, y + bubble_h],
            fill=(255, 255, 255),
            outline=(0, 0, 0),
            width=self.OUTLINE_WIDTH,
        )

        tail_size = 12
        if position_hint in ("top-left", "bottom-left"):
            tail_cx = x + bubble_w // 4
            tail_pts = [
                (tail_cx - tail_size // 2, y + bubble_h - 2),
                (tail_cx + tail_size // 2, y + bubble_h - 2),
                (tail_cx - tail_size, y + bubble_h + tail_size),
            ]
        elif position_hint in ("top-right", "bottom-right"):
            tail_cx = x + 3 * bubble_w // 4
            tail_pts = [
                (tail_cx - tail_size // 2, y + bubble_h - 2),
                (tail_cx + tail_size // 2, y + bubble_h - 2),
                (tail_cx + tail_size, y + bubble_h + tail_size),
            ]
        else:
            tail_cx = x + bubble_w // 2
            tail_pts = [
                (tail_cx - tail_size // 2, y + bubble_h - 2),
                (tail_cx + tail_size // 2, y + bubble_h - 2),
                (tail_cx, y + bubble_h + tail_size),
            ]

        draw.polygon(tail_pts, fill=(255, 255, 255), outline=(0, 0, 0))

        text_x = x + self.BUBBLE_PADDING + 4
        text_y = y + self.BUBBLE_PADDING + 4
        for line in lines:
            bbox = font.getbbox(line)
            line_h = bbox[3] - bbox[1]
            draw.text((text_x, text_y), line, fill=(0, 0, 0), font=font)
            text_y += line_h + 4

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
