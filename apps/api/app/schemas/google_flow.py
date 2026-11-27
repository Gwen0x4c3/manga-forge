from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, StringConstraints

VideoModel = Literal["veo-3.1-lite", "omni-flash-1.2"]
Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class FlowOptions(BaseModel):
    model: VideoModel = "veo-3.1-lite"
    pages_per_clip: Literal[1, 2] = 2
    aspect_ratio: Literal["landscape", "portrait"] = "landscape"


class FlowStart(FlowOptions):
    request_id: UUID = Field(default_factory=uuid4)
    provider_id: str
    connection_id: str | None = None
    mode: Literal["sync", "video"] = "video"
    plan_id: str
    prompts: list[Prompt] | None = None


class FlowAccount(BaseModel):
    id: str
    name: str
    status: Literal["unpaired", "offline", "login_required", "ready"]
    connection_id: str | None


class FlowSource(BaseModel):
    key: str
    label: str
    kind: str


class FlowShot(BaseModel):
    label: str
    prompt: str
    references: list[str]


class FlowPlan(BaseModel):
    plan_id: str = ""
    sources: list[FlowSource]
    shots: list[FlowShot]
