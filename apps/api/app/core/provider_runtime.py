from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.provider_presets import PRESET_BY_KEY
from app.core.secret_box import decrypt_secret

logger = logging.getLogger(__name__)

VALID_ROLES = ("main_llm", "vision_llm", "image_gen", "embedding")


@dataclass(frozen=True)
class ResolvedModelConfig:
    role: str
    source: str  # "database" | "env"
    provider_id: str | None
    provider_key: str
    provider_name: str
    interface_type: str
    base_url: str | None
    api_key: str
    model: str
    max_tokens: int = 16384
    extra_headers: dict[str, str] = field(default_factory=dict)
    image_size: str = "1024x1024"


_CACHE_TTL_SEC = 5.0
_cache_ts: float = 0.0
_cache_snapshot: dict[str, ResolvedModelConfig] = {}
_sync_engine = None
_runtime_test_overrides: dict[str, ResolvedModelConfig] | None = None


def set_runtime_test_overrides(overrides: dict[str, ResolvedModelConfig] | None) -> None:
    """Allow unit tests to inject deterministic resolved configs without touching MySQL."""
    global _runtime_test_overrides
    _runtime_test_overrides = overrides
    invalidate_provider_cache()


def invalidate_provider_cache() -> None:
    global _cache_ts, _cache_snapshot
    _cache_ts = 0.0
    _cache_snapshot = {}


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(settings.mysql_sync_dsn, pool_pre_ping=True, pool_size=2, max_overflow=2)
    return _sync_engine


def normalize_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme:
        return normalized
    return f"https://{normalized.lstrip('/')}"


def _env_fallback(role: str) -> ResolvedModelConfig:
    if role == "image_gen":
        backend = settings.IMAGE_BACKEND or "openai"
        if backend in ("gemini", "nano-banana"):
            return ResolvedModelConfig(
                role=role,
                source="env",
                provider_id=None,
                provider_key="gemini",
                provider_name="Google Gemini (.env)",
                interface_type="gemini_image",
                base_url=settings.IMAGE_API_URL or None,
                api_key=settings.IMAGE_API_KEY or settings.GEMINI_API_KEY or "",
                model=settings.IMAGE_MODEL or "gemini-3.1-flash-image",
                image_size=settings.IMAGE_DEFAULT_SIZE or "1024x1024",
            )
        if backend == "comfyui":
            return ResolvedModelConfig(
                role=role,
                source="env",
                provider_id=None,
                provider_key="comfyui",
                provider_name="ComfyUI (.env)",
                interface_type="comfyui",
                base_url=settings.COMFYUI_URL or "http://localhost:8188",
                api_key="",
                model=settings.IMAGE_MODEL or "flux1-dev.safetensors",
                image_size=settings.IMAGE_DEFAULT_SIZE or "1024x1024",
            )
        if backend == "mock":
            return ResolvedModelConfig(
                role=role,
                source="env",
                provider_id=None,
                provider_key="mock",
                provider_name="Mock (.env)",
                interface_type="mock",
                base_url=None,
                api_key="",
                model="mock",
                image_size=settings.IMAGE_DEFAULT_SIZE or "1024x1024",
            )
        if backend == "antigravity":
            return ResolvedModelConfig(
                role=role,
                source="env",
                provider_id=None,
                provider_key="antigravity",
                provider_name="Antigravity (.env)",
                interface_type="antigravity",
                base_url=None,
                api_key="",
                model=settings.IMAGE_MODEL or "antigravity",
                image_size=settings.IMAGE_DEFAULT_SIZE or "1024x1024",
            )
        return ResolvedModelConfig(
            role=role,
            source="env",
            provider_id=None,
            provider_key=backend,
            provider_name=f"{backend} (.env)",
            interface_type="openai_compatible",
            base_url=normalize_base_url(settings.IMAGE_API_URL or settings.OPENAI_BASE_URL),
            api_key=settings.IMAGE_API_KEY or settings.OPENAI_API_KEY or "",
            model=settings.IMAGE_MODEL or "gpt-image-2",
            image_size=settings.IMAGE_DEFAULT_SIZE or "1024x1024",
        )

    if role == "embedding":
        return ResolvedModelConfig(
            role=role,
            source="env",
            provider_id=None,
            provider_key=settings.LLM_BACKEND or "openai",
            provider_name="Embedding (.env)",
            interface_type="openai_compatible",
            base_url=normalize_base_url(settings.OPENAI_BASE_URL),
            api_key=settings.OPENAI_API_KEY or "",
            model=(settings.OPENAI_EMBEDDING_MODEL or "").strip(),
            max_tokens=settings.OPENAI_MAX_TOKENS,
        )

    # main_llm / vision_llm
    return ResolvedModelConfig(
        role=role,
        source="env",
        provider_id=None,
        provider_key=settings.LLM_BACKEND or "openai",
        provider_name="Environment (.env)",
        interface_type="openai_compatible",
        base_url=normalize_base_url(settings.OPENAI_BASE_URL),
        api_key=settings.OPENAI_API_KEY or "",
        model=settings.OPENAI_MODEL or "gpt-4o",
        max_tokens=settings.OPENAI_MAX_TOKENS,
    )


