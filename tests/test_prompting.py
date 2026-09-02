from pathlib import Path
from datetime import datetime, timezone

from src.ai.prompting.enrichment import (
    artifact_prompt,
    block_prompt,
    item_context,
    tool_planning_prompt,
)
from src.models import (
    ClassificationResult,
    ContentAnalysis,
    ContentItem,
    ProcessingResult,
    SourceType,
)
from src.processing import ProfileRegistry


PROFILES = ProfileRegistry.load(
    Path(__file__).resolve().parents[1] / "profiles", "tech-news"
)


def test_tool_planning_excludes_profile_writing_policy():
    profile = PROFILES.get("tech-news")
    blocks = profile.definition.enrichment.blocks

    planning = tool_planning_prompt(blocks)
    artifact = artifact_prompt(profile, "en", blocks)
    block = block_prompt(profile, "en", blocks[0], include_header=True)

    assert profile.enrichment_prompt not in planning
    assert profile.enrichment_prompt in artifact
    assert profile.enrichment_prompt in block
    assert all(configured.id in planning for configured in blocks)
    assert "Block `background` is required" in planning


def test_enrichment_context_uses_profile_content_budget():
    profile = PROFILES.get("tech-blog")
    item = ContentItem(
        id="rss:test:blog",
        source_type=SourceType.RSS,
        title="Long article",
        url="https://example.com/blog",
        published_at=datetime.now(timezone.utc),
        profile="tech-blog",
        content="OPENING" + "A" * 25000 + "MIDDLE" + "B" * 25000 + "ENDING",
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile="tech-blog", method="source_override"
            ),
            analysis=ContentAnalysis(
                score=8,
                reason="Deep article",
                summary="A long argument",
            ),
        ),
    )

    context = item_context(item, profile, include_content=True)

    assert "[Opening excerpt]" in context
    assert "[Middle excerpt]" in context
    assert "[Closing excerpt]" in context
    assert "OPENING" in context
    assert "MIDDLE" in context
    assert "ENDING" in context


def test_target_language_instruction_japanese():
    from src.ai.prompting.enrichment import target_language_instruction

    assert target_language_instruction("ja") == "Japanese (language tag `ja`, 日本語)"
    assert target_language_instruction("zh") == "Simplified Chinese (language tag `zh`, 简体中文)"
    assert target_language_instruction("fr") == "language `fr`"


def test_artifact_prompt_target_language_contract_decoupled_from_source():
    from src.ai.prompting.enrichment import artifact_prompt

    prompt = artifact_prompt(PROFILES.get("tech-news"), "ja", [])
    assert "# Target language (required)" in prompt
    assert "exclusively in Japanese (language tag `ja`, 日本語)" in prompt
    assert "never output artifact text in the source content's language" in prompt


def test_target_language_reminder_uses_target_language_itself():
    from src.ai.prompting.enrichment import target_language_reminder

    ja = target_language_reminder("ja")
    assert "Final reminder" in ja
    assert "日本語" in ja

    zh = target_language_reminder("zh")
    assert "简体中文" in zh

    fr = target_language_reminder("fr")
    assert "language `fr`" in fr
