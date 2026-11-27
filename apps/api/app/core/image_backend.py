from __future__ import annotations

import base64
import io
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx
from openai import AsyncOpenAI
from PIL import Image, ImageDraw

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ImageResult:
    image_data: bytes
    seed: int | None = None
    meta: dict = field(default_factory=dict)


def _compose_prompt(prompt: str, negative_prompt: str | None, context: dict | None) -> str:
    """Fold context notes and negative constraints into a single prompt string
    for providers without native structured fields."""
    parts = [prompt]
    if context:
        notes = []
        for character in context.get("characters", []) or []:
            name = character.get("name", "")
            appearance = character.get("appearance") or character.get("outfit") or ""
            if name:
                notes.append(f"{name}: {appearance}" if appearance else name)
        for loc in context.get("locations", []) or []:
            loc_name = loc.get("name", "")
            loc_desc = loc.get("description", "")
            if loc_name:
                notes.append(f"location {loc_name}: {loc_desc}" if loc_desc else f"location {loc_name}")
        for item in context.get("items", []) or []:
            item_name = item.get("name", "")
            item_desc = item.get("description", "")
            if item_name:
                notes.append(f"prop {item_name}: {item_desc}" if item_desc else f"prop {item_name}")
        art_style = context.get("art_style")
        if art_style:
            notes.append(f"manga art style: {art_style}")
        style_tags = context.get("style_tags") or []
        if style_tags:
            notes.append("style: " + ", ".join(str(t) for t in style_tags))
        episode_no = context.get("episode_number")
        if episode_no:
            notes.append(f"episode {episode_no} of the same series, keep visual continuity")
        if notes:
            parts.append("Consistency references — " + "; ".join(notes))
    if negative_prompt:
        parts.append(f"Avoid: {negative_prompt}")
    return "\n".join(p for p in parts if p)


class ImageBackend(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
        reference_images: list[tuple[bytes, str]] | None = None,
        context: dict | None = None,
        **kwargs,
    ) -> ImageResult: ...

    @abstractmethod
    async def inpaint(
        self,
        image_data: bytes,
        mask_data: bytes,
        prompt: str,
        **kwargs,
    ) -> ImageResult: ...


