from __future__ import annotations

import base64
import io
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx
from openai import AsyncOpenAI
from PIL import Image, ImageDraw

from app.config import settings


@dataclass
class ImageResult:
    image_data: bytes
    seed: int | None = None
    meta: dict = field(default_factory=dict)


class ImageBackend(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
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
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    @staticmethod
    def _size_to_str(size: tuple[int, int]) -> str:
        return f"{size[0]}x{size[1]}"

    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        size: tuple[int, int] = (1024, 1024),
        seed: int | None = None,
        **kwargs,
    ) -> ImageResult:
        size_str = self._size_to_str(size)
        response = await self._client.images.generate(
            model=settings.IMAGE_MODEL,
            prompt=prompt,
            n=1,
            size=size_str,
            response_format="b64_json",
        )
        b64 = response.data[0].b64_json
        image_data = base64.b64decode(b64)
        return ImageResult(
            image_data=image_data,
            seed=seed,
            meta={"model": settings.IMAGE_MODEL, "size": size_str, "prompt": prompt},
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
            model=settings.IMAGE_MODEL,
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
            meta={"model": settings.IMAGE_MODEL, "prompt": prompt},
        )


class CustomHttpBackend(ImageBackend):
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
        **kwargs,
    ) -> ImageResult:
        size_str = self._size_to_str(size)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "size": size_str,
            "model": settings.IMAGE_MODEL,
            **kwargs,
        }
        if seed is not None:
            body["seed"] = seed
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._base_url, headers=headers, json=body)
            resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            data = resp.json()
            if "image" in data:
                image_data = base64.b64decode(data["image"])
            elif "url" in data:
                async with httpx.AsyncClient() as client:
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
            meta={"model": settings.IMAGE_MODEL, "size": size_str, "prompt": prompt},
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
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._base_url, headers=headers, json=body)
            resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            data = resp.json()
            if "image" in data:
                result_data = base64.b64decode(data["image"])
            elif "url" in data:
                async with httpx.AsyncClient() as client:
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
        **kwargs,
    ) -> ImageResult:
        img = Image.new("RGB", size, color=(73, 109, 137))
        draw = ImageDraw.Draw(img)
        label = f"Mock Image\n{prompt[:40]}"
        draw.text((10, 10), label, fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return ImageResult(
            image_data=buf.getvalue(),
            seed=seed or 0,
            meta={"model": "mock", "size": f"{size[0]}x{size[1]}", "prompt": prompt},
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
    elif backend == "custom":
        return CustomHttpBackend()
    else:
        return MockImageBackend()
