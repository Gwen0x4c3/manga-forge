# ruff: noqa: E501
from __future__ import annotations

from jinja2 import Template

CONSISTENCY_CHECK_SYSTEM_PROMPT = (
    "You are a senior manga continuity editor. Audit a newly generated storyboard script against "
    "the series' canon rules, main plotline, previous episode ending bridge, cumulative character states, "
    "key items/locations, and open foreshadowing.\n\n"
    "Check strictly for:\n"
    "1. Canon & World Rule Violations (breaking established laws/settings of the world)\n"
    "2. Immediate Transition Errors (ignoring where/how the previous episode ended without explanation)\n"
    "3. Character & Voice Inconsistencies (wrong personality, wrong forms of address, wrong visual appearance/outfit)\n"
    "4. Cumulative State Conflicts (injured character suddenly unharmed, lost/locked item used impossibly, wrong location)\n"
    "5. Plot & Foreshadowing Contradictions (contradicting open mysteries or past events)\n"
    "6. Panel-Layout Mismatch (e.g. layout='3_panels' having 1 or 5 panels, or missing dialogue language consistency)\n\n"
    "Severity levels:\n"
    "- critical = factual contradiction, broken continuity, or wrong character identity/state (must regenerate)\n"
    "- warning = minor pacing, outfit, or tone drift\n"
    "- info = constructive polish suggestion\n"
    "Be rigorous on continuity facts while welcoming creative forward plot progression."
)

CONSISTENCY_CHECK_USER_TEMPLATE = Template(
    """## Main Plotline & World Canon Rules
{% if story_bible and story_bible.get('main_plot') %}
Main Plot: {{ story_bible.get('main_plot') }}
{% endif %}
{% if canon_rules %}
Canon Rules: {{ canon_rules }}
{% else %}
Canon Rules: (none)
{% endif %}

## Long-term Summary
{{ long_summary or '(none)' }}

{% if previous_bridge %}
## Previous Episode Ending Bridge (Episode {{ previous_bridge.episode_number }})
- Ending State: {{ previous_bridge.ending_state }}
- Summary: {{ previous_bridge.summary }}
{% endif %}

## Recent Episodes
{% for ep in recent_episodes %}
- Episode {{ ep.number }}{% if ep.title %} ({{ ep.title }}){% endif %}: {{ ep.summary }}
{% endfor %}

## Cumulative Character Dossier & Latest States
{% for char in character_states %}
- {{ char.name }}: {{ char.description }}{% if char.current_state %} | State: {{ char.current_state }}{% endif %}{% if char.speech_style %} | Voice: {{ char.speech_style }}{% endif %}
{% else %}
(none)
{% endfor %}

## Key Items & Locations
{% for asset in world_assets %}
- [{{ asset.type }}] {{ asset.name }}: {{ asset.description }}
{% else %}
(none)
{% endfor %}

## Open Pits (Unresolved Foreshadowing)
{% for pit in open_pits %}
- [{{ pit.id }}] {{ pit.description }}
{% else %}
(none)
{% endfor %}

## Candidate Storyboard Script
{{ storyboard_json }}

Audit this storyboard and output the structured ConsistencyReport."""
)