class OpenAIImageBackend(ImageBackend):
    """GPT Image family (gpt-image-2 / gpt-image-2.5-sunburst / -flare ...) via the
    OpenAI Images API: /images/generations for text-to-image, /images/edits when
    reference images (character sheets etc.) are supplied."""

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        raw_url = base_url or settings.IMAGE_API_URL or settings.OPENAI_BASE_URL
        if raw_url and "open.bigmodel.cn/api/coding/paas/v4" in raw_url and not base_url and not settings.IMAGE_API_URL:
            raw_url = raw_url.replace("/api/coding/paas/v4", "/api/paas/v4")
        self._base_url = raw_url
        self._client = AsyncOpenAI(
            api_key=api_key or settings.IMAGE_API_KEY or settings.OPENAI_API_KEY,
            base_url=raw_url,
            http_client=httpx.AsyncClient(trust_env=False, timeout=600.0),
        )
        self._model = model or settings.IMAGE_MODEL or "gpt-image-1"
        self._edits_supported = not bool(raw_url and "open.bigmodel.cn" in raw_url)

    @staticmethod
    def _size_to_str(size: tuple[int, int], model: str = "") -> str:
        w, h = size
        ratio = w / max(h, 1)
        m = (model or "").lower()
        if "cogview" in m:
            if ratio >= 1.75:
                return "1440x720"
            if ratio >= 1.35:
                return "1344x768"
            if ratio >= 1.15:
                return "1152x864"
            if ratio <= 0.57:
                return "720x1440"
            if ratio <= 0.74:
                return "768x1344"
            if ratio <= 0.87:
                return "864x1152"
            return "1024x1024"
        if "gpt-image" in m or "dall-e" in m:
            if (w, h) in {(1024, 1024), (1536, 1024), (1024, 1536), (1792, 1024), (1024, 1792)}:
                return f"{w}x{h}"
            if ratio >= 1.25:
                return "1536x1024"
            if ratio <= 0.80:
                return "1024x1536"
            return "1024x1024"
        return f"{w}x{h}"

    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
        reference_images: list[tuple[bytes, str]] | None = None,
        context: dict | None = None,
        **kwargs,
    ) -> ImageResult:
        import asyncio

        full_prompt = _compose_prompt(prompt, negative_prompt, context)
        model = kwargs.get("model") or self._model
        size_str = self._size_to_str(size, model)

        # OpenRouter image models use /chat/completions with modalities=["image", "text"]
        if "openrouter.ai" in (self._base_url or "").lower():
            return await self._generate_via_openrouter_chat(
                full_prompt=full_prompt,
                model=model,
                size=size,
                seed=seed,
                reference_images=reference_images,
            )

        used_edits = False
        response = None
        for attempt in range(4):
            try:
                if reference_images and self._edits_supported:
                    files = []
                    for i, (data, mime) in enumerate(reference_images):
                        ext = "png" if "png" in mime else "jpg" if "jpeg" in mime else "webp"
                        files.append(("image[]", (f"reference_{i}.{ext}", data, mime)))
                    try:
                        response = await self._client.images.edit(
                            model=model,
                            image=files,
                            prompt=full_prompt,
                            size=size_str,
                            n=1,
                        )
                        used_edits = True
                    except Exception as edit_exc:
                        err_s = str(edit_exc)
                        if any(code in err_s for code in ("404", "405", "400", "Not Found", "unsupported")):
                            logger.info(
                                "Images edits endpoint unsupported on %s, falling back to generations",
                                self._base_url,
                            )
                            self._edits_supported = False
                            response = await self._client.images.generate(
                                model=model,
                                prompt=full_prompt[:1800],
                                size=size_str,
                                n=1,
                            )
                        else:
                            raise
                else:
                    response = await self._client.images.generate(
                        model=model,
                        prompt=full_prompt[:1800],
                        size=size_str,
                        n=1,
                    )
                break
            except Exception as exc:
                if attempt < 3 and ("429" in str(exc) or "RateLimit" in type(exc).__name__):
                    await asyncio.sleep(3 * (attempt + 1))
                    continue
                raise
        item = response.data[0]
        if getattr(item, "b64_json", None):
            result_data = base64.b64decode(item.b64_json)
        elif getattr(item, "url", None):
            async with httpx.AsyncClient(trust_env=False, timeout=120.0) as dl:
                resp = await dl.get(item.url)
                resp.raise_for_status()
                result_data = resp.content
        else:
            result_data = b""
        return ImageResult(
            image_data=result_data,
            seed=seed,
            meta={
                "model": model,
                "size": size_str,
                "prompt": full_prompt,
                "references": len(reference_images or []),
                "endpoint": "edits" if used_edits else "generations",
            },
        )

    async def _generate_via_openrouter_chat(
        self,
        *,
        full_prompt: str,
        model: str,
        size: tuple[int, int],
        seed: int | None,
        reference_images: list[tuple[bytes, str]] | None,
    ) -> ImageResult:
        content: list[dict] = [{"type": "text", "text": full_prompt}]
        for data, mime in (reference_images or [])[:6]:
            b64 = base64.b64encode(data).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        headers = {
            "Authorization": f"Bearer {self._client.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Gwen0x4c3/manga-forge",
            "X-Title": "MangaForge",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": _nearest_ratio(size)},
        }
        url = f"{self._base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(trust_env=False, timeout=240.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            body = resp.json()

        img_bytes = b""
        choices = body.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            images = msg.get("images") or []
            for item in images:
                img_url = ""
                if isinstance(item, dict):
                    img_url = (item.get("image_url") or {}).get("url") or item.get("url") or ""
                if img_url.startswith("data:") and "," in img_url:
                    img_bytes = base64.b64decode(img_url.split(",", 1)[1])
                    break
                if img_url.startswith("http"):
                    async with httpx.AsyncClient(trust_env=False, timeout=120.0) as dl:
                        r = await dl.get(img_url)
                        r.raise_for_status()
                        img_bytes = r.content
                        break
        if not img_bytes:
            raise RuntimeError(f"OpenRouter model {model} did not return image data")
        return ImageResult(
            image_data=img_bytes,
            seed=seed,
            meta={
                "model": model,
                "size": f"{size[0]}x{size[1]}",
                "aspect_ratio": _nearest_ratio(size),
                "prompt": full_prompt,
                "references": len(reference_images or []),
                "endpoint": "openrouter_chat_image",
            },
        )

    async def inpaint(
        self,
        image_data: bytes,
        mask_data: bytes,
        prompt: str,
        **kwargs,
    ) -> ImageResult:
        image_file = io.BytesIO(image_data)
        image_file.name = "image.png"
        mask_file = io.BytesIO(mask_data)
        mask_file.name = "mask.png"
        response = await self._client.images.edit(
            model=kwargs.get("model") or self._model,
            image=image_file,
            mask=mask_file,
            prompt=prompt,
            n=1,
            response_format="b64_json",
        )
        b64 = response.data[0].b64_json
        result_data = base64.b64decode(b64)
        return ImageResult(
            image_data=result_data,
            meta={"model": kwargs.get("model") or self._model, "prompt": prompt},
        )