def _load_db_snapshot() -> dict[str, ResolvedModelConfig]:
    from app.models.model_provider import ModelProvider, ModelRoleBinding

    resolved: dict[str, ResolvedModelConfig] = {}
    try:
        engine = _get_sync_engine()
        with Session(engine) as session:
            bindings = list(session.execute(select(ModelRoleBinding)).scalars().all())
            provider_ids = [b.provider_id for b in bindings if b.provider_id]
            providers_by_id: dict[str, ModelProvider] = {}
            if provider_ids:
                for p in session.execute(
                    select(ModelProvider).where(ModelProvider.id.in_(provider_ids), ModelProvider.enabled.is_(True))
                ).scalars().all():
                    providers_by_id[p.id] = p

            for b in bindings:
                if not b.provider_id or b.provider_id not in providers_by_id:
                    continue
                p = providers_by_id[b.provider_id]
                preset = PRESET_BY_KEY.get(p.preset_key)
                headers = dict(preset.extra_headers if preset else {})
                if p.extra_headers:
                    headers.update({str(k): str(v) for k, v in p.extra_headers.items()})
                params = b.params or {}
                eff_interface = p.interface_type
                if b.role == "image_gen" and p.preset_key == "gemini":
                    eff_interface = "gemini_image"
                elif b.role == "image_gen" and p.preset_key == "comfyui":
                    eff_interface = "comfyui"

                resolved[b.role] = ResolvedModelConfig(
                    role=b.role,
                    source="database",
                    provider_id=p.id,
                    provider_key=p.preset_key,
                    provider_name=p.name,
                    interface_type=eff_interface,
                    base_url=normalize_base_url(p.base_url),
                    api_key=decrypt_secret(p.api_key_encrypted),
                    model=(b.model_id or p.default_model or "").strip(),
                    max_tokens=int(params.get("max_tokens") or settings.OPENAI_MAX_TOKENS),
                    extra_headers=headers,
                    image_size=str(params.get("image_size") or settings.IMAGE_DEFAULT_SIZE or "1024x1024"),
                )
    except Exception:
        logger.debug("Provider DB lookup skipped; falling back to .env", exc_info=True)
    return resolved


def resolve_role_config(role: str = "main_llm") -> ResolvedModelConfig:
    global _cache_ts, _cache_snapshot

    if _runtime_test_overrides is not None:
        if role in _runtime_test_overrides:
            return _runtime_test_overrides[role]
        if role == "vision_llm" and "main_llm" in _runtime_test_overrides:
            return _runtime_test_overrides["main_llm"]
        return _env_fallback(role)

    now = time.monotonic()
    if now - _cache_ts > _CACHE_TTL_SEC:
        _cache_snapshot = _load_db_snapshot()
        _cache_ts = now

    if role in _cache_snapshot:
        return _cache_snapshot[role]

    # vision_llm inherits main_llm when user didn't set a dedicated vision model
    if role == "vision_llm" and "main_llm" in _cache_snapshot:
        base = _cache_snapshot["main_llm"]
        return ResolvedModelConfig(**{**base.__dict__, "role": "vision_llm"})

    return _env_fallback(role)


