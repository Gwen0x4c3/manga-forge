from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.understanding import _coerce_nested_json


class _JsonCoercedModel(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _unwrap_json_strings(cls, data: Any) -> Any:
        return _coerce_nested_json(data)


class CharacterState(_JsonCoercedModel):
    name: str = Field(description="Character name (must match established character name)")
    outfit: str | None = Field(default=None, description="Current outfit/clothing description")
    emotion: str | None = Field(default=None, description="Current facial expression and emotional state")
    posture: str | None = Field(default=None, description="Body action/pose in this panel")


class Dialogue(_JsonCoercedModel):
    speaker: str = Field(default="", description="Who is speaking (empty for narration/sfx)")
    text: str = Field(description="Dialogue text in the manga's language")
    type: str = Field(default="speech", description="speech|thought|narration|sfx")
    speaker_position: str = Field(
        default="top-right",
        description="Bubble corner inside panel: top-right|top-left|bottom-right|bottom-left",
    )


class Panel(_JsonCoercedModel):
    panel_id: str = Field(description="Unique panel identifier within the episode, e.g. '1-1', '1-2'")
    scene: str = Field(description="Specific visual action and staging happening in this panel")
    location: str | None = Field(default=None, description="Established location name if applicable")
    items: list[str] = Field(default_factory=list, description="Key props/items visible in this panel")
    characters: list[CharacterState] = Field(default_factory=list, description="Characters visible in this panel")
    camera: str = Field(
        default="medium",
        description="Camera shot type: close-up|medium|wide|bird-eye|low-angle|high-angle|over-shoulder",
    )
    mood: str | None = Field(default=None, description="Lighting and emotional atmosphere of the panel")
    dialogue: list[Dialogue] = Field(default_factory=list, description="Ordered dialogue/narration bubbles")
    prompt: str = Field(
        description=(
            "Detailed English image generation prompt (composition, characters' visual traits, "
            "action, environment, lighting, manga art style; NO speech bubbles or text)"
        )
    )
    negative_prompt: str | None = Field(
        default="speech bubble, text, watermark, signature, blurry, deformed anatomy",
        description="Negative prompt for image generation",
    )


class Page(_JsonCoercedModel):
    page_number: int = Field(description="Page number (1-based)")
    layout: str = Field(
        default="3_panels",
        description="splash|2_vertical|2_cinematic|3_panels|3_vertical|2x2|4_manga_dynamic|5_panels",
    )
    panels: list[Panel] = Field(description="Panels on this page (count should match layout)")


class Storyboard(_JsonCoercedModel):
    title: str = Field(description="Episode title in the manga's language")
    synopsis: str = Field(description="Episode synopsis covering setup, development, climax, and ending hook")
    arc_connection: str = Field(
        default="",
        description="How this episode bridges from the previous episode's ending and advances the main plotline",
    )
    addressed_pit_ids: list[str] = Field(
        default_factory=list,
        description="IDs of active pits advanced or resolved in this episode",
    )
    tone: str = Field(default="main", description="Episode tone: main|daily|climax|filler|pit_resolve")
    pages: list[Page] = Field(description="Pages in this episode (typically 4-8 pages with varied pacing)")
