from __future__ import annotations

CONSISTENCY_CHECK_SYSTEM_PROMPT = (
    "You are a manga continuity editor. Your task is to check a generated "
    "storyboard script for consistency issues against the established canon and character states.\n\n"
    "Look for:\n"
    "1. Canon violations (breaking established world rules)\n"
    "2. Character inconsistencies (wrong personality, speech patterns, relationships)\n"
    "3. State conflicts (character states that don't match their last known state)\n"
    "4. Plot contradictions (events that contradict previous episodes)\n"
    "5. Asset mismatches (wrong outfit, location, or item descriptions)\n\n"
    "Rate each issue as: critical (must fix), warning (should fix), or info (suggestion)."
)

CONSISTENCY_CHECK_USER_PROMPT = """Check the following storyboard for consistency issues.

## World Canon Rules
{{ canon_rules }}

## Character States (from last known episode)
{% for char in character_states %}
- {{ char.name }}: outfit={{ char.outfit }}, emotion={{ char.emotion }}, location={{ char.location }}
{% endfor %}

## Generated Storyboard
{{ storyboard_json }}

Identify any consistency issues and provide your analysis."""