# Allowed aspect ratios of the Gemini image models (Nano Banana family).
_GEMINI_RATIOS = [(1, 1), (2, 3), (3, 2), (3, 4), (4, 3), (4, 5), (5, 4), (9, 16), (16, 9), (21, 9)]


def _nearest_ratio(size: tuple[int, int]) -> str:
    target = math.log(size[0] / size[1])
    best = min(_GEMINI_RATIOS, key=lambda r: abs(math.log(r[0] / r[1]) - target))
    return f"{best[0]}:{best[1]}"


class GeminiImageBackend(ImageBackend):
    """Nano Banana family via the Google Interactions API
    (POST /v1beta/interactions, x-goog-api-key auth).

    Models: gemini-3-pro-image (Nano Banana Pro), gemini-3.1-flash-image
    (Nano Banana 2 — recommended for multi-reference character consistency),
    gemini-2.5-flash-image (Nano Banana). Accepts up to 14 reference images
    as input parts."""

    DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        self._endpoint = endpoint or settings.IMAGE_API_URL or self.DEFAULT_ENDPOINT
        if self._endpoint and "/openai" in self._endpoint:
            self._endpoint = self.DEFAULT_ENDPOINT
        self._api_key = api_key or settings.IMAGE_API_KEY or settings.GEMINI_API_KEY
        self._model = model or settings.IMAGE_MODEL or "gemini-3.1-flash-image"

    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
        reference_images: list[tuple[bytes, str]] | None = None,
        context: dict | None = None,
        **kwargs,
    ) -> ImageResult:
        if not self._api_key:
            raise RuntimeError("Gemini image backend requires IMAGE_API_KEY or GEMINI_API_KEY")

        full_prompt = _compose_prompt(prompt, negative_prompt, context)
        model = kwargs.get("model") or self._model

        content: list[dict] = [{"type": "text", "text": full_prompt}]
        for data, mime in reference_images or []:
            content.append({"type": "image", "mime_type": mime, "data": base64.b64encode(data).decode()})

        max_edge = max(size)
        image_size = "1K" if max_edge <= 1024 else ("2K" if max_edge <= 2048 else "4K")
        body = {
            "model": model,
            "input": content,
            "response_format": {
                "type": "image",
                "mime_type": "image/png",
                "aspect_ratio": _nearest_ratio(size),
                "image_size": image_size,
            },
            "store": False,
        }

        async with httpx.AsyncClient(trust_env=False, timeout=600.0) as client:
            resp = await client.post(
                self._endpoint,
                headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                json=body,
            )
            resp.raise_for_status()
            payload = resp.json()

        image_bytes = self._extract_image(payload)
        return ImageResult(
            image_data=image_bytes,
            seed=seed,
            meta={
                "model": model,
                "size": f"{size[0]}x{size[1]}",
                "aspect_ratio": body["response_format"]["aspect_ratio"],
                "image_size": image_size,
                "prompt": full_prompt,
                "references": len(reference_images or []),
            },
        )

    @staticmethod
    def _extract_image(payload: dict) -> bytes:
        for step in payload.get("steps", []) or []:
            if step.get("type") != "model_output":
                continue
            for part in step.get("content", []) or []:
                if part.get("type") == "image" and part.get("data"):
                    return base64.b64decode(part["data"])
        for candidate in payload.get("candidates", []) or []:
            for part in (candidate.get("content", {}) or {}).get("parts", []) or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        raise RuntimeError(f"Gemini image response contained no image: {str(payload)[:300]}")

    async def inpaint(
        self,
        image_data: bytes,
        mask_data: bytes,
        prompt: str,
        **kwargs,
    ) -> ImageResult:
        return await self.generate(
            prompt=f"{prompt}\n(Inpaint only the masked region; keep everything else identical.)",
            reference_images=[(image_data, "image/png"), (mask_data, "image/png")],
            size=kwargs.get("size", (1024, 1024)),
            seed=kwargs.get("seed"),
        )


