from __future__ import annotations

from pydantic import BaseModel, Field


class Event(BaseModel):
    description: str = Field(description="What happened in this event")
    characters_involved: list[str] = Field(default_factory=list, description="Characters involved")
    significance: str = Field(default="normal", description="normal|major|turning_point|cliffhanger")


class StateChange(BaseModel):
    character: str = Field(description="Character whose state changed")
    attribute: str = Field(description="What changed: injury|relationship|location|possession|ability|knowledge")
    before: str | None = Field(default=None, description="Previous state")
    after: str = Field(description="New state")
    reason: str | None = Field(default=None, description="Why the change happened")


class NewAsset(BaseModel):
    name: str = Field(description="Asset name")
    asset_type: str = Field(description="character|outfit|location|item|style")
    description: str = Field(description="Detailed description of the asset")
    visual_tags: list[str] = Field(default_factory=list, description="Visual description tags for image generation")


class PitDiscovery(BaseModel):
    description: str = Field(description="Foreshadowing/pit description")
    priority: str = Field(default="medium", description="low|medium|high")
    trigger_hint: str | None = Field(default=None, description="When should this pit be resolved")


class DialogueLine(BaseModel):
    speaker: str = Field(default="", description="Speaker name, empty for narration")
    text: str = Field(description="The line as written in the manga, in the original language")
    line_type: str = Field(default="speech", description="speech|thought|narration|sfx")


class PageDialogue(BaseModel):
    page_number: int = Field(description="Page number the lines belong to")
    lines: list[DialogueLine] = Field(
        default_factory=list, description="Dialogue/narration on this page, in reading order"
    )


class CharacterSighting(BaseModel):
    name: str = Field(description="Character name as used in this episode")
    asset_id: str | None = Field(
        default=None,
        description="ID of the matching known character asset from the provided list, null if unrecognized",
    )
    appearance: str | None = Field(default=None, description="Outfit/look this episode, for visual consistency")
    role: str = Field(default="", description="protagonist|support|antagonist|cameo")


class EpisodeUnderstanding(BaseModel):
    summary: str = Field(description="Episode summary/synopsis")
    events: list[Event] = Field(default_factory=list, description="Key events in chronological order")
    state_changes: list[StateChange] = Field(default_factory=list, description="Character state changes")
    characters: list[CharacterSighting] = Field(
        default_factory=list, description="Characters appearing in this episode, linked to known assets when possible"
    )
    new_assets: list[NewAsset] = Field(default_factory=list, description="Newly discovered assets")
    pit_discoveries: list[PitDiscovery] = Field(default_factory=list, description="Foreshadowing/pits discovered")
    resolved_pits: list[str] = Field(
        default_factory=list,
        description="IDs of open pits (from the provided list) that this episode clearly resolves",
    )
    page_dialogues: list[PageDialogue] = Field(
        default_factory=list, description="Transcribed dialogue/narration per page, original language"
    )
