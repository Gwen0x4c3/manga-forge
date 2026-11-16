from __future__ import annotations

from jinja2 import Template

CONSISTENCY_CHECK_SYSTEM_PROMPT = (
    "You are a manga continuity editor. Check a generated storyboard script against "
    "the established canon, character states, and open foreshadowing.\n\n"
    "Look for:\n"
    "1. Canon violations (breaking established world rules)\n"
    "2. Character inconsistencies (wrong personality, speech patterns, relationships, outfits)\n"
    "3. State conflicts (character states that don't match their last known state)\n"
    "4. Plot contradictions (events that contradict previous episodes)\n"
    "5. Asset mismatches (wrong outfit, location, or item descriptions)\n\n"
    "Severity: critical = must fix before rendering, warning = should fix, info = suggestion.\n"
    "Be strict about facts but tolerant of creative new plot elements that don't contradict anything."
)

CONSISTENCY_CHECK_USER_TEMPLATE = Template(
    """## World Canon Rules
{% if canon_rules %}
{{ canon_rules }}
{% else %}
(none)
{% endif %}

## Long-term Summary
{% if long_summary %}
{{ long_summary }}
{% else %}
(none)
{% endif %}

## Recent Episodes
{% for ep in recent_episodes %}
- Episode {{ ep.number }}{% if ep.title %} ({{ ep.title }}){% endif %}: {{ ep.summary }}
{% endfor %}

## Character States (latest known)
{% for char in character_states %}
- {{ char.name }}: {{ char.description }}
{% else %}
(none)
{% endfor %}

## Open Pits (unresolved foreshadowing)
{% for pit in open_pits %}
- {{ pit.description }}
{% else %}
(none)
{% endfor %}

## Generated Storyboard
{{ storyboard_json }}

Identify consistency issues and provide the structured report."""
)
