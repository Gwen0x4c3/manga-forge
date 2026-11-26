from __future__ import annotations

import asyncio

from app.core.llm import get_active_model, get_llm_config_error
from app.core.provider_presets import PRESET_BY_KEY, PROVIDER_PRESETS
from app.core.provider_runtime import ResolvedModelConfig, resolve_role_config, set_runtime_test_overrides
from app.core.secret_box import decrypt_secret, encrypt_secret, mask_api_key
from app.database import Base
from app.models.model_provider import ModelProvider, ModelRoleBinding
from app.schemas.provider import ProviderCreateRequest, ProviderUpdateRequest, RoleBindingUpdateRequest
from app.services import provider_service
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_builtin_presets_cover_all_mainstream_providers():
    keys = {p.key for p in PROVIDER_PRESETS}
    expected = {
        "openrouter",
        "openai",
        "anthropic",
        "gemini",
        "glm_coding",
        "glm",
        "kimi",
        "deepseek",
        "qwen",
        "comfyui",
        "custom",
    }
    assert expected.issubset(keys)
    assert PRESET_BY_KEY["glm_coding"].base_url == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert PRESET_BY_KEY["openrouter"].base_url == "https://openrouter.ai/api/v1"
    assert PRESET_BY_KEY["deepseek"].base_url == "https://api.deepseek.com"
    assert PRESET_BY_KEY["kimi"].base_url == "https://api.moonshot.cn/v1"
    assert PRESET_BY_KEY["anthropic"].base_url == "https://api.anthropic.com/v1"


def test_secret_box_roundtrip_and_masking():
    raw = "sk-or-v1-supersecretkey1234567890abcd"
    enc = encrypt_secret(raw)
    assert enc is not None
    assert enc.startswith("enc:v1:")
    assert raw not in enc
    assert decrypt_secret(enc) == raw
    assert mask_api_key(raw) == "sk-o••••abcd"
    assert mask_api_key("") == ""


def test_runtime_role_inheritance_and_dynamic_override():
    try:
        set_runtime_test_overrides(
            {
                "main_llm": ResolvedModelConfig(
                    role="main_llm",
                    source="database",
                    provider_id="p-glm",
                    provider_key="glm_coding",
                    provider_name="智谱 GLM Coding Plan",
                    interface_type="openai_compatible",
                    base_url="https://open.bigmodel.cn/api/coding/paas/v4",
                    api_key="test-coding-key",
                    model="glm-5.4",
                    max_tokens=32768,
                )
            }
        )
        assert get_active_model("main_llm") == "glm-5.4"
        # vision_llm automatically inherits main_llm when not explicitly overridden
        vision = resolve_role_config("vision_llm")
        assert vision.model == "glm-5.4"
        assert vision.provider_key == "glm_coding"
        assert get_llm_config_error("main_llm") is None

        # Explicit vision override works independently of main_llm (e.g. DeepSeek main + Gemini vision)
        set_runtime_test_overrides(
            {
                "main_llm": ResolvedModelConfig(
                    role="main_llm",
                    source="database",
                    provider_id="p-ds",
                    provider_key="deepseek",
                    provider_name="DeepSeek",
                    interface_type="openai_compatible",
                    base_url="https://api.deepseek.com",
                    api_key="sk-ds-key",
                    model="deepseek-chat",
                ),
                "vision_llm": ResolvedModelConfig(
                    role="vision_llm",
                    source="database",
                    provider_id="p-gem",
                    provider_key="gemini",
                    provider_name="Google Gemini",
                    interface_type="openai_compatible",
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                    api_key="AIza-test",
                    model="gemini-2.5-flash",
                ),
            }
        )
        assert get_active_model("main_llm") == "deepseek-chat"
        assert get_active_model("vision_llm") == "gemini-2.5-flash"
    finally:
        set_runtime_test_overrides(None)


class _AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self._s = session

    async def execute(self, statement, *args, **kwargs):
        return self._s.execute(statement, *args, **kwargs)

    async def get(self, entity, ident):
        return self._s.get(entity, ident)

    def add(self, instance) -> None:
        self._s.add(instance)

    async def delete(self, instance) -> None:
        self._s.delete(instance)

    async def flush(self) -> None:
        self._s.flush()

    async def commit(self) -> None:
        self._s.commit()

    async def refresh(self, instance) -> None:
        self._s.refresh(instance)


def test_provider_service_crud_and_role_binding_lifecycle():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ModelProvider.__table__, ModelRoleBinding.__table__])
    db = _AsyncSessionAdapter(Session(engine))

    async def _run():
        # 1. Create GLM Coding Plan provider with quick bind to main_llm + vision_llm
        created = await provider_service.create_provider(
            db,  # type: ignore[arg-type]
            ProviderCreateRequest(
                preset_key="glm_coding",
                name="智谱 GLM Coding Plan",
                api_key="sk-glm-coding-secret-9999",
                default_model="glm-5.4",
                activate_roles=["main_llm", "vision_llm"],
            ),
        )
        assert created.preset_key == "glm_coding"
        assert created.base_url == "https://open.bigmodel.cn/api/coding/paas/v4"
        assert created.has_api_key is True
        assert created.api_key_masked == "sk-g••••9999"

        # 2. Update name without touching api_key -> secret stays encrypted and intact
        updated = await provider_service.update_provider(
            db,  # type: ignore[arg-type]
            created.id,
            ProviderUpdateRequest(name="我的 GLM Coding Plan"),
        )
        assert updated is not None
        assert updated.name == "我的 GLM Coding Plan"
        assert updated.has_api_key is True
        assert updated.api_key_masked == "sk-g••••9999"

        # 3. Create OpenRouter provider & switch main_llm to Claude via OpenRouter
        or_provider = await provider_service.create_provider(
            db,  # type: ignore[arg-type]
            ProviderCreateRequest(
                preset_key="openrouter",
                name="OpenRouter",
                api_key="sk-or-v1-abcd1234",
                default_model="anthropic/claude-sonnet-4",
            ),
        )
        binding = await provider_service.update_role_binding(
            db,  # type: ignore[arg-type]
            "main_llm",
            RoleBindingUpdateRequest(provider_id=or_provider.id, model_id="anthropic/claude-sonnet-4"),
        )
        assert binding.provider_id == or_provider.id
        assert binding.preset_key == "openrouter"
        assert binding.model_id == "anthropic/claude-sonnet-4"

        # 4. Overview reflects both providers and bound roles
        overview = await provider_service.get_overview(db)  # type: ignore[arg-type]
        assert len(overview.providers) == 2
        main_role = next(r for r in overview.roles if r.role == "main_llm")
        vision_role = next(r for r in overview.roles if r.role == "vision_llm")
        assert main_role.provider_id == or_provider.id
        assert vision_role.provider_id == created.id

        # 5. Deleting a provider cleanly unbinds roles referencing it
        deleted = await provider_service.delete_provider(db, or_provider.id)  # type: ignore[arg-type]
        assert deleted is True
        overview_after = await provider_service.get_overview(db)  # type: ignore[arg-type]
        assert len(overview_after.providers) == 1
        main_role_after = next(r for r in overview_after.roles if r.role == "main_llm")
        assert main_role_after.provider_id is None

    asyncio.run(_run())
    engine.dispose()