class CustomHttpBackend(ImageBackend):
    """Generic HTTP adapter for aggregators exposing an OpenAI-compatible
    Images API on a custom URL (IMAGE_API_URL is the full endpoint)."""

    def __init__(self, model: str | None = None) -> None:
        self._base_url = settings.IMAGE_API_URL
        self._api_key = settings.IMAGE_API_KEY
        self._model = model or settings.IMAGE_MODEL

    @staticmethod
    def _size_to_str(size: tuple[int, int]) -> str:
        return f"{size[0]}x{size[1]}"

    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
        reference_images: list[tuple[bytes, str]] | None = None,
        context: dict | None = None,
        **kwargs,
    ) -> ImageResult:
        if not self._base_url:
            raise RuntimeError("Custom image backend requires IMAGE_API_URL")
        size_str = self._size_to_str(size)
        model = kwargs.pop("model", None) or self._model
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "prompt": _compose_prompt(prompt, negative_prompt, context),
            "size": size_str,
            "model": model,
            **kwargs,
        }
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        if seed is not None:
            body["seed"] = seed
        if reference_images:
            body["reference_images"] = [
                f"data:{mime};base64," + base64.b64encode(data).decode() for data, mime in reference_images
            ]
        async with httpx.AsyncClient(trust_env=False, timeout=600.0) as client:
            resp = await client.post(self._base_url, headers=headers, json=body)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                data = resp.json()
                if "image" in data:
                    image_data = base64.b64decode(data["image"])
                elif data.get("data") and isinstance(data["data"], list) and data["data"][0].get("b64_json"):
                    image_data = base64.b64decode(data["data"][0]["b64_json"])
                elif "url" in data:
                    img_resp = await client.get(data["url"])
                    img_resp.raise_for_status()
                    image_data = img_resp.content
                else:
                    image_data = resp.content
            else:
                image_data = resp.content
        return ImageResult(
            image_data=image_data,
            seed=seed,
            meta={
                "model": model,
                "size": size_str,
                "prompt": prompt,
                "references": len(reference_images or []),
            },
        )

    async def inpaint(
        self,
        image_data: bytes,
        mask_data: bytes,
        prompt: str,
        **kwargs,
    ) -> ImageResult:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "prompt": prompt,
            "image": base64.b64encode(image_data).decode(),
            "mask": base64.b64encode(mask_data).decode(),
            "model": self._model,
            **kwargs,
        }
        async with httpx.AsyncClient(trust_env=False, timeout=600.0) as client:
            resp = await client.post(self._base_url, headers=headers, json=body)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                data = resp.json()
                if "image" in data:
                    result_data = base64.b64decode(data["image"])
                elif "url" in data:
                    img_resp = await client.get(data["url"])
                    img_resp.raise_for_status()
                    result_data = img_resp.content
                else:
                    result_data = resp.content
            else:
                result_data = resp.content
        return ImageResult(
            image_data=result_data,
            meta={"model": self._model, "prompt": prompt},
        )


