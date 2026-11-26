# ruff: noqa: E501
from __future__ import annotations

SCRIPT_GENERATE_SYSTEM_PROMPT = (
    "You are a master serialized manga scriptwriter and storyboard director. "
    "Your task is to write a compelling, canon-faithful, visually cinematic storyboard script "
    "for the next episode of an ongoing manga series.\n\n"
    "Core Directives:\n"
    "1. SEAMLESS CONTINUITY — Pick up naturally from the Previous Episode Bridge (exact ending scene, "
    "cliffhanger, character states, and emotional momentum). Never contradict established events or states.\n"
    "2. MAIN PLOT & FORESHADOWING — Advance the Main Plotline / Current Arc meaningfully. Weave open pits "
    "(foreshadowing) naturally: pay off pits whose trigger conditions are met, plant subtle clues for high-priority "
    "mysteries, and list advanced/resolved pit IDs in `addressed_pit_ids`.\n"
    "3. CHARACTER VOICE & PERSONALITY — Write dialogue in the manga's target language matching each character's "
    "established personality, relationships, forms of address, and speech samples.\n"
    "4. MANGA PACING & LAYOUTS — Structure 4 to 6 pages with varied dramatic rhythm:\n"
    "   - `3_panels` (3 panels: wide establishing/action top + 2 bottom panels)\n"
    "   - `2x2` or `4_manga_dynamic` (4 panels: crisp dialogue/action progression)\n"
    "   - `2_cinematic` or `2_vertical` (2 large high-impact panels)\n"
    "   - `5_panels` (5 panels: fast-paced exchange or montage)\n"
    "   - `splash` (1 full-page dramatic reveal or climax)\n"
    "   CRITICAL: The number of panels in `page.panels` MUST match the chosen `page.layout` "
    "(splash=1, 2_*=2, 3_*=3, 2x2/4_*=4, 5_panels=5)!\n"
    "5. IMAGE PROMPTS — Write `panel.prompt` in detailed English describing: camera angle, character visual traits "
    "(hair, eyes, outfit from Character Dossier), pose/expression, key items/props, environment/lighting, and "
    "the series' exact manga art style. NEVER ask for speech bubbles or written text inside `panel.prompt` "
    "(lettering is composited separately by the layout engine).\n"
    "6. BUBBLE PLACEMENT — Set `dialogue[].speaker_position` (`top-right`, `top-left`, `bottom-right`, `bottom-left`) "
    "to alternate cleanly across speakers in a panel.\n"
    "7. VITAL STATUS & DEATH LOCK — Characters marked `deceased` MUST NOT appear alive in present-day scenes "
    "(only in explicitly labeled flashbacks, memories, or spirits if canon allows). Sealed or missing characters "
    "cannot walk in casually without an explicit plot event explaining their return."
)

