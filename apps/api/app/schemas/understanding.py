from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, model_validator


def _coerce_nested_json(data: Any) -> Any:
    """Coerce stringified JSON objects/arrays emitted by OpenAI-compatible tool-calling models (e.g. GLM/Qwen)."""
    if isinstance(data, str):
        s = data.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return data
        return data
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if isinstance(v, str):
                sv = v.strip()
                if (sv.startswith("{") and sv.endswith("}")) or (sv.startswith("[") and sv.endswith("]")):
                    try:
                        out[k] = json.loads(sv)
                        continue
                    except json.JSONDecodeError:
                        pass
            out[k] = v
        return out
    if isinstance(data, list):
        return [_coerce_nested_json(item) for item in data]
    return data


class _CoercedBaseModel(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _unwrap_json_strings(cls, data: Any) -> Any:
        return _coerce_nested_json(data)


class Event(_CoercedBaseModel):
    description: str = Field(description="What happened in this event")
    characters_involved: list[str] = Field(default_factory=list, description="Characters involved")
    location: str | None = Field(default=None, description="Scene/location where this event happens")
    items_involved: list[str] = Field(default_factory=list, description="Key items/props involved in this event")
    significance: str = Field(default="normal", description="normal|major|turning_point|cliffhanger")


class StateChange(_CoercedBaseModel):
    character: str = Field(description="Character or item whose state changed")
    attribute: str = Field(description="What changed: injury|relationship|location|possession|ability|knowledge|status")
    before: str | None = Field(default=None, description="Previous state")
    after: str = Field(description="New state")
    reason: str | None = Field(default=None, description="Why the change happened")


class CharacterSighting(_CoercedBaseModel):
    name: str = Field(description="Canonical character name as used in this episode")
    asset_id: str | None = Field(
        default=None,
        description="ID of the matching known character asset from the provided list, null if genuinely new",
    )
    aliases: list[str] = Field(default_factory=list, description="Nicknames, titles, or how others address them")
    appearance: str | None = Field(
        default=None,
        description="Detailed visual appearance & outfit in this episode (hair, eyes, build, clothing)",
    )
    speech_style: str | None = Field(
        default=None,
        description="Speech pattern, tone, pronouns, or catchphrases observed in their dialogue",
    )
    role: str = Field(default="", description="protagonist|support|antagonist|cameo")
    source_page: int | None = Field(
        default=None,
        description="1-based episode page number showing the clearest portrait/view of this character",
    )
    bbox: list[int] | None = Field(
        default=None,
        description="Bounding box [ymin, xmin, ymax, xmax] normalized 0-1000 on source_page for the character portrait",
    )


class AssetSighting(_CoercedBaseModel):
    asset_id: str = Field(description="ID of the matching known item/location/outfit asset from the provided list")
    name: str = Field(description="Asset name")
    asset_type: str = Field(default="item", description="item|location|outfit|style")
    state_note: str | None = Field(
        default=None,
        description="How this item/location appears or changes in this episode",
    )


class NewAsset(_CoercedBaseModel):
    name: str = Field(description="Asset name (keep in the manga's language)")
    asset_type: str = Field(description="character|outfit|location|item|style")
    description: str = Field(
        description="Rich visual & narrative description detailed enough to reproduce consistently in image prompts"
    )
    visual_tags: list[str] = Field(
        default_factory=list,
        description="Specific English visual tags (colors, shapes, materials, lighting, clothing details)",
    )
    owner_or_context: str | None = Field(
        default=None,
        description="Who owns/wears this asset or where this location belongs in the world",
    )
    source_page: int | None = Field(
        default=None,
        description="1-based episode page number where this asset is most clearly visible",
    )
    bbox: list[int] | None = Field(
        default=None,
        description="Bounding box [ymin, xmin, ymax, xmax] normalized 0-1000 on source_page around this asset",
    )


class PitDiscovery(_CoercedBaseModel):
    title: str = Field(default="", description="Concise title for the foreshadowing/mystery (under 30 chars)")
    description: str = Field(description="Detailed description of the foreshadowing, mystery, promise, or plot hook")
    priority: str = Field(default="medium", description="low|medium|high (high = core main-plot mystery)")
    trigger_hint: str | None = Field(default=None, description="Condition or future moment when this pit may pay off")
    related_characters: list[str] = Field(default_factory=list, description="Characters tied to this foreshadowing")


class PitProgression(_CoercedBaseModel):
    pit_id: str = Field(description="ID of an open pit from the provided list that received new clues/progress")
    clue: str = Field(description="What new clue, development, or partial reveal happened in this episode")


class MainPlotUpdate(_CoercedBaseModel):
    core_conflict: str = Field(
        default="",
        description="Overarching main plotline / central conflict or mystery driving the series so far",
    )
    current_arc: str = Field(
        default="",
        description="Name and focus of the current story arc / chapter group",
    )
    protagonist_goal: str = Field(
        default="",
        description="What the protagonist(s) currently want or must do next",
    )
    arc_progress: str = Field(
        default="",
        description="How this specific episode advanced the main storyline or character relationships",
    )
    next_hook: str = Field(
        default="",
        description="Immediate narrative hook or unresolved tension leading into the next episode",
    )


class EndingState(_CoercedBaseModel):
    location: str = Field(default="", description="Exact location/scene at the end of the final page")
    time_and_mood: str = Field(default="", description="Time of day and emotional atmosphere at the ending")
    active_characters: list[str] = Field(default_factory=list, description="Characters present on the final page")
    cliffhanger: str = Field(
        default="",
        description="Exact action, reveal, or line on the final page that the next episode must continue from",
    )


class DialogueLine(_CoercedBaseModel):
    speaker: str = Field(default="", description="Speaker name, empty for narration/sfx")
    text: str = Field(description="The line as written in the manga, in the original language")
    line_type: str = Field(default="speech", description="speech|thought|narration|sfx")


class PageDialogue(_CoercedBaseModel):
    page_number: int = Field(description="Page number the lines belong to")
    lines: list[DialogueLine] = Field(
        default_factory=list, description="Dialogue/narration on this page, in reading order"
    )


class EpisodeUnderstanding(_CoercedBaseModel):
    @model_validator(mode="before")
    @classmethod
    def _unwrap_json_strings(cls, data: Any) -> Any:
        return _coerce_nested_json(data)

    summary: str = Field(description="Comprehensive episode synopsis covering beginning, turning points, and ending")
    main_plot: MainPlotUpdate = Field(
        default_factory=MainPlotUpdate,
        description="Main storyline, current arc, protagonist goal, and narrative hook",
    )
    ending_state: EndingState = Field(
        default_factory=EndingState,
        description="Exact scene and cliffhanger state at the end of this episode for seamless continuation",
    )
    art_style_notes: str = Field(
        default="",
        description="Visual art style observed (e.g. B&W manga with screentones vs color webtoon, linework, shading)",
    )
    world_rules_discovered: list[str] = Field(
        default_factory=list,
        description="New worldbuilding rules, magic/power mechanics, or setting facts revealed in this episode",
    )
    events: list[Event] = Field(default_factory=list, description="Key events in strict chronological order")
    state_changes: list[StateChange] = Field(
        default_factory=list, description="Persistent character/item state changes"
    )
    characters: list[CharacterSighting] = Field(
        default_factory=list,
        description="Every character appearing in this episode, linked to known character assets when matched",
    )
    asset_sightings: list[AssetSighting] = Field(
        default_factory=list,
        description="Known items, locations, or outfits from the provided list that appear in this episode",
    )
    new_assets: list[NewAsset] = Field(
        default_factory=list,
        description="Newly discovered characters, key items/props, recurring locations, or signature outfits",
    )
    pit_discoveries: list[PitDiscovery] = Field(
        default_factory=list, description="New foreshadowing, mysteries, or plot threads planted"
    )
    pit_progressions: list[PitProgression] = Field(
        default_factory=list,
        description="Existing open pits that gained new clues/progress without being fully resolved yet",
    )
    resolved_pits: list[str] = Field(
        default_factory=list,
        description="IDs of open pits (from the provided list) that this episode clearly resolves",
    )
    page_dialogues: list[PageDialogue] = Field(
        default_factory=list, description="Transcribed dialogue/narration per page, original language"
    )
