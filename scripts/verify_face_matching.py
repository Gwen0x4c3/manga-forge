"""Verify visual character recognition: the protagonist (with reference sheet)
must be linked by face, and a same-uniform passer-by must NOT be linked to her.

Scenario: 小樱 (pink hair) has a reference sheet in the asset library.
Episode page shows 小樱 + a grey-haired bespectacled passer-by in the SAME
school uniform asking for directions.
"""
from __future__ import annotations

import asyncio
import io
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

PROJECT_ID = "d9a0038e-3ec9-4c17-8e29-91bf1c17e1ab"
FONT = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 20)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗ FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


def draw_face(hair: str, glasses: bool = False) -> bytes:
    """Reference-sheet style portrait."""
    img = Image.new("RGB", (400, 520), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([5, 5, 395, 515], outline="black", width=3)
    cx, cy = 200, 210
    d.ellipse([cx - 80, cy - 130, cx + 80, cy + 30], fill="#ffe0c8", outline="black", width=3)
    d.polygon([cx - 85, cy - 40, cx - 60, cy - 155, cx + 10, cy - 110], fill=hair)
    d.polygon([cx + 85, cy - 40, cx + 60, cy - 155, cx - 10, cy - 110], fill=hair)
    d.polygon([cx - 60, cy - 155, cx + 60, cy - 155, cx, cy - 120], fill=hair)
    d.ellipse([cx - 28, cy - 80, cx - 8, cy - 62], fill="black")
    d.ellipse([cx + 8, cy - 80, cx + 28, cy - 62], fill="black")
    if glasses:
        d.rectangle([cx - 40, cy - 90, cx - 2, cy - 55], outline="black", width=3)
        d.rectangle([cx + 2, cy - 90, cx + 40, cy - 55], outline="black", width=3)
        d.line([cx - 2, cy - 75, cx + 2, cy - 75], fill="black", width=2)
    d.arc([cx - 20, cy - 48, cx + 20, cy - 18], 20, 160, fill="black", width=2)
    d.rectangle([cx - 70, cy + 32, cx + 70, cy + 190], fill="#3a5fbf", outline="black", width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def draw_page() -> bytes:
    """Corridor scene: 小樱 (pink twin-tails) and a grey-haired passer-by in the SAME uniform."""
    img = Image.new("RGB", (900, 1300), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 880, 1280], outline="black", width=4)
    d.rectangle([40, 40, 860, 1240], fill="#eef2f8")  # corridor bg
    for dx in range(120, 820, 140):
        d.rectangle([dx, 220, dx + 60, 520], fill="#cfe0f5", outline="#9ab0cc")  # windows

    def person(cx: int, cy: int, hair: str, glasses: bool):
        d.ellipse([cx - 55, cy - 120, cx + 55, cy - 10], fill="#ffe0c8", outline="black", width=3)
        d.polygon([cx - 60, cy - 50, cx - 35, cy - 150, cx + 5, cy - 100], fill=hair)
        d.polygon([cx + 60, cy - 50, cx + 35, cy - 150, cx - 5, cy - 100], fill=hair)
        d.polygon([cx - 35, cy - 150, cx + 35, cy - 150, cx, cy - 112], fill=hair)
        d.ellipse([cx - 16, cy - 85, cx - 4, cy - 70], fill="black")
        d.ellipse([cx + 4, cy - 85, cx + 16, cy - 70], fill="black")
        if glasses:
            d.rectangle([cx - 26, cy - 92, cx - 2, cy - 62], outline="black", width=3)
            d.rectangle([cx + 2, cy - 92, cx + 26, cy - 62], outline="black", width=3)
        d.arc([cx - 12, cy - 52, cx + 12, cy - 30], 20, 160, fill="black", width=2)
        d.rectangle([cx - 50, cy - 8, cx + 50, cy + 200], fill="#3a5fbf", outline="black", width=3)  # same uniform

    person(250, 620, "#ff9ecf", glasses=False)   # 小樱: pink hair
    person(640, 640, "#b8b8c0", glasses=True)    # passer-by: grey hair + glasses

    def bubble(x0, y0, x1, y1, text):
        d.ellipse([x0, y0, x1, y1], fill="white", outline="black", width=3)
        lines, cur = [], ""
        for ch in text:
            cur += ch
            if d.textlength(cur, font=FONT) > (x1 - x0) * 0.8:
                lines.append(cur[:-1])
                cur = ch
        lines.append(cur)
        ty = (y0 + y1) / 2 - 14 * len(lines)
        for ln in lines:
            w = d.textlength(ln, font=FONT)
            d.text(((x0 + x1) / 2 - w / 2, ty), ln, fill="black", font=FONT)
            ty += 28

    bubble(300, 300, 700, 430, "同学你好，请问图书馆怎么走？")
    bubble(60, 800, 420, 930, "直走到头左转就是～")
    d.text((50, 1180), "放学后的走廊", fill="gray", font=FONT)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def main():
    from sqlalchemy import select

    from app.database import async_session
    from app.models.asset import Asset
    from app.models.branch import Branch
    from app.models.episode import Episode
    from app.models.episode_memory import EpisodeMemory
    from app.models.episode_page import EpisodePage
    from app.schemas.episode import EpisodeImport
    from app.services import (
        asset_service,
        episode_service,
        storage_service,
        understanding_service,
    )
    from app.config import settings

    async with async_session() as db:
        xiaoying = (
            await db.execute(select(Asset).where(Asset.project_id == PROJECT_ID, Asset.name.like("%小樱%")))
        ).scalars().first()
        check("小樱 asset exists", xiaoying is not None)
        xiaoying_id = xiaoying.id

        # give 小樱 a proper face reference sheet
        await asset_service.upload_asset_image(db, xiaoying, draw_face("#ff9ecf"), "sakura_sheet.png", kind="reference")

        # direct check: reference block builder returns her sheet
        known = list((await db.execute(select(Asset).where(Asset.project_id == PROJECT_ID))).scalars().all())
        blocks = await understanding_service._character_reference_blocks(db, known)
        check("reference sheet picked up", any(xiaoying_id in label for label, _ in blocks),
              str([label for label, _ in blocks]))

        branch = (
            await db.execute(
                select(Branch).where(Branch.project_id == PROJECT_ID, Branch.is_default == True)  # noqa: E712
            )
        ).scalars().first()
        ep = await episode_service.create_episode(
            db, PROJECT_ID, EpisodeImport(branch_id=branch.id, number=Decimal("9"), title="走廊问路的同学")
        )
        key = storage_service.generate_object_key(f"smoke/{ep.id}", "p1.jpg")
        storage_service.upload_file(settings.MINIO_BUCKET, key, draw_page(), "image/jpeg")
        db.add(EpisodePage(episode_id=ep.id, page_index=0, image_path=key, width=900, height=1300))
        await db.commit()
        ep_id = ep.id

    print("\n== understand episode (visual matching) ==")
    async with async_session() as db:
        episode = await db.get(Episode, ep_id)
        result = await understanding_service.run_multimodal_understanding(db, episode, [(1, key)])

    roster = result.get("characters", [])
    print("    roster:", [(c.get("name"), c.get("asset_id")) for c in roster])
    print("    summary:", result.get("summary", "")[:150])

    sakura = next((c for c in roster if "小樱" in c.get("name", "")), None)
    check("小樱 in roster", sakura is not None)
    check("小樱 linked by face", sakura and sakura.get("asset_id") == xiaoying_id,
          str(sakura))
    others = [c for c in roster if c.get("asset_id") == xiaoying_id and c is not sakura]
    check("no one else linked to 小樱", not others, str(others))
    passerby = next((c for c in roster if c is not sakura and c.get("asset_id") is None), None) or \
        next((c for c in roster if c is not sakura), None)
    check("passer-by recognized as distinct person", passerby is not None and passerby.get("asset_id") != xiaoying_id,
          str(passerby))

    async with async_session() as db:
        mem = (
            await db.execute(
                select(EpisodeMemory).where(EpisodeMemory.episode_id == ep_id, EpisodeMemory.type == "summary")
            )
        ).scalars().all()
        check("understanding memory saved", bool(mem))

    print(f"\n==== FACE MATCH RESULT: {len(PASS)} passed, {len(FAIL)} failed ====")
    for f in FAIL:
        print(f"  FAILED: {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
