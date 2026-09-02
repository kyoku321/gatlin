"""Tests for language tag validation and alias normalization."""

import pytest
from pydantic import ValidationError

from src.models import AIConfig, AIProvider, WebhookConfig


def _ai_config(languages):
    return AIConfig(
        provider=AIProvider.OPENAI,
        model="gpt-4",
        api_key_env="OPENAI_API_KEY",
        languages=languages,
    )


def test_ai_languages_default():
    config = AIConfig(
        provider=AIProvider.OPENAI,
        model="gpt-4",
        api_key_env="OPENAI_API_KEY",
    )
    assert config.languages == ["en"]


def test_ai_languages_accepts_standard_tags():
    config = _ai_config(["zh", "en", "ja", "pt-BR"])
    assert config.languages == ["zh", "en", "ja", "pt-BR"]


@pytest.mark.parametrize("alias, canonical", [("jp", "ja"), ("JP", "ja"), ("Jp", "ja")])
def test_ai_languages_normalizes_jp_alias(alias, canonical):
    config = _ai_config([alias])
    assert config.languages == [canonical]


def test_ai_languages_mixed_alias_and_standard():
    config = _ai_config(["zh", "en", "jp"])
    assert config.languages == ["zh", "en", "ja"]


@pytest.mark.parametrize("bad", ["../etc/passwd", "en/us/x", "1", "a", "_en"])
def test_ai_languages_rejects_invalid_tags(bad):
    with pytest.raises(ValidationError, match="invalid language code"):
        _ai_config([bad])


def test_webhook_languages_normalizes_alias():
    config = WebhookConfig(url_env="X", languages=["jp", "zh"])
    assert config.languages == ["ja", "zh"]


def test_webhook_languages_none_unchanged():
    config = WebhookConfig(url_env="X", languages=None)
    assert config.languages is None
