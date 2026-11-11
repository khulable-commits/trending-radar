"""Prompt construction for profile-driven content analysis."""

from ...models import ContentItem
from ...processing.profiles import LoadedProfile
from .common import EVIDENCE_RULES, UNTRUSTED_INPUT_RULE

ANALYSIS_RULES = f"""You are a content curator evaluating an item under the supplied processing profile.

- {UNTRUSTED_INPUT_RULE}
- Base the analysis only on the supplied item and its metadata.
{EVIDENCE_RULES}
- Apply the profile's evaluation policy consistently."""


def analysis_system_prompt(profile: LoadedProfile, language: str | None = None) -> str:
    language_note = analysis_language_note(language) if language else ""
    return f"""{ANALYSIS_RULES}

# Profile policy

{profile.analysis_prompt}

# Output contract

Return valid JSON only:
{{
  "score": <number from 0 to 10>,
  "reason": "<concise explanation>",
  "summary": "<one-sentence summary>",
  "tags": ["<tag>", "..."]
}}{language_note}"""


def analysis_language_note(language: str) -> str:
    """Keep reader-facing analysis text in the configured output language."""
    lowered = language.lower()
    if lowered == "ko":
        return (
            "\n\n# Output language\n\n"
            "Write `reason` and `summary` in Korean (한국어). "
            "Keep `tags` as short technical terms, which may stay in English."
        )
    if lowered == "zh":
        return (
            "\n\n# Output language\n\n"
            "Write `reason` and `summary` in Simplified Chinese. "
            "Keep `tags` as short technical terms."
        )
    return ""


def analysis_user_prompt(
    item: ContentItem,
    content_section: str,
    discussion_section: str,
) -> str:
    return f"""Analyze the following content.

Title: {item.title}
Source: {item.source_type.value}
Author: {item.author or "Unknown"}
URL: {item.url}
{content_section}
{discussion_section}"""
