from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FlowBrowser(Base):
    __tablename__ = "flow_browsers"

    provider_id: Mapped[str] = mapped_column(ForeignKey("model_providers.id", ondelete="CASCADE"), primary_key=True)
    pair_hash: Mapped[str | None] = mapped_column(String(64))
    pair_until: Mapped[datetime | None] = mapped_column(DateTime)
    session_id: Mapped[str | None] = mapped_column(String(36))
    token_hash: Mapped[str | None] = mapped_column(String(64))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    ready: Mapped[bool] = mapped_column(Boolean, default=False)


class FlowBrowserJob(Base):
    """Persistent commands shared by FastAPI, the generation workers and a paired Chrome connector."""

    __tablename__ = "flow_browser_jobs"
    __table_args__ = (Index("ix_flow_browser_queue", "provider_id", "session_id", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("flow_browsers.provider_id", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    runner: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class FlowExtensionKey(Base):
    __tablename__ = "flow_extension_keys"

    provider_id: Mapped[str] = mapped_column(
        ForeignKey("flow_browsers.provider_id", ondelete="CASCADE"), primary_key=True
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    account_hash: Mapped[str | None] = mapped_column(String(64))  # Nullable legacy column from extension 1.0.
    installation: Mapped[str | None] = mapped_column(String(36))
