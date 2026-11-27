from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.provider_presets import PRESET_BY_KEY, PROVIDER_PRESETS
from app.core.provider_runtime import (
    VALID_ROLES,
    invalidate_provider_cache,
    normalize_base_url,
    probe_provider_connection,
    resolve_role_config,
)
from app.core.secret_box import decrypt_secret, encrypt_secret, mask_api_key
from app.models.model_provider import ModelProvider, ModelRoleBinding
from app.schemas.provider import (
    ModelProviderResponse,
    ProviderCreateRequest,
    ProviderOverviewResponse,
    ProviderTestRequest,
    ProviderTestResponse,
    ProviderUpdateRequest,
    RoleBindingItem,
    RoleBindingUpdateRequest,
)


def _serialize_provider(p: ModelProvider) -> ModelProviderResponse:
    return ModelProviderResponse(
        id=p.id,
        preset_key=p.preset_key,
        name=p.name,
        interface_type=p.interface_type,
        base_url=p.base_url or "",
        has_api_key=bool(p.api_key_encrypted),
        api_key_masked=p.api_key_hint or "",
        default_model=p.default_model or "",
        models_cache=list(p.models_cache or []),
        extra_headers=dict(p.extra_headers or {}),
        enabled=p.enabled,
        last_test_status=p.last_test_status,
        last_test_message=p.last_test_message,
        last_tested_at=p.last_tested_at,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


async def get_overview(db: AsyncSession) -> ProviderOverviewResponse:
    providers = list(
        (await db.execute(select(ModelProvider).order_by(ModelProvider.created_at.desc()))).scalars().all()
    )
    providers_by_id = {p.id: p for p in providers}
    bindings = list((await db.execute(select(ModelRoleBinding))).scalars().all())
    bindings_by_role = {b.role: b for b in bindings}

    role_items: list[RoleBindingItem] = []
    for role in VALID_ROLES:
        b = bindings_by_role.get(role)
        p = providers_by_id.get(b.provider_id) if (b and b.provider_id) else None
        eff = resolve_role_config(role)
        role_items.append(
            RoleBindingItem(
                role=role,
                provider_id=b.provider_id if b else None,
                provider_name=p.name if p else None,
                preset_key=p.preset_key if p else None,
                model_id=b.model_id if b else None,
                params=dict((b.params or {}) if b else {}),
                effective_source=eff.source,
                effective_provider=eff.provider_name,
                effective_model=eff.model,
                effective_base_url=eff.base_url,
            )
        )

    return ProviderOverviewResponse(
        presets=[preset.to_dict() for preset in PROVIDER_PRESETS],
        providers=[_serialize_provider(p) for p in providers],
        roles=role_items,
    )


async def create_provider(db: AsyncSession, payload: ProviderCreateRequest) -> ModelProviderResponse:
    preset = PRESET_BY_KEY.get(payload.preset_key)
    interface_type = payload.interface_type or (preset.interface_type if preset else "openai_compatible")
    raw_url = (payload.base_url or (preset.base_url if preset else "")).strip()
    base_url = raw_url if interface_type == "antigravity" else (normalize_base_url(raw_url) or "")
    default_model = (payload.default_model or (preset.default_model if preset else "")).strip()
    headers = dict(preset.extra_headers if preset else {})
    if payload.extra_headers:
        headers.update(payload.extra_headers)

    raw_key = (payload.api_key or "").strip()
    provider = ModelProvider(
        id=str(uuid.uuid4()),
        preset_key=payload.preset_key,
        name=payload.name.strip(),
        interface_type=interface_type,
        base_url=base_url,
        api_key_encrypted=encrypt_secret(raw_key) if raw_key else None,
        api_key_hint=mask_api_key(raw_key) if raw_key else None,
        default_model=default_model,
        models_cache=payload.models_cache or ([m.id for m in preset.models] if preset else []),
        extra_headers=headers or None,
        enabled=payload.enabled,
    )
    db.add(provider)
    await db.flush()

    if payload.activate_roles:
        for role in payload.activate_roles:
            if role not in VALID_ROLES:
                continue
            existing = await db.get(ModelRoleBinding, role)
            if existing:
                existing.provider_id = provider.id
                existing.model_id = default_model or existing.model_id
            else:
                db.add(ModelRoleBinding(role=role, provider_id=provider.id, model_id=default_model or None))

    await db.commit()
    await db.refresh(provider)
    invalidate_provider_cache()
    return _serialize_provider(provider)


async def update_provider(
    db: AsyncSession, provider_id: str, payload: ProviderUpdateRequest
) -> ModelProviderResponse | None:
    provider = await db.get(ModelProvider, provider_id)
    if not provider:
        return None

    if payload.name is not None:
        provider.name = payload.name.strip()
    if payload.interface_type is not None:
        provider.interface_type = payload.interface_type
    if payload.base_url is not None:
        eff_iface = payload.interface_type or provider.interface_type
        provider.base_url = (
            payload.base_url.strip() if eff_iface == "antigravity" else (normalize_base_url(payload.base_url) or "")
        )
    if payload.api_key is not None:
        raw_key = payload.api_key.strip()
        if raw_key:
            provider.api_key_encrypted = encrypt_secret(raw_key)
            provider.api_key_hint = mask_api_key(raw_key)
        else:
            provider.api_key_encrypted = None
            provider.api_key_hint = None
    if payload.default_model is not None:
        provider.default_model = payload.default_model.strip()
    if payload.models_cache is not None:
        provider.models_cache = payload.models_cache
    if payload.extra_headers is not None:
        provider.extra_headers = payload.extra_headers
    if payload.enabled is not None:
        provider.enabled = payload.enabled

    await db.commit()
    await db.refresh(provider)
    invalidate_provider_cache()
    return _serialize_provider(provider)


async def delete_provider(db: AsyncSession, provider_id: str) -> bool:
    provider = await db.get(ModelProvider, provider_id)
    if not provider:
        return False
    # Explicitly clear role bindings referencing this provider (dialect-safe)
    bound_rows = (
        await db.execute(select(ModelRoleBinding).where(ModelRoleBinding.provider_id == provider_id))
    ).scalars().all()
    for row in bound_rows:
        await db.delete(row)
    await db.delete(provider)
    await db.commit()
    invalidate_provider_cache()
    return True


async def test_provider(db: AsyncSession, payload: ProviderTestRequest) -> ProviderTestResponse:
    provider: ModelProvider | None = None
    api_key = (payload.api_key or "").strip()
    base_url = payload.base_url
    interface_type = payload.interface_type
    preset_key = payload.preset_key
    model = payload.model
    headers = dict(payload.extra_headers or {})

    if payload.provider_id:
        provider = await db.get(ModelProvider, payload.provider_id)
        if provider:
            if not api_key:
                api_key = decrypt_secret(provider.api_key_encrypted)
            if not base_url:
                base_url = provider.base_url
            interface_type = provider.interface_type
            preset_key = provider.preset_key
            if not model:
                model = provider.default_model
            if provider.extra_headers:
                headers = {**provider.extra_headers, **headers}

    preset = PRESET_BY_KEY.get(preset_key)
    if preset:
        if not base_url:
            base_url = preset.base_url
        if not model:
            model = preset.default_model
        headers = {**preset.extra_headers, **headers}

    result = await probe_provider_connection(
        interface_type=interface_type,
        base_url=base_url,
        api_key=api_key,
        model=model,
        extra_headers=headers,
        preset_key=preset_key,
    )

    if provider:
        provider.last_test_status = "ok" if result["ok"] else "error"
        provider.last_test_message = str(result["message"])[:500]
        provider.last_tested_at = datetime.now()
        if result["models"]:
            merged = list(dict.fromkeys([*(result["models"] or []), *(provider.models_cache or [])]))
            provider.models_cache = merged[:250]
        await db.commit()
        invalidate_provider_cache()

    return ProviderTestResponse(**result)


async def update_role_binding(
    db: AsyncSession, role: str, payload: RoleBindingUpdateRequest
) -> RoleBindingItem:
    if role not in VALID_ROLES:
        raise ValueError(f"Unsupported role: {role}")

    binding = await db.get(ModelRoleBinding, role)
    if not payload.provider_id:
        if binding:
            await db.delete(binding)
            await db.commit()
    else:
        provider = await db.get(ModelProvider, payload.provider_id)
        if not provider:
            raise ValueError("Provider not found")
        model_id = (payload.model_id or provider.default_model or "").strip() or None
        if binding:
            binding.provider_id = provider.id
            binding.model_id = model_id
            if payload.params is not None:
                binding.params = payload.params
        else:
            binding = ModelRoleBinding(
                role=role,
                provider_id=provider.id,
                model_id=model_id,
                params=payload.params or None,
            )
            db.add(binding)
        await db.commit()

    invalidate_provider_cache()
    eff = resolve_role_config(role)
    p = await db.get(ModelProvider, payload.provider_id) if payload.provider_id else None
    return RoleBindingItem(
        role=role,
        provider_id=p.id if p else None,
        provider_name=p.name if p else None,
        preset_key=p.preset_key if p else None,
        model_id=(payload.model_id or (p.default_model if p else None)) if p else None,
        params=dict(payload.params or {}),
        effective_source=eff.source,
        effective_provider=eff.provider_name,
        effective_model=eff.model,
        effective_base_url=eff.base_url,
    )