SCRIPT_GENERATE_USER_PROMPT = """Create the storyboard script for Episode {{ episode_number }}.

## Project & Style Profile
- Series Title: {{ project_title }}
- Dialogue Language: {{ language_label }} (ALL title, synopsis, scene notes, and dialogue MUST be in {{ language_label }}; image `prompt` MUST be in English)
- Visual Art Style: {{ art_style or "Serialized manga style, clean ink linework, expressive characters, consistent visual tone" }}

## Main Plotline & Current Story Arc
{% if story_bible and story_bible.get('main_plot') %}
{% set mp = story_bible.get('main_plot') %}
- Core Conflict / Main Line: {{ mp.get('core_conflict') or '(see long summary)' }}
- Current Arc: {{ mp.get('current_arc') or '(ongoing)' }}
- Protagonist Goal: {{ mp.get('protagonist_goal') or '(ongoing)' }}
- Immediate Hook to Follow Up: {{ mp.get('next_hook') or '(continue from recent episode)' }}
{% else %}
(Derive main plotline directly from Long-term Summary and Recent Episodes below)
{% endif %}

## World Canon & Established Rules
{% if canon_rules %}
{{ canon_rules }}
{% else %}
(Follow world logic established in the episodes below)
{% endif %}

## Rolling Historical Summary
{% if long_summary %}
{{ long_summary }}
{% else %}
(See recent episodes below)
{% endif %}

{% if previous_bridge %}
## Immediate Bridge from Previous Episode (Episode {{ previous_bridge.episode_number }}{% if previous_bridge.title %}: {{ previous_bridge.title }}{% endif %})
{% if previous_bridge.ending_state %}
- Ending Location: {{ previous_bridge.ending_state.get('location') or 'unknown' }}
- Ending Atmosphere: {{ previous_bridge.ending_state.get('time_and_mood') or 'continuous' }}
- Characters Present at Ending: {{ (previous_bridge.ending_state.get('active_characters') or []) | join(', ') }}
- Cliffhanger / Final Moment: {{ previous_bridge.ending_state.get('cliffhanger') or previous_bridge.summary }}
{% endif %}
{% if previous_bridge.key_events %}
- Key Events in Previous Episode:
{% for ev in previous_bridge.key_events %}
  * [{{ ev.significance }}] {{ ev.description }}
{% endfor %}
{% endif %}
{% if previous_bridge.closing_dialogue %}
- Final Dialogue Lines of Previous Episode (match tone & immediate context):
{% for line in previous_bridge.closing_dialogue %}
  * {{ line }}
{% endfor %}
{% endif %}
{% endif %}

## Recent Episodes Window (Chronological)
{% for ep in recent_episodes %}
### Episode {{ ep.number }}{% if ep.title %}: {{ ep.title }}{% endif %}
Summary: {{ ep.summary }}
{% if ep.events %}
Key Beats: {% for e in ep.events %}{{ e.description }}{% if not loop.last %} → {% endif %}{% endfor %}
{% endif %}
{% if ep.state_changes %}
State Changes:
{% for change in ep.state_changes %}
- {{ change.character }} ({{ change.attribute }}): {{ change.before or '?' }} → {{ change.after }}{% if change.reason %} ({{ change.reason }}){% endif %}
{% endfor %}
{% endif %}
{% endfor %}

## Character Dossier (Cumulative State & Authentic Voice)
{% if character_dossier %}
{% for char in character_dossier %}
- **{{ char.name }}**{% if char.role %} [{{ char.role }}]{% endif %}{% if char.vital_status and char.vital_status != 'alive' %} [STATUS: {{ char.vital_status | upper }}{% if char.vital_status_episode %} since Ep {{ char.vital_status_episode }}{% endif %}]{% endif %}: {{ char.description }}
  {% if char.visual_tags %}Visual Tags: {{ char.visual_tags | join(', ') }}{% endif %}
  {% if char.current_state %}Current State: {{ char.current_state }}{% endif %}
  {% if char.speech_style %}Speech Style: {{ char.speech_style }}{% endif %}
  {% if char.speech_samples %}Sample Lines: {{ char.speech_samples | join(' / ') }}{% endif %}
{% endfor %}
{% else %}
(No character dossier yet)
{% endif %}

{% if unavailable_characters %}
## Deceased / Unavailable Characters (STRICT CONTINUITY LOCK)
{% for uc in unavailable_characters %}
- **{{ uc.name }}** — **{{ uc.vital_status | upper }}**{% if uc.vital_status_episode %} (since Episode {{ uc.vital_status_episode }}){% endif %}{% if uc.vital_status_note %}: {{ uc.vital_status_note }}{% endif %}. DO NOT depict alive in present-day scenes unless explicitly framed as a flashback or canon revival.
{% endfor %}
{% endif %}

## Key Locations, Props & Outfits (Keep Visual Descriptions Consistent)
{% if world_assets %}
{% for asset in world_assets %}
- [{{ asset.type }}] **{{ asset.name }}**: {{ asset.description }}{% if asset.visual_tags %} (tags: {{ asset.visual_tags | join(', ') }}){% endif %}
{% endfor %}
{% else %}
(None registered yet)
{% endif %}

{% if rag_memories %}
## Retrieved Long-Range Memories (Earlier Chapters)
{% for memory in rag_memories %}
- [Ep {{ memory.episode_number }} · {{ memory.type }}] {{ memory.content }}
{% endfor %}
{% endif %}

## Active Foreshadowing & Plot Threads (Pits)
{% if active_pits %}
{% for pit in active_pits %}
- [ID: {{ pit.id }}] [Priority: {{ pit.priority_label }}] {{ pit.description }}{% if pit.trigger_hint %} (Trigger: {{ pit.trigger_hint }}){% endif %}{% if pit.clues %} | Clues so far: {{ pit.clues | join('; ') }}{% endif %}
{% endfor %}
{% else %}
(No open pits)
{% endif %}

## Episode Generation Directive
- Target Episode Number: {{ episode_number }}
- Narrative Mode / Tone: {{ tone }}
{% if tone == 'pit_resolve' %}- Focus: Actively pay off or significantly advance high-priority open foreshadowing!{% endif %}
{% if tone == 'climax' %}- Focus: High-stakes dramatic confrontation, turning point, and impactful splash/cinematic panels!{% endif %}
{% if tone == 'daily' %}- Focus: Character chemistry, slice-of-life warmth, subtle worldbuilding and relationship growth!{% endif %}
{% if custom_instructions %}
- Author's Custom Instructions (HIGHEST PRIORITY): {{ custom_instructions }}
{% endif %}

Generate the complete Storyboard JSON now."""
