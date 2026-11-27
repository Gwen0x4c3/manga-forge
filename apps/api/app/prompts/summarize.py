# ruff: noqa: E501
from __future__ import annotations

LANGUAGE_DISPLAY_NAMES: dict[str, str] = {
    "zh": "简体中文 (Simplified Chinese)",
    "zh-cn": "简体中文 (Simplified Chinese)",
    "zh-tw": "繁體中文 (Traditional Chinese)",
    "en": "English",
    "ja": "日本語 (Japanese)",
    "ko": "한국어 (Korean)",
}


def resolve_language_label(code: str | None) -> str:
    raw = (code or "zh").strip().lower()
    return LANGUAGE_DISPLAY_NAMES.get(raw, code or "简体中文 (Simplified Chinese)")


SUMMARIZE_SYSTEM_PROMPT = (
    "You are a senior manga editor and visual continuity analyst. "
    "You receive ordered page images of a serialized manga episode and extract a CRISP, HIGH-SIGNAL, "
    "low-noise structured understanding for downstream story continuation.\n\n"
    "CRITICAL GLOBAL RULES:\n"
    "1. OUTPUT LANGUAGE LOCK: You MUST write ALL text fields — summary, main_plot, ending_state, events, "
    "state_changes, character primary names, descriptions, relationship notes, world_rules_discovered, "
    "and pit descriptions — strictly in the project's Preferred Output Language (default: Simplified Chinese). "
    "NEVER mix Polish, random English, or Japanese sentences into Chinese summaries (only `visual_tags` stays in English).\n"
    "2. SKIP NON-STORY PAGES COMPLETELY: Ignore fan-translation/scanlation credit pages, recruitment banners, "
    "Discord promos, translator notes, publisher copyright pages, and blank covers. NEVER include scanlation group names "
    "(e.g. Dead-chan, Stripease) as characters, summaries, or foreshadowing!\n"
    "3. CHARACTER NAMING (TRANSLATED PRIMARY + ORIGINAL ALIASES): Always put the canonical name in the Preferred "
    "Output Language (e.g. '舅舅', '敬文', '精灵', '藤宫澄夏') in `name`, and put all original Japanese/English names "
    "or nicknames (e.g. ['おじさん', 'Uncle', '柴崎']) in `aliases`. Always reuse an existing `asset_id` whenever "
    "a known character appears!\n"
    "4. QUALITY OVER QUANTITY (STRICT ANTI-NOISE):\n"
    "   - characters & new_assets (character): ONLY register named characters or recurring plot-relevant characters. "
    "NEVER create assets for unnamed one-off background extras (nurses, passers-by, festival crowds, nameless thugs).\n"
    "   - new_assets (item / location / outfit): ONLY register plot-critical, magical/special, or signature recurring "
    "items/locations/outfits that are VISUALLY SHOWN on a page (ALWAYS provide `source_page` so a visual reference "
    "can be auto-cropped). Things merely mentioned in speech without being drawn belong in `summary` or `world_rules_discovered`, "
    "NOT `new_assets`. NEVER register ordinary mundane objects (teacups, chairs, shopping bags, radishes, generic clothes/phones).\n"
    "   - pit_discoveries (FORESHADOWING — STRICTLY 0 TO 2 MAX PER EPISODE): Less is more! Routine comedy/slice-of-life "
    "episodes should emit 0 pits. ONLY record major cross-episode mysteries, unfulfilled promises, curses, hidden identities, "
    "seals, or looming threats that genuinely matter in future chapters. NEVER record single-episode gags, resolved beats, "
    "or general world rules as pits.\n"
    "   - page_dialogues: Keep concise — extract only the 2 to 5 key story-driving or character-defining lines per page "
    "(skip trivial SFX, crowd noise, and scanlation credits).\n"
    "5. VITAL STATUS & CONTINUITY: If any character dies, is killed/slain, goes missing, is sealed, or revives, ALWAYS emit "
    "a state_change with attribute='vital_status' and after='deceased'|'missing'|'sealed'|'injured'|'alive'.\n"
    "6. VISUAL MATCHING & PORTRAIT CROPS: When character reference sheets (`参考图 [asset_id] 姓名`) are attached, match strictly by "
    "visual face/hair/glasses/build AND aliases. For each main character appearing clearly, ALWAYS provide `source_page` (1-based) "
    "and `bbox` `[ymin, xmin, ymax, xmax]` (0-1000 integer coordinates) around their clearest face/upper-body portrait so reference sheets "
    "can be auto-cropped for subsequent episodes. Keep `summary` crisp (2-4 sentences per window) and factual."
)