class MockImageBackend(ImageBackend):
    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
        reference_images: list[tuple[bytes, str]] | None = None,
        context: dict | None = None,
        **kwargs,
    ) -> ImageResult:
        # Render a stylized manga screentone mock panel so layout previews look clean
        img = Image.new("RGB", size, color=(248, 248, 250))
        draw = ImageDraw.Draw(img)
        # Subtle manga screentone speedlines / atmosphere
        for y in range(0, size[1], 24):
            tone = 232 + (y % 48) // 4
            draw.line([(0, y), (size[0], y)], fill=(tone, tone, tone + 4), width=2)
        # Focal silhouette frame
        cx, cy = size[0] // 2, int(size[1] * 0.56)
        r = min(size) // 5
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(220, 224, 232), outline=(45, 50, 60), width=4)
        draw.rectangle(
            [cx - int(r * 1.2), cy + r, cx + int(r * 1.2), size[1] - 12],
            fill=(65, 72, 88),
            outline=(35, 40, 50),
            width=4,
        )

        draw.rectangle([8, 8, size[0] - 8, size[1] - 8], outline=(30, 30, 35), width=4)
        draw.rectangle([16, 16, min(size[0] - 16, 360), 54], fill=(25, 28, 36))
        draw.text((26, 26), "MANGA PANEL PREVIEW (MOCK)", fill=(255, 255, 255))
        for i, line in enumerate(prompt.split("\n")[:6]):
            draw.text((20, 68 + i * 22), line[:78], fill=(60, 65, 80))
        if reference_images:
            draw.rectangle([16, size[1] - 54, 260, size[1] - 20], fill=(230, 248, 235), outline=(40, 130, 65), width=2)
            draw.text((26, size[1] - 44), f"Refs attached: {len(reference_images)}", fill=(20, 100, 45))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return ImageResult(
            image_data=buf.getvalue(),
            seed=seed,
            meta={
                "model": "mock",
                "size": f"{size[0]}x{size[1]}",
                "prompt": prompt,
                "references": len(reference_images or []),
            },
        )

    async def inpaint(
        self,
        image_data: bytes,
        mask_data: bytes,
        prompt: str,
        **kwargs,
    ) -> ImageResult:
        img = Image.open(io.BytesIO(image_data))
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), f"Inpainted\n{prompt[:40]}", fill=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return ImageResult(
            image_data=buf.getvalue(),
            meta={"model": "mock", "prompt": prompt},
        )


