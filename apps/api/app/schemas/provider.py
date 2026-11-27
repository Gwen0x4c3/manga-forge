from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProviderCreateRequest(BaseModel):
    preset_key: str = Field(default="custom", max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    interface_type: str = Field(default="openai_compatible", max_length=32)
    base_url: str = Field(default="", max_length=500)
    api_key: str | None = Field(default=None)
    default_model: str = Field(default="", max_length=160)
    models_cache: list[str] | None = None
    extra_headers: dict[str, str] | None = None
    enabled: bool = True
    activate_roles: list[str] | None = Field(
        default=None, description="Optional roles to immediately bind: main_llm|vision_llm|image_gen|embedding"
    )


class ProviderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    interface_type: str | None = Field(default=None, max_length=32)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, description="Omit to keep existing key; empty string clears key")
    default_model: str | None = Field(default=None, max_length=160)
    models_cache: list[str] | None = None
    extra_headers: dict[str, str] | None = None
    enabled: bool | None = None


class ProviderTestRequest(BaseModel):
    provider_id: str | None = None
    preset_key: str = "custom"
    interface_type: str = "openai_compatible"
    base_url: str = ""
    api_key: str | None = None
    model: str | None = None
    extra_headers: dict[str, str] | None = None


class ProviderTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    message: str
    models: list[str] = Field(default_factory=list)


class ModelProviderResponse(BaseModel):
    flow_status: str | None = None
    id: str
    preset_key: str
    name: str
    interface_type: str
    base_url: str
    has_api_key: bool
    api_key_masked: str
    default_model: str
    models_cache: list[str] = Field(default_factory=list)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_tested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RoleBindingItem(BaseModel):
    role: str
    provider_id: str | None = None
    provider_name: str | None = None
    preset_key: str | None = None
    model_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    effective_source: str = "env"  # "database" | "env"
    effective_provider: str = ""
    effective_model: str = ""
    effective_base_url: str | None = None


class RoleBindingUpdateRequest(BaseModel):
    provider_id: str | None = None
    model_id: str | None = None
    params: dict[str, Any] | None = None


class ProviderOverviewResponse(BaseModel):
    presets: list[dict[str, Any]]
    providers: list[ModelProviderResponse]
    roles: list[RoleBindingItem]
