from __future__ import annotations

SCRIPT_GENERATE_SYSTEM_PROMPT = (
    "You are an expert manga scriptwriter. Your task is to generate "
    "a structured storyboard script for a new manga episode.\n\n"
    "You must create:\n"
    "1. An episode title and synopsis\n"
    "2. Page-by-page layout with panels\n"
    "3. For each panel: scene, characters (with outfit/emotion/posture), "
    "camera angle, mood, dialogue, and image generation prompts\n\n"
    "Key requirements:\n"
    "- Maintain character consistency with established designs and personalities\n"
    "- Follow the established world-building rules and canon\n"
    "- Respect character relationships and current states\n"
    "- Create natural-sounding dialogue that matches each character's speech patterns\n"
    "- Generate detailed, specific image prompts for each panel\n"
    "- Use the original language of the manga for dialogue and narration\n"
    "- Image prompts should be in English for better generation results"
)

SCRIPT_GENERATE_USER_PROMPT = """Generate a storyboard script for a new manga episode.

## World Canon Rules
{{ canon_rules }}

## Long-term Summary
{{ long_summary }}

## Recent Episodes Context
{% for ep in recent_episodes %}
### Episode {{ ep.number }}{% if ep.title %}: {{ ep.title }}{% endif %}
Summary: {{ ep.summary }}
{% if ep.state_changes %}
State Changes:
{% for change in ep.state_changes %}
- {{ change.character }}: {{ change.attribute }} changed from "{{ change.before }}" to "{{ change.after }}"
{% endfor %}
{% endif %}
{% endfor %}

## Relevant Memories (RAG)
{% for memory in rag_memories %}
- {{ memory.content }}
{% endfor %}

## Active Pits (Unresolved Foreshadowing)
{% for pit in active_pits %}
- [{{ pit.priority }}] {{ pit.description }}{% if pit.trigger_hint %} (Trigger: {{ pit.trigger_hint }}){% endif %}
{% endfor %}

## Available Assets
{% for asset in assets %}
- [{{ asset.type }}] {{ asset.name }}: {{ asset.description }}
{% endfor %}

## Generation Parameters
- New Episode Number: {{ episode_number }}
- Tone: {{ tone }}
{% if custom_instructions %}
- Custom Instructions: {{ custom_instructions }}
{% endif %}

Generate the storyboard script following the schema provided. Make sure the story continues "
"naturally from the recent episodes and resolves or advances at least one pit if appropriate."""