class AntigravityImageBackend(ImageBackend):
    """Google Antigravity native image-generator backend (`agy` CLI or Bridge Queue).
    Supports passing local character/item/style reference crops (`ImagePaths`) directly
    to Antigravity's native `generate_image` tool for multi-reference manga consistency."""

    def __init__(self, model: str | None = None, *, endpoint: str | None = None) -> None:
        from pathlib import Path

        self._model = model or "antigravity-image-generator"
        raw = (endpoint or "").strip()
        if raw and Path(raw).is_dir():
            self._bridge_dir = raw
            self._cli_bin = settings.AGY_CLI_BIN or "agy"
        else:
            self._bridge_dir = settings.AGY_BRIDGE_DIR
            self._cli_bin = raw or settings.AGY_CLI_BIN or "agy"

    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
        reference_images: list[tuple[bytes, str]] | None = None,
        context: dict | None = None,
        **kwargs,
    ) -> ImageResult:
        import asyncio
        import json
        import re
        import shutil
        import tempfile
        import uuid
        from pathlib import Path

        full_prompt = _compose_prompt(prompt, negative_prompt, context)
        aspect_ratio = _nearest_ratio(size)
        req_id = f"panel_{uuid.uuid4().hex[:10]}"

        if self._bridge_dir:
            base = Path(self._bridge_dir)
            refs_dir = base / "refs" / req_id
            req_dir = base / "requests"
            out_dir = base / "outputs"
            refs_dir.mkdir(parents=True, exist_ok=True)
            req_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            ref_paths: list[str] = []
            for idx, (data, mime) in enumerate(reference_images or []):
                ext = "png" if "png" in mime else ("webp" if "webp" in mime else "jpg")
                rp = refs_dir / f"ref_{idx}.{ext}"
                rp.write_bytes(data)
                ref_paths.append(str(rp))

            req_file = req_dir / f"{req_id}.json"
            done_file = out_dir / f"{req_id}.json"
            req_file.write_text(
                json.dumps(
                    {
                        "id": req_id,
                        "prompt": full_prompt,
                        "aspect_ratio": aspect_ratio,
                        "image_paths": ref_paths,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            for _ in range(300):
                if done_file.exists():
                    meta = json.loads(done_file.read_text(encoding="utf-8"))
                    img_bytes = Path(meta["image_path"]).read_bytes()
                    return ImageResult(
                        image_data=img_bytes,
                        seed=seed,
                        meta={
                            "model": self._model,
                            "aspect_ratio": aspect_ratio,
                            "references": len(ref_paths),
                            "mode": "bridge",
                        },
                    )
                await asyncio.sleep(1.0)
            raise TimeoutError(f"Antigravity bridge request {req_id} timed out")

        cli_path = shutil.which(self._cli_bin) or self._cli_bin
        with tempfile.TemporaryDirectory(prefix="mf_agy_") as tmp:
            tmp_dir = Path(tmp)
            ref_paths = []
            for idx, (data, mime) in enumerate(reference_images or []):
                ext = "png" if "png" in mime else ("webp" if "webp" in mime else "jpg")
                rp = tmp_dir / f"ref_{idx}.{ext}"
                rp.write_bytes(data)
                ref_paths.append(str(rp))

            agy_prompt = (
                "Invoke the `image-generator` subagent to generate a single manga panel using `generate_image` "
                f"with `ImageName`: {req_id!r}, `AspectRatio`: {aspect_ratio!r}, "
                f"`ImagePaths`: {json.dumps(ref_paths)}, and `Prompt`: {full_prompt!r}. "
                "Reply ONLY with the exact absolute file path of the saved image."
            )
            proc = await asyncio.create_subprocess_exec(
                cli_path,
                "--dangerously-skip-permissions",
                "--add-dir",
                str(tmp_dir),
                "-p",
                agy_prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            out_text = stdout.decode("utf-8", errors="replace").strip()
            if proc.returncode != 0:
                err_text = stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Antigravity CLI failed ({proc.returncode}): {err_text or out_text}")

            match = re.search(r"(/[^\s`'\"<>]+\.(?:png|jpg|jpeg|webp))", out_text)
            if not match or not Path(match.group(1)).is_file():
                raise RuntimeError(f"Antigravity CLI did not return a valid image path: {out_text[:300]}")
            img_bytes = Path(match.group(1)).read_bytes()
            return ImageResult(
                image_data=img_bytes,
                seed=seed,
                meta={
                    "model": self._model,
                    "aspect_ratio": aspect_ratio,
                    "references": len(ref_paths),
                    "mode": "cli",
                },
            )

    async def inpaint(
        self,
        image_data: bytes,
        mask_data: bytes,
        prompt: str,
        **kwargs,
    ) -> ImageResult:
        return await self.generate(prompt=prompt, reference_images=[(image_data, "image/png")], **kwargs)


class ComfyUIImageBackend(ImageBackend):
    """Local ComfyUI workflow backend (`COMFYUI_URL` + optional custom workflow JSON template).
    Uploads reference images via `/upload/image`, injects prompt/size/seed/ref placeholders,
    submits via `/prompt`, and polls `/history/{prompt_id}` until output is ready."""

    def __init__(self, model: str | None = None) -> None:
        self._base_url = (settings.COMFYUI_URL or "http://localhost:8188").rstrip("/")
        self._model = model or settings.IMAGE_MODEL or "sd_xl_base_1.0.safetensors"
        self._workflow_path = settings.COMFYUI_WORKFLOW_PATH

    def _build_workflow(
        self,
        prompt: str,
        negative_prompt: str,
        size: tuple[int, int],
        seed: int,
        uploaded_refs: list[str],
    ) -> dict:
        import json
        from pathlib import Path

        if self._workflow_path and Path(self._workflow_path).is_file():
            raw = Path(self._workflow_path).read_text(encoding="utf-8")
            raw = (
                raw.replace("{{PROMPT}}", json.dumps(prompt)[1:-1])
                .replace("{{NEGATIVE_PROMPT}}", json.dumps(negative_prompt)[1:-1])
                .replace("{{WIDTH}}", str(size[0]))
                .replace("{{HEIGHT}}", str(size[1]))
                .replace("{{SEED}}", str(seed))
                .replace("{{MODEL}}", json.dumps(self._model)[1:-1])
            )
            for idx, name in enumerate(uploaded_refs):
                raw = raw.replace(f"{{{{REF_IMAGE_{idx}}}}}", json.dumps(name)[1:-1])
            return json.loads(raw)

        # Standard ComfyUI txt2img graph when no custom workflow template is supplied
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": 24,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": self._model}},
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": size[0], "height": size[1], "batch_size": 1},
            },
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["4", 1]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mangaforge", "images": ["8", 0]}},
        }

    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
        reference_images: list[tuple[bytes, str]] | None = None,
        context: dict | None = None,
        **kwargs,
    ) -> ImageResult:
        import asyncio
        import random
        import uuid

        full_prompt = _compose_prompt(prompt, None, context)
        neg = negative_prompt or "speech bubble, text, watermark, blurry, deformed"
        actual_seed = seed if seed is not None else random.randint(1, 2**31 - 1)
        client_id = str(uuid.uuid4())

        async with httpx.AsyncClient(trust_env=False, timeout=300.0) as client:
            uploaded_refs: list[str] = []
            for idx, (data, mime) in enumerate(reference_images or []):
                ext = "png" if "png" in mime else "jpg"
                up = await client.post(
                    f"{self._base_url}/upload/image",
                    files={"image": (f"mf_ref_{client_id[:8]}_{idx}.{ext}", data, mime)},
                    data={"overwrite": "true"},
                )
                up.raise_for_status()
                uploaded_refs.append(up.json().get("name", ""))

            workflow = self._build_workflow(full_prompt, neg, size, actual_seed, uploaded_refs)
            resp = await client.post(f"{self._base_url}/prompt", json={"prompt": workflow, "client_id": client_id})
            resp.raise_for_status()
            prompt_id = resp.json()["prompt_id"]

            img_info = None
            for _ in range(240):
                hist = await client.get(f"{self._base_url}/history/{prompt_id}")
                hist.raise_for_status()
                entry = hist.json().get(prompt_id)
                if entry and entry.get("outputs"):
                    for node_out in entry["outputs"].values():
                        imgs = node_out.get("images") or []
                        if imgs:
                            img_info = imgs[0]
                            break
                    if img_info:
                        break
                await asyncio.sleep(1.0)

            if not img_info:
                raise TimeoutError(f"ComfyUI prompt {prompt_id} timed out")

            view = await client.get(
                f"{self._base_url}/view",
                params={
                    "filename": img_info["filename"],
                    "subfolder": img_info.get("subfolder", ""),
                    "type": img_info.get("type", "output"),
                },
            )
            view.raise_for_status()
            return ImageResult(
                image_data=view.content,
                seed=actual_seed,
                meta={
                    "model": self._model,
                    "size": f"{size[0]}x{size[1]}",
                    "prompt": full_prompt,
                    "references": len(uploaded_refs),
                    "prompt_id": prompt_id,
                },
            )

    async def inpaint(
        self,
        image_data: bytes,
        mask_data: bytes,
        prompt: str,
        **kwargs,
    ) -> ImageResult:
        return await self.generate(
            prompt=prompt,
            reference_images=[(image_data, "image/png"), (mask_data, "image/png")],
            **kwargs,
        )


