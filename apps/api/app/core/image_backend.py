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

    def __init__(self, model: str | None = None) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.IMAGE_API_KEY or settings.OPENAI_API_KEY,
            base_url=settings.IMAGE_API_URL or settings.OPENAI_BASE_URL,
            http_client=httpx.AsyncClient(trust_env=False, timeout=600.0),
        )
        self._model = model or settings.IMAGE_MODEL or "gpt-image-2"

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
        full_prompt = _compose_prompt(prompt, negative_prompt, context)
        size_str = self._size_to_str(size)
        model = kwargs.get("model") or self._model

        if reference_images:
            files = []
            for i, (data, mime) in enumerate(reference_images):
                ext = "png" if "png" in mime else "jpg" if "jpeg" in mime else "webp"
                files.append(("image[]", (f"reference_{i}.{ext}", data, mime)))
            response = await self._client.images.edit(
                model=model,
                image=files,
                prompt=full_prompt,
                size=size_str,
                n=1,
            )
        else:
            response = await self._client.images.generate(
                model=model,
                prompt=full_prompt,
                size=size_str,
                n=1,
            )
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
                "endpoint": "edits" if reference_images else "generations",
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

    def __init__(self, model: str | None = None) -> None:
        self._endpoint = settings.IMAGE_API_URL or self.DEFAULT_ENDPOINT
        self._api_key = settings.IMAGE_API_KEY or settings.GEMINI_API_KEY
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


def get_image_backend(backend_name: str | None = None, model: str | None = None) -> ImageBackend:
    backend = backend_name or settings.IMAGE_BACKEND
    if backend == "openai":
        return OpenAIImageBackend(model=model)
    elif backend in ("gemini", "nano-banana"):
        return GeminiImageBackend(model=model)
    elif backend == "custom":
        return CustomHttpBackend(model=model)
    else:
        return MockImageBackend()
