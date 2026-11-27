from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CHAR, JSON, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModelProvider(Base):
    """User-configured AI model provider stored in DB (Web UI managed, supersedes .env)."""

    __tablename__ = "model_providers"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    preset_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="openrouter|openai|anthropic|gemini|glm_coding|glm|kimi|deepseek|qwen|comfyui|custom",
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    interface_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="openai_compatible",
        comment="openai_compatible|gemini_image|comfyui|antigravity|mock",
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_model: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    models_cache: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    extra_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_test_status: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="ok|error")
    last_test_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(6), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ModelRoleBinding(Base):
    """Maps a MangaForge task role (main_llm | vision_llm | image_gen | embedding) to a provider & model."""

    __tablename__ = "model_role_bindings"

    role: Mapped[str] = mapped_column(String(32), primary_key=True, comment="main_llm|vision_llm|image_gen|embedding")
    provider_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("model_providers.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False, server_default=func.now(), onupdate=func.now()
    )