# Split user prompt into (1) an episode-wide IDENTICAL prefix (cacheable across all
# page chunks in the same episode along with character reference portraits) and
# (2) a per-chunk tail placed AFTER the shared prefix so LLM Prompt Caching achieves
# high hit rates (40-70%+) instead of invalidating on "Part 1/N" at line 1.
SUMMARIZE_SHARED_PREFIX_PROMPT = """Analyze this serialized manga episode cleanly and concisely.

## Output Language (MANDATORY)
- Preferred Output Language: **{{ preferred_language }}**
- Every narrative field (summary, events, character primary `name`, descriptions, world_rules, pit titles/descriptions) MUST be written in **{{ preferred_language }}**. Put original Japanese/English names into `aliases[]`. Keep `visual_tags` in English.

## Episode Information
- Episode Number: {{ episode_number }}
{% if episode_title %}- Title: {{ episode_title }}{% endif %}

## Main Plotline & Story Bible So Far
{% if main_plot %}
- Core Conflict: {{ main_plot.get('core_conflict', '') }}
- Current Arc: {{ main_plot.get('current_arc', '') }}
- Protagonist Goal: {{ main_plot.get('protagonist_goal', '') }}
- Previous Hook: {{ main_plot.get('next_hook', '') }}
{% else %}
(Not established yet — establish the foundational main plotline and current arc concisely in {{ preferred_language }})
{% endif %}

## Rolling Story Context
{% if previous_summary %}
{{ previous_summary }}
{% else %}
(none — this is the first analyzed episode)
{% endif %}

{% if known_characters %}
## Known Characters (MUST reuse `asset_id` when they reappear — do NOT create duplicates!)
{% if has_reference_sheets %}
Reference portraits (`参考图 [asset_id] Name (aliases)`) are attached right below BEFORE the episode pages. Match by face, hair, glasses, build, AND aliases.
{% else %}
Match characters by name, aliases, and visual descriptions below.
{% endif %}
{% for c in known_characters %}
- [{{ c.asset_id }}] {{ c.name }}{% if c.aliases %} (aliases: {{ c.aliases | join(', ') }}){% endif %}: {{ c.description }}
{% endfor %}
{% else %}
## Known Characters
(none yet — register ONLY named or recurring main characters, using {{ preferred_language }} primary names and original names in `aliases`)
{% endif %}

{% if known_other_assets %}
## Known Signature Items, Locations & Outfits (match via `asset_sightings[].asset_id`; do NOT re-create)
{% for a in known_other_assets %}
- [{{ a.asset_id }}] ({{ a.type }}) {{ a.name }}: {{ a.description }}
{% endfor %}
{% endif %}

{% if open_pits %}
## Open Pits (Major Unresolved Foreshadowing)
- If an open pit's core mystery/obstacle is directly answered or resolved here, put its exact ID in `resolved_pits`.
- Use `pit_progressions` only when a major new clue appears.
- For `pit_discoveries`: emit **0 to 2** genuinely major cross-episode mysteries ONLY (0 is preferred if nothing major is planted).
{% for p in open_pits %}
- [{{ p.id }}] (priority={{ p.priority }}) {{ p.description }}{% if p.trigger_hint %} | Hint: {{ p.trigger_hint }}{% endif %}
{% endfor %}
{% else %}
## Open Pits
(none yet — emit ONLY 0 to 2 truly major cross-episode mysteries/hooks; skip gags and minor details)
{% endif %}"""

SUMMARIZE_CHUNK_TAIL_PROMPT = """## Current Page Window
{% if chunk_info %}- Page Window: {{ chunk_info }}{% endif %}
{% if intra_episode_context %}
- Earlier Pages in This Episode:
{{ intra_episode_context }}
{% endif %}
{% if pages %}
Episode pages follow in strict reading order (`第 N 页`). Skip any scanlation credit/recruitment pages completely.
{% endif %}
{% if ocr_text %}
## Extracted Text
{{ ocr_text }}
{% endif %}
{% if raw_text %}
## Authoritative Episode Script / Text Context
{{ raw_text }}
{% endif %}

Produce a concise, high-signal structured EpisodeUnderstanding in **{{ preferred_language }}**."""

# Backward-compatible combined template
SUMMARIZE_USER_PROMPT = SUMMARIZE_SHARED_PREFIX_PROMPT + "\n\n" + SUMMARIZE_CHUNK_TAIL_PROMPT
