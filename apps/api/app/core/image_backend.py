from __future__ import annotations

import base64
import io
import logging
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

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.IMAGE_API_KEY or settings.OPENAI_API_KEY,
            base_url=settings.IMAGE_API_URL or settings.OPENAI_BASE_URL,
            http_client=httpx.AsyncClient(trust_env=False, timeout=600.0),
        )
        self._model = settings.IMAGE_MODEL or "gpt-image-2"

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
        b64 = response.data[0].b64_json
        result_data = base64.b64decode(b64) if b64 else b""
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
import math  # noqa: E402


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

    def __init__(self) -> None:
        self._endpoint = settings.IMAGE_API_URL or self.DEFAULT_ENDPOINT
        self._api_key = settings.IMAGE_API_KEY or settings.GEMINI_API_KEY
        self._model = settings.IMAGE_MODEL or "gemini-3.1-flash-image"

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
        # Interactions shape: steps[type=model_output].content[].{type: image, data}
        for step in payload.get("steps", []) or []:
            if step.get("type") != "model_output":
                continue
            for part in step.get("content", []) or []:
                if part.get("type") == "image" and part.get("data"):
                    return base64.b64decode(part["data"])
        # Legacy generateContent shape: candidates[].content.parts[].inlineData
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
        # Nano Banana edits are conversational: image + mask described in prompt.
        return await self.generate(
            prompt=f"{prompt}\n(Inpaint only the masked region; keep everything else identical.)",
            reference_images=[(image_data, "image/png"), (mask_data, "image/png")],
            size=kwargs.get("size", (1024, 1024)),
            seed=kwargs.get("seed"),
        )


class CustomHttpBackend(ImageBackend):
    """Generic HTTP adapter for aggregators exposing an OpenAI-compatible
    Images API on a custom URL (IMAGE_API_URL is the full endpoint)."""

    def __init__(self) -> None:
        self._base_url = settings.IMAGE_API_URL
        self._api_key = settings.IMAGE_API_KEY

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
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "prompt": _compose_prompt(prompt, negative_prompt, context),
            "size": size_str,
            "model": settings.IMAGE_MODEL,
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
                "model": settings.IMAGE_MODEL,
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
            "model": settings.IMAGE_MODEL,
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
            meta={"model": settings.IMAGE_MODEL, "prompt": prompt},
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
        img = Image.new("RGB", size, color=(240, 240, 245))
        draw = ImageDraw.Draw(img)
        draw.rectangle([5, 5, size[0] - 5, size[1] - 5], outline=(60, 60, 70), width=3)
        draw.text((12, 12), "MOCK PANEL", fill=(40, 40, 50))
        for i, line in enumerate(prompt.split("\n")[:8]):
            draw.text((12, 40 + i * 18), line[:90], fill=(80, 80, 100))
        if reference_images:
            draw.text((12, size[1] - 60), f"refs attached: {len(reference_images)}", fill=(0, 120, 0))
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


def get_image_backend() -> ImageBackend:
    backend = settings.IMAGE_BACKEND
    if backend == "openai":
        return OpenAIImageBackend()
    elif backend in ("gemini", "nano-banana"):
        return GeminiImageBackend()
    elif backend == "custom":
        return CustomHttpBackend()
    else:
        return MockImageBackend()