class InstrumentedImageBackend(ImageBackend):
    """Transparent telemetry proxy wrapping any ImageBackend to record every image generation/inpaint call."""

    def __init__(self, inner: ImageBackend, backend_name: str, default_model: str | None = None) -> None:
        self._inner = inner
        self._backend_name = backend_name
        self._default_model = default_model or getattr(inner, "_model", None) or backend_name

    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
        reference_images: list[tuple[bytes, str]] | None = None,
        context: dict | None = None,
        **kwargs,
    ) -> ImageResult:
        import time

        from app.core.telemetry import record_usage_event

        t0 = time.perf_counter()
        requested_model = str(kwargs.get("model") or self._default_model or self._backend_name)
        size_str = f"{size[0]}x{size[1]}"
        try:
            result = await self._inner.generate(
                prompt=prompt,
                negative_prompt=negative_prompt,
                size=size,
                seed=seed,
                reference_images=reference_images,
                context=context,
                **kwargs,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            await record_usage_event(
                kind="image",
                operation="image_generate",
                provider=self._backend_name,
                model=requested_model,
                image_count=0,
                image_size=size_str,
                duration_ms=elapsed_ms,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                meta={
                    "references": len(reference_images or []),
                    "prompt_preview": (prompt or "")[:240],
                },
            )
            raise

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        res_meta = result.meta or {}
        await record_usage_event(
            kind="image",
            operation="image_generate",
            provider=self._backend_name,
            model=str(res_meta.get("model") or requested_model),
            image_count=1,
            image_size=str(res_meta.get("size") or size_str),
            duration_ms=elapsed_ms,
            status="succeeded",
            meta={
                "references": res_meta.get("references", len(reference_images or [])),
                "endpoint": res_meta.get("endpoint", "generate"),
                "seed": result.seed,
                "prompt_preview": (prompt or "")[:240],
            },
        )
        return result

    async def inpaint(
        self,
        image_data: bytes,
        mask_data: bytes,
        prompt: str,
        **kwargs,
    ) -> ImageResult:
        import time

        from app.core.telemetry import record_usage_event

        t0 = time.perf_counter()
        requested_model = str(kwargs.get("model") or self._default_model or self._backend_name)
        size_val = kwargs.get("size")
        size_str = f"{size_val[0]}x{size_val[1]}" if isinstance(size_val, tuple) and len(size_val) == 2 else None
        try:
            result = await self._inner.inpaint(
                image_data=image_data,
                mask_data=mask_data,
                prompt=prompt,
                **kwargs,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            await record_usage_event(
                kind="image",
                operation="image_inpaint",
                provider=self._backend_name,
                model=requested_model,
                image_count=0,
                image_size=size_str,
                duration_ms=elapsed_ms,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                meta={"prompt_preview": (prompt or "")[:240]},
            )
            raise

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        res_meta = result.meta or {}
        await record_usage_event(
            kind="image",
            operation="image_inpaint",
            provider=self._backend_name,
            model=str(res_meta.get("model") or requested_model),
            image_count=1,
            image_size=str(res_meta.get("size") or size_str or ""),
            duration_ms=elapsed_ms,
            status="succeeded",
            meta={
                "endpoint": "inpaint",
                "seed": result.seed,
                "prompt_preview": (prompt or "")[:240],
            },
        )
        return result


def get_image_backend(backend_name: str | None = None, model: str | None = None) -> ImageBackend:
    from app.core.provider_runtime import resolve_role_config

    resolved = resolve_role_config("image_gen")
    if backend_name:
        backend = backend_name
        eff_model = model
        eff_key = None
        eff_url = None
    elif resolved.source == "database":
        if resolved.interface_type == "gemini_image" or resolved.provider_key == "gemini":
            backend = "gemini"
        elif resolved.interface_type == "comfyui" or resolved.provider_key == "comfyui":
            backend = "comfyui"
        elif resolved.interface_type == "mock":
            backend = "mock"
        elif resolved.interface_type == "antigravity":
            backend = "antigravity"
        else:
            backend = "openai"
        eff_model = model or resolved.model or None
        eff_key = resolved.api_key or None
        eff_url = resolved.base_url or None
    else:
        backend = settings.IMAGE_BACKEND
        eff_model = model
        eff_key = None
        eff_url = None

    if backend == "antigravity":
        inner: ImageBackend = AntigravityImageBackend(model=eff_model, endpoint=eff_url)
    elif backend == "comfyui":
        inner = ComfyUIImageBackend(model=eff_model)
        if eff_url:
            inner._base_url = eff_url.rstrip("/")
    elif backend == "openai":
        inner = OpenAIImageBackend(model=eff_model, api_key=eff_key, base_url=eff_url)
    elif backend in ("gemini", "nano-banana"):
        inner = GeminiImageBackend(model=eff_model, api_key=eff_key)
    elif backend == "custom":
        inner = CustomHttpBackend(model=eff_model)
    else:
        inner = MockImageBackend()
    provider_label = resolved.provider_key if (not backend_name and resolved.source == "database") else backend
    return InstrumentedImageBackend(inner, backend_name=provider_label, default_model=eff_model)
