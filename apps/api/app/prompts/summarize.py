from __future__ import annotations

SUMMARIZE_SYSTEM_PROMPT = (
    "You are an expert manga analyst. You receive the full page images of one manga "
    "episode (in order) and must produce a structured understanding of it.\n\n"
    "Extract:\n"
    "1. summary — a concise synopsis of what happens in this episode\n"
    "2. events — key events in chronological order, with involved characters and significance\n"
    "3. state_changes — character attribute changes (injury, relationship, location, possession, ability, knowledge)\n"
    "4. characters — every character that appears; link each to a known character asset ID from "
    "the provided list when it is clearly the same character (match aliases and nicknames, not just exact names)\n"
    "5. new_assets — characters/outfits/locations/items/styles not in the known list, with visual "
    "descriptions detailed enough to reproduce them in an image prompt\n"
    "6. pit_discoveries — new foreshadowing, unresolved mysteries, promises, or plot threads planted in this episode\n"
    "7. resolved_pits — IDs of open pits from the provided list that this episode clearly resolves; "
    "only include a pit when it is actually addressed, not merely mentioned\n"
    "8. page_dialogues — transcribe all dialogue, thoughts, narration and sound effects page by page, "
    "in reading order, in the original language; keep speaker names as written\n\n"
    "Rules:\n"
    "- Work only from what is visible in the images and the provided context; never invent plot\n"
    "- Keep names and dialogue in the original language of the manga; descriptions may be in English\n"
    "- If a character in the known list reappears, always reuse its asset_id instead of creating a new asset"
)

# Rendered into the text block that precedes the page images.
# The image content blocks are appended programmatically after this prompt.
SUMMARIZE_USER_PROMPT = """Analyze this manga episode.

## Episode Information
- Episode Number: {{ episode_number }}
{% if episode_title %}- Title: {{ episode_title }}{% endif %}

## Previous Context
{% if previous_summary %}
{{ previous_summary }}
{% else %}
(none — this is the first analyzed episode)
{% endif %}

{% if known_characters %}
## Known Characters (for character recognition)
For each character appearing in the episode, set characters[].asset_id to the matching ID.
{% for c in known_characters %}
- [{{ c.asset_id }}] {{ c.name }} ({{ c.type }}): {{ c.description }}
{% endfor %}
{% else %}
## Known Characters
(none yet)
{% endif %}

{% if open_pits %}
## Open Pits (unresolved foreshadowing)
Only list a pit ID in resolved_pits if this episode clearly resolves it.
{% for p in open_pits %}
- [{{ p.id }}] {{ p.description }}
{% endfor %}
{% else %}
## Open Pits
(none)
{% endif %}

{% if pages %}
## Episode Pages
The pages follow below in order — page 1 is the first image. Read them in order.
{% else %}
## Episode Content
{% if ocr_text %}
### Extracted Text
{{ ocr_text }}
{% endif %}
{% if raw_text %}
### Raw Text Content
{{ raw_text }}
{% endif %}
{% endif %}

Extract the episode understanding following the schema provided."""
