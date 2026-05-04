from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterState(BaseModel):
    name: str = Field(description="Character name")
    outfit: str | None = Field(default=None, description="Current outfit/clothing description")
    emotion: str | None = Field(default=None, description="Current emotional state")
    posture: str | None = Field(default=None, description="Body posture/pose description")


class Dialogue(BaseModel):
    speaker: str = Field(description="Who is speaking")
    text: str = Field(description="Dialogue text content")
    type: str = Field(default="speech", description="speech|thought|narration|sfx")


class Panel(BaseModel):
    panel_id: str = Field(description="Unique panel identifier within the page, e.g. '1-2'")
    scene: str = Field(description="Scene/location description")
    characters: list[CharacterState] = Field(default_factory=list, description="Characters in this panel")
    camera: str = Field(
        default="medium",
        description="Camera shot type: close-up|medium|wide|bird-eye|low-angle|high-angle",
    )
    mood: str | None = Field(default=None, description="Overall mood/atmosphere of the panel")
    dialogue: list[Dialogue] = Field(default_factory=list, description="Dialogue bubbles in this panel")
    prompt: str = Field(description="Image generation prompt for this panel")
    negative_prompt: str | None = Field(default=None, description="Negative prompt for image generation")


class Page(BaseModel):
    page_number: int = Field(description="Page number (1-based)")
    layout: str = Field(default="2x2", description="Page layout template: 1x1|2x2|3_panels|4_panels|splash")
    panels: list[Panel] = Field(description="Panels on this page")


class Storyboard(BaseModel):
    title: str = Field(description="Episode title")
    synopsis: str = Field(description="Brief episode synopsis/outline")
    tone: str = Field(default="main", description="Episode tone: main|daily|climax|filler|pit_resolve")
    pages: list[Page] = Field(description="Pages in this episode")
