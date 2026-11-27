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


# =============================================================================
# Two-Phase Agentic Manga Understanding Prompts
# Phase A: Sequential High-Res Page Reading Notes (90%+ Prefix Cache Hit!)
# Phase B: Whole-Episode Coherent Structured Synthesis (Zero Fragmentation!)
# =============================================================================

READ_PAGES_SYSTEM_PROMPT = (
    "You are an expert manga editor carefully reading a serialized manga episode page by page.\n"
    "You will receive the series Story Bible, known cast (with visual reference portraits), open foreshadowing, "
    "earlier page notes from THIS SAME episode, and the next 3-5 manga pages stamped with labels (e.g. `p04`, `p06 R`, `p06 L`).\n\n"
    "Your ONLY job in this reading step is to write CRISP, FACTUAL, PAGE-BY-PAGE READING NOTES in the project's "
    "Preferred Output Language (plain bullet points, NO JSON):\n"
    "1. SKIP NON-STORY PAGES: If a page is a scanlation credit/recruitment page, Discord ad, blank page, table of contents, "
    "or publisher copyright page, write ONLY `- pXX: 非正片页 -> 跳过` and NEVER mention scanlation group names.\n"
    "2. READ CAREFULLY IN ORDER: For every story page, capture what happens visually, who appears (matching Known Characters "
    "by face/hair/glasses/aliases!), key dialogue lines (translated concisely into Preferred Language), exact character "
    "appearances/outfits/vital status changes, signature items/locations drawn, and any clues/payoffs for Open Pits.\n"
    "3. MARK BEST VISUAL CROPS: Whenever a character has a clear, unclipped FRONT or 3/4 FACE (normal expression) or a "
    "signature item/location/outfit is drawn clearly on a page, add a bullet:\n"
    "   `- ★裁剪候选 [character|item|location|outfit] <标准名称> @ pXX: <画面特征与位置>`\n"
    "4. OPTIONAL ZOOM RE-READ: ONLY if a single page has critical small/dense text you could not read clearly, add:\n"
    "   `- ?需放大复核 @ pXX: <原因>`\n"
    "Keep notes dense, accurate, strictly grounded in what is drawn on the pages — NEVER hallucinate or extrapolate."
)

READ_SHARED_PREFIX_PROMPT = """## Output Language & Canonical Naming (MANDATORY)
- Series Title: **{{ project_title or 'Unknown Manga' }}**
- Preferred Output Language: **{{ preferred_language }}**
- Write ALL notes and character primary names strictly in **{{ preferred_language }}**.
- CRITICAL NAMING RULE: When reading foreign/English-translated pages of a known manga series, ALWAYS use the official/canonical character names in **{{ preferred_language }}** for `{{ project_title or 'this series' }}` (NEVER invent arbitrary phonetic kanji transliterations — e.g. for 《异世界舅舅》 use 舅舅 / 敬文 / 精灵 / 梅贝尔 / 藤宫澄夏, NOT 敬一 / 富士宫). Put original JP/EN spellings in parentheses when first introduced.

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
(Not established yet — this is the beginning of the series)
{% endif %}

## Rolling Story Context (Prior Episodes)
{% if previous_summary %}
{{ previous_summary }}
{% else %}
(none — this is the first analyzed episode)
{% endif %}

{% if known_characters %}
## Known Characters (match strictly by visual portrait + aliases; NEVER confuse different people!)
{% for c in known_characters %}
- [{{ c.asset_id }}] {{ c.name }}{% if c.aliases %} (aliases: {{ c.aliases | join(', ') }}){% endif %}: {{ c.description }}
{% endfor %}
{% else %}
## Known Characters
(none yet — identify every named or recurring main character cleanly)
{% endif %}

{% if known_other_assets %}
## Known Signature Items, Locations & Outfits
{% for a in known_other_assets %}
- [{{ a.asset_id }}] ({{ a.type }}) {{ a.name }}: {{ a.description }}
{% endfor %}
{% endif %}

{% if open_pits %}
## Open Pits (Watch for Clues & Payoffs!)
{% for p in open_pits %}
- [{{ p.id }}] (priority={{ p.priority }}) {{ p.description }}{% if p.trigger_hint %} | Hint: {{ p.trigger_hint }}{% endif %}
{% endfor %}
{% endif %}"""

READ_WINDOW_TAIL_PROMPT = """{% if earlier_notes %}## Notes From Earlier Pages of This Same Episode
{{ earlier_notes }}

{% endif %}## Next Pages to Read ({{ window_label }})
Read the attached pages strictly in label order (`pXX`, right-to-left if marked `R` then `L`). Output crisp page-by-page bullet notes in **{{ preferred_language }}**."""


