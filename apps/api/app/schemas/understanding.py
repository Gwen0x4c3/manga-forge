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


class EpisodeUnderstanding(BaseModel):
    summary: str = Field(description="Episode summary/synopsis")
    events: list[Event] = Field(default_factory=list, description="Key events in chronological order")
    state_changes: list[StateChange] = Field(default_factory=list, description="Character state changes")
    new_assets: list[NewAsset] = Field(default_factory=list, description="Newly discovered assets")
    pit_discoveries: list[PitDiscovery] = Field(default_factory=list, description="Foreshadowing/pits discovered")