async def probe_provider_connection(
    *,
    interface_type: str,
    base_url: str,
    api_key: str,
    model: str | None = None,
    extra_headers: dict[str, str] | None = None,
    preset_key: str = "custom",
) -> dict[str, Any]:
    """Verify endpoint reachability + auth and discover live models via /models (with safe fallback)."""
    t0 = time.perf_counter()
    norm_url = normalize_base_url(base_url) or ""
    if not norm_url:
        return {"ok": False, "latency_ms": 0, "message": "请先填写接口 Base URL", "models": []}

    headers: dict[str, str] = {"Accept": "application/json"}
    if extra_headers:
        headers.update({str(k): str(v) for k, v in extra_headers.items()})

    if interface_type == "comfyui":
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=8.0) as client:
                resp = await client.get(f"{norm_url}/system_stats")
                elapsed = int((time.perf_counter() - t0) * 1000)
                if resp.status_code < 400:
                    return {
                        "ok": True,
                        "latency_ms": elapsed,
                        "message": f"ComfyUI 连接正常 (HTTP {resp.status_code})",
                        "models": [],
                    }
                return {
                    "ok": False,
                    "latency_ms": elapsed,
                    "message": f"ComfyUI 返回 HTTP {resp.status_code}",
                    "models": [],
                }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "message": f"无法连接 ComfyUI: {exc}",
                "models": [],
            }

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        if preset_key == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"

    discovered: list[str] = []
    models_ok = False
    last_error = ""

    async with httpx.AsyncClient(trust_env=False, timeout=15.0) as client:
        # 1. Try GET /models (OpenAI / OpenRouter / DeepSeek / Kimi / Gemini / Anthropic / Qwen / Ollama)
        try:
            resp = await client.get(f"{norm_url}/models", headers=headers)
            if resp.status_code == 200:
                payload = resp.json()
                raw_list = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(raw_list, list):
                    for item in raw_list:
                        if isinstance(item, dict) and item.get("id"):
                            mid = str(item["id"])
                            if mid.startswith("models/"):
                                mid = mid[len("models/") :]
                            discovered.append(mid)
                    models_ok = True
            elif resp.status_code in (401, 403):
                return {
                    "ok": False,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "message": f"鉴权失败 (HTTP {resp.status_code})，请检查 API Key 或套餐权限",
                    "models": [],
                }
            else:
                last_error = f"/models 返回 HTTP {resp.status_code}"
        except Exception as exc:
            last_error = str(exc)

        # 2. If /models wasn't supported (e.g. GLM Coding Plan / custom proxies), run a tiny chat completion ping
        if not models_ok and model:
            try:
                ping = await client.post(
                    f"{norm_url}/chat/completions",
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 8,
                    },
                )
                elapsed = int((time.perf_counter() - t0) * 1000)
                if ping.status_code == 200:
                    return {
                        "ok": True,
                        "latency_ms": elapsed,
                        "message": f"连接与鉴权通过（模型 {model} 响应正常）",
                        "models": discovered[:200],
                    }
                detail = ping.text[:200]
                return {
                    "ok": False,
                    "latency_ms": elapsed,
                    "message": f"模型测试失败 (HTTP {ping.status_code}): {detail}",
                    "models": discovered[:200],
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "message": f"连接失败: {exc}",
                    "models": [],
                }

    elapsed = int((time.perf_counter() - t0) * 1000)
    if models_ok:
        return {
            "ok": True,
            "latency_ms": elapsed,
            "message": f"连接成功，拉取到 {len(discovered)} 个可用模型",
            "models": sorted(set(discovered))[:250],
        }
    return {
        "ok": False,
        "latency_ms": elapsed,
        "message": last_error or "无法探测接口，请填写模型 ID 后重试测试",
        "models": [],
    }