SYNTHESIZE_EPISODE_SYSTEM_PROMPT = (
    "You are a senior manga story editor synthesizing complete page-by-page reading notes of ONE serialized episode "
    "into a single ultra-clean, coherent, deduplicated JSON `EpisodeUnderstanding`.\n\n"
    "MANDATORY QUALITY RULES:\n"
    "1. OUTPUT LANGUAGE LOCK: ALL narrative text (summary, main_plot, ending_state, events, state_changes, "
    "character primary `name`, appearance, descriptions, world_rules_discovered, pit titles/descriptions) MUST be "
    "in the Preferred Output Language. Put original JP/EN names in `aliases[]`. Keep `visual_tags[]` in English.\n"
    "2. ZERO NON-STORY NOISE: Completely ignore any skipped scanlation/recruitment/blank/TOC pages. NEVER mention "
    "scanlation groups or write 'this window only contains covers'.\n"
    "3. COHERENT EPISODE SUMMARY: Write ONE fluent 3-5 sentence synopsis covering the ENTIRE episode from opening to ending.\n"
    "4. STRICT ANTI-DUPLICATE & ANTI-NOISE CAST:\n"
    "   - Reuse exact `asset_id` for every Known Character who appeared; NEVER split one person into two entries "
    "(e.g. a known character wearing a hoodie or glasses is STILL that known character!).\n"
    "   - Register ONLY named or recurring plot-relevant characters. NEVER register unnamed one-off extras (nurses, passers-by, crowds).\n"
    "   - For every character, set `source_page` (integer 1-based page number) to the BEST `★裁剪候选` page from the notes!\n"
    "5. STRICT VISUAL ASSET GATE: In `new_assets` (item|location|outfit), register ONLY plot-critical, magical/special, "
    "or recurring signature items/locations/outfits that were VISUALLY DRAWN on a page (ALWAYS provide integer `source_page`!). "
    "Never register mundane props (teacups, chairs, bags) or things merely mentioned in speech.\n"
    "6. FORESHADOWING (LESS IS MORE — 0 TO 2 NEW PITS MAX): Routine comedy/slice-of-life episodes should emit 0 new pits! "
    "ONLY record truly major cross-episode mysteries, curses, seals, hidden pasts, or looming threats. Actively emit "
    "`pit_progressions` and `resolved_pits` (using exact open pit IDs!) whenever an existing pit advances or resolves.\n"
    "7. VITAL STATUS: Always emit `state_changes` with `attribute='vital_status'` if any character dies, is sealed, goes missing, or revives.\n"
    "8. Output ONLY a single valid JSON object matching the requested schema (no markdown fences or commentary). "
    "NEVER use raw ASCII double quotes (\") inside Chinese/Japanese string values — use 『』 or 「」 instead."
)

SYNTHESIZE_EPISODE_USER_PROMPT = """Synthesize the complete reading notes of Episode {{ episode_number }} into one clean JSON object.

## Output Language & Canonical Naming (MANDATORY)
- Series Title: **{{ project_title or 'Unknown Manga' }}**
- Preferred Output Language: **{{ preferred_language }}**
- Use official/canonical character names in **{{ preferred_language }}** for `{{ project_title or 'this series' }}` (put original JP/EN names in `aliases[]`).

## Story Bible & Context Prior to Episode {{ episode_number }}
{% if main_plot %}
- Core Conflict: {{ main_plot.get('core_conflict', '') }}
- Current Arc: {{ main_plot.get('current_arc', '') }}
- Protagonist Goal: {{ main_plot.get('protagonist_goal', '') }}
- Previous Hook: {{ main_plot.get('next_hook', '') }}
{% else %}
(Not established yet — establish foundational main plotline & current arc from this episode)
{% endif %}
{% if previous_summary %}
### Prior Episodes Rolling Summary
{{ previous_summary }}
{% endif %}

## Known Characters (MUST reuse exact `asset_id`)
{% if known_characters %}
{% for c in known_characters %}
- [{{ c.asset_id }}] {{ c.name }}{% if c.aliases %} (aliases: {{ c.aliases | join(', ') }}){% endif %}: {{ c.description }}
{% endfor %}
{% else %}
(none yet)
{% endif %}

## Known Items, Locations & Outfits (match via `asset_sightings[].asset_id`, do NOT duplicate in `new_assets`)
{% if known_other_assets %}
{% for a in known_other_assets %}
- [{{ a.asset_id }}] ({{ a.type }}) {{ a.name }}: {{ a.description }}
{% endfor %}
{% else %}
(none yet)
{% endif %}

## Open Pits (Use exact `id` for `pit_progressions` and `resolved_pits`)
{% if open_pits %}
{% for p in open_pits %}
- [{{ p.id }}] (priority={{ p.priority }}) {{ p.description }}
{% endfor %}
{% else %}
(none yet)
{% endif %}

## Complete Sequential Page-by-Page Reading Notes of Episode {{ episode_number }}
{{ episode_notes }}

## Required JSON Schema
```json
{
  "summary": "3-5 sentence fluent synopsis in {{ preferred_language }}",
  "main_plot": {"core_conflict": "...", "current_arc": "...", "protagonist_goal": "...", "arc_progress": "...", "next_hook": "..."},
  "ending_state": {"location": "...", "time_of_day": "...", "active_characters": ["..."], "emotional_tone": "...", "cliffhanger": "..."},
  "art_style_notes": "...",
  "world_rules_discovered": ["..."],
  "events": [{"description": "...", "characters_involved": ["..."], "location": "...", "items_involved": ["..."], "significance": "normal|major|turning_point|cliffhanger"}],
  "state_changes": [{"character": "...", "attribute": "vital_status|injury|relationship|location|possession|ability|knowledge|status", "before": "...", "after": "...", "reason": "..."}],
  "characters": [{"name": "...", "asset_id": "<existing id or null>", "aliases": ["..."], "appearance": "...", "speech_style": "...", "role": "protagonist|support|antagonist|cameo", "vital_status": "alive|injured|missing|sealed|deceased", "source_page": 5}],
  "asset_sightings": [{"asset_id": "...", "name": "...", "asset_type": "item|location|outfit", "state_note": "..."}],
  "new_assets": [{"name": "...", "aliases": ["..."], "asset_type": "character|outfit|location|item", "description": "...", "visual_tags": ["english tags"], "owner_or_context": "...", "source_page": 5}],
  "pit_discoveries": [{"title": "...", "description": "...", "priority": "high|medium", "trigger_hint": "...", "related_characters": ["..."]}],
  "pit_progressions": [{"pit_id": "...", "clue": "..."}],
  "resolved_pits": ["<open pit id>"],
  "page_dialogues": [{"page_number": 5, "lines": [{"speaker": "...", "text": "...", "line_type": "speech|thought|narration"}]}]
}
```
Return ONLY the valid JSON object."""
