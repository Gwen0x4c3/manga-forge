from __future__ import annotations

SUMMARIZE_SYSTEM_PROMPT = (
    "You are an expert manga analyst. Your task is to analyze "
    "manga episode content and extract structured information.\n\n"
    "You must identify:\n"
    "1. A concise summary of the episode\n"
    "2. Key events in chronological order\n"
    "3. Character state changes (injuries, relationship changes, new possessions, etc.)\n"
    "4. New assets discovered (characters, outfits, locations, items, art styles)\n"
    "5. Foreshadowing/pits (unresolved plot threads, mysteries, hints at future events)\n\n"
    "Be thorough and specific. Use the original language of the manga (Chinese/Japanese/etc)."
)

SUMMARIZE_USER_PROMPT = """Analyze the following manga episode content.

## Episode Information
- Episode Number: {{ episode_number }}
{% if episode_title %}- Title: {{ episode_title }}{% endif %}

## Previous Context
{% if previous_summary %}
{{ previous_summary }}
{% endif %}

## Current Episode Content
{% if ocr_text %}
### Extracted Text (OCR)
{{ ocr_text }}
{% endif %}

{% if page_descriptions %}
### Page Descriptions
{% for page in page_descriptions %}
Page {{ page.page_number }}:
{% for panel in page.panels %}
- Panel: {{ panel.description }}
{% if panel.ocr_text %}  Text: {{ panel.ocr_text }}{% endif %}
{% endfor %}
{% endfor %}
{% endif %}

{% if raw_text %}
### Raw Text Content
{{ raw_text }}
{% endif %}

Extract the episode understanding following the schema provided."""
