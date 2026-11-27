"""Verify: (1) Gemini Interactions backend request/response against a fake
server, (2) the tool-calling render agent end-to-end with the mock image
backend (real glm-5.3-flash tool loop, real DB/MinIO)."""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import sys
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402


PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗ FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


def tiny_png(color=(10, 200, 10)) -> bytes:
    img = Image.new("RGB", (64, 64), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------- fake Google Interactions server ----------
captured: dict = {}


class FakeInteractionsHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        captured["path"] = self.path
        captured["auth"] = self.headers.get("x-goog-api-key")
        captured["body"] = json.loads(self.rfile.read(length))
        png_b64 = base64.b64encode(tiny_png()).decode()
        payload = {
            "steps": [
                {"type": "model_output", "content": [{"type": "text", "text": "done"}]},
                {"type": "model_output", "content": [{"type": "image", "mime_type": "image/png", "data": png_b64}]},
            ]
        }
        out = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


async def test_gemini_backend():
    print("== Gemini Interactions backend (fake server) ==")
    from app.config import settings

    server = HTTPServer(("127.0.0.1", 0), FakeInteractionsHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    saved = (settings.IMAGE_BACKEND, settings.IMAGE_MODEL, settings.IMAGE_API_URL, settings.IMAGE_API_KEY)
    try:
        settings.IMAGE_BACKEND = "gemini"
        settings.IMAGE_MODEL = "gemini-3.1-flash-image"
        settings.IMAGE_API_URL = f"http://127.0.0.1:{port}/v1beta/interactions"
        settings.IMAGE_API_KEY = "test-key"

        from app.core.image_backend import get_image_backend

        backend = get_image_backend()
        result = await backend.generate(
            prompt="manga panel: girl opening a glowing box",
            negative_prompt="text artifacts",
            size=(1024, 1536),
            reference_images=[(tiny_png(), "image/png")],
            context={"characters": [{"name": "小樱", "appearance": "pink hair, school uniform"}]},
        )
        body = captured["body"]
        check("auth header x-goog-api-key", captured["auth"] == "test-key")
        check("endpoint path", captured["path"].endswith("/v1beta/interactions"), captured["path"])
        check("model passed", body.get("model") == "gemini-3.1-flash-image")
        types = [p.get("type") for p in body.get("input", [])]
        check("input = text + image refs", types == ["text", "image"], str(types))
        ref_part = body["input"][1]
        check("reference image base64+mime", ref_part.get("mime_type") == "image/png" and len(ref_part.get("data", "")) > 50)
        check(
            "prompt composed with context+negative",
            "manga panel" in body["input"][0]["text"] and "小樱" in body["input"][0]["text"] and "Avoid:" in body["input"][0]["text"],
            body["input"][0]["text"][:120],
        )
        rf = body.get("response_format", {})
        check("response_format image/ratio/size", rf.get("type") == "image" and rf.get("aspect_ratio") == "2:3" and rf.get("image_size") == "2K", str(rf))
        check("store false", body.get("store") is False)
        check("image extracted from steps", result.image_data[:8] == b"\x89PNG\r\n\x1a\n")
        check("meta records refs", result.meta.get("references") == 1 and result.meta.get("aspect_ratio") == "2:3")
    finally:
        settings.IMAGE_BACKEND, settings.IMAGE_MODEL, settings.IMAGE_API_URL, settings.IMAGE_API_KEY = saved
        server.shutdown()


async def test_render_agent(project_id: str):
    print("== Render agent e2e (glm tool loop + mock image backend) ==")
    from sqlalchemy import select

    from app.config import settings
    from app.database import async_session
    from app.models.asset import Asset
    from app.models.episode_memory import EpisodeMemory
    from app.models.generated_image import GeneratedImage
    from app.models.generation_run import GenerationRun
    from app.schemas.episode import EpisodeImport
    from app.services import asset_service, episode_service, generation_service, storage_service

    async with async_session() as db:
        from app.models.branch import Branch

        branch = (
            await db.execute(
                select(Branch).where(Branch.project_id == project_id, Branch.is_default == True)  # noqa: E712
            )
        ).scalars().first()
        xiaoying = (
            await db.execute(select(Asset).where(Asset.project_id == project_id, Asset.name.like("%小樱%")))
        ).scalars().first()
        check("asset 小樱 exists", xiaoying is not None)

        # ensure 小樱 has a reference image
        ref_png = tiny_png((255, 150, 200))
        await asset_service.upload_asset_image(db, xiaoying, ref_png, "xiaoying_ref.png", kind="reference")

        ep = await episode_service.create_episode(
            db, project_id, EpisodeImport(branch_id=branch.id, number=Decimal("8"), title="渲染Agent测试")
        )
        db.add(
            EpisodeMemory(
                episode_id=ep.id,
                type="storyboard_json",
                content={
                    "title": "星之匣的回响",
                    "synopsis": "小樱在阁楼再次打开星之匣，阿明在一旁守望。",
                    "tone": "main",
                    "pages": [
                        {
                            "page_number": 1,
                            "panels": [
                                {
                                    "panel_id": "1-1",
                                    "scene": "attic, afternoon light",
                                    "characters": [{"name": "小樱", "outfit": "school uniform", "emotion": "curious"}],
                                    "camera": "medium",
                                    "mood": "warm",
                                    "dialogue": [{"speaker": "小樱", "text": "又亮了……", "type": "speech"}],
                                    "prompt": "manga panel, girl in school uniform opening a glowing star-shaped box, attic, afternoon light",
                                },
                                {
                                    "panel_id": "1-2",
                                    "scene": "attic, close on box",
                                    "characters": [{"name": "小樱", "outfit": "school uniform"}, {"name": "阿明"}],
                                    "camera": "close-up",
                                    "mood": "mysterious",
                                    "dialogue": [],
                                    "prompt": "manga panel, close-up of glowing star box, two teenagers watching, attic",
                                },
                            ],
                        }
                    ],
                },
            )
        )
        await db.commit()
        run = await generation_service.create_generation_run(db, episode_id=ep.id, stage="render", backend="mock")
        ep_id, run_id = ep.id, str(run.id)

    class Shim:
        def update_state(self, **kw):
            print(f"    [render] {kw.get('state')}: {str(kw.get('meta'))[:140]}")

    from workers.tasks.render import _render_episode

    await _render_episode(Shim(), run_id, ep_id, "mock", None, "1024x1024")

    async with async_session() as db:
        run = await db.get(GenerationRun, run_id)
        check("render run succeeded", run.status == "succeeded", str(run.error))
        images = (
            await db.execute(select(GeneratedImage).where(GeneratedImage.episode_id == ep_id))
        ).scalars().all()
        panel_ids = {i.panel_id for i in images}
        check("both panels rendered", panel_ids == {"1-1", "1-2"}, str(panel_ids))
        agent_imgs = [i for i in images if (i.meta or {}).get("rendered_by") == "agent"]
        check("agent rendered at least one panel", len(agent_imgs) >= 1, str([(i.panel_id, (i.meta or {}).get("rendered_by")) for i in images]))
        with_refs = [i for i in images if (i.meta or {}).get("reference_assets")]
        check("reference assets attached", len(with_refs) >= 1, str([(i.panel_id, (i.meta or {}).get("reference_assets")) for i in images]))
        for img in images:
            meta = img.meta or {}
            print(
                f"    panel {img.panel_id}: by={meta.get('rendered_by')} refs={meta.get('reference_assets')} "
                f"prompt={meta.get('prompt', '')[:80]!r}"
            )
            check(f"panel {img.panel_id} image in storage", storage_service.get_object_bytes(settings.MINIO_BUCKET, img.image_path) is not None)
            if img.panel_id == "1-1":
                check("panel 1-1 prompt enriched with asset info", "小樱" in meta.get("prompt", "") or "pink" in meta.get("prompt", "").lower(), meta.get("prompt", "")[:150])
        agent_stats = (run.params or {}).get("render_agent", {})
        print(f"    agent stats: {agent_stats}")
        check("agent used research tools", agent_stats.get("tools_used", 0) >= 2, str(agent_stats))


async def main(project_id: str):
    await test_gemini_backend()
    await test_render_agent(project_id)
    print(f"\n==== RENDER AGENT RESULT: {len(PASS)} passed, {len(FAIL)} failed ====")
    for f in FAIL:
        print(f"  FAILED: {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id", help="ID of the smoke-test project containing 小樱")
    asyncio.run(main(parser.parse_args().project_id))
