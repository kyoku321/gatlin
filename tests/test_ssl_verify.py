"""Tests for HORIZON_SSL_VERIFY handling in the AI clients."""

import asyncio
import ssl

import certifi
import pytest

from src.ai.client import (
    AnthropicClient,
    AzureOpenAIClient,
    OpenAIClient,
    _build_ssl_http_client,
    _resolve_ssl_verify,
)
from src.models import AIConfig, AIProvider


def _ssl_mode(httpx_client) -> int:
    """Extract the verify_mode of the SSL context backing an httpx client."""
    return httpx_client._transport._pool._ssl_context.verify_mode


def _close(httpx_client) -> None:
    asyncio.run(httpx_client.aclose())


@pytest.mark.parametrize("value, expected", [
    ("0", False),
    ("false", False),
    ("no", False),
    ("off", False),
    ("1", True),
    ("true", True),
    ("on", True),
    ("/some/path/ca-bundle.pem", "/some/path/ca-bundle.pem"),
])
def test_resolve_ssl_verify_values(monkeypatch, value, expected):
    monkeypatch.setenv("HORIZON_SSL_VERIFY", value)
    result = _resolve_ssl_verify()
    if expected is None or isinstance(expected, bool):
        assert result is expected
    else:
        assert result == expected


def test_resolve_ssl_verify_unset(monkeypatch):
    monkeypatch.delenv("HORIZON_SSL_VERIFY", raising=False)
    assert _resolve_ssl_verify() is None


def test_resolve_ssl_verify_blank_and_whitespace(monkeypatch):
    monkeypatch.setenv("HORIZON_SSL_VERIFY", "   ")
    assert _resolve_ssl_verify() is None
    monkeypatch.setenv("HORIZON_SSL_VERIFY", "  0  ")
    assert _resolve_ssl_verify() is False


def test_build_ssl_http_client_unset_returns_none(monkeypatch):
    monkeypatch.delenv("HORIZON_SSL_VERIFY", raising=False)
    assert _build_ssl_http_client() is None


def test_build_ssl_http_client_disabled(monkeypatch):
    monkeypatch.setenv("HORIZON_SSL_VERIFY", "0")
    client = _build_ssl_http_client()
    try:
        assert client is not None
        assert _ssl_mode(client) == ssl.CERT_NONE
    finally:
        _close(client)


def test_build_ssl_http_client_explicit_verify(monkeypatch):
    monkeypatch.setenv("HORIZON_SSL_VERIFY", "1")
    client = _build_ssl_http_client()
    try:
        assert client is not None
        assert _ssl_mode(client) == ssl.CERT_REQUIRED
    finally:
        _close(client)


def test_build_ssl_http_client_ca_bundle_path(monkeypatch):
    monkeypatch.setenv("HORIZON_SSL_VERIFY", certifi.where())
    client = _build_ssl_http_client()
    try:
        assert client is not None
        assert _ssl_mode(client) == ssl.CERT_REQUIRED
    finally:
        _close(client)


def _make_ollama_config() -> AIConfig:
    return AIConfig(provider=AIProvider.OLLAMA, model="llama3.1", api_key_env="")


def test_openai_client_ssl_disabled(monkeypatch):
    monkeypatch.setenv("HORIZON_SSL_VERIFY", "0")
    client = OpenAIClient(_make_ollama_config())
    assert _ssl_mode(client.client._client) == ssl.CERT_NONE


def test_openai_client_default_verification(monkeypatch):
    monkeypatch.delenv("HORIZON_SSL_VERIFY", raising=False)
    client = OpenAIClient(_make_ollama_config())
    assert _ssl_mode(client.client._client) == ssl.CERT_REQUIRED


def test_anthropic_client_ssl_disabled(monkeypatch):
    monkeypatch.setenv("HORIZON_SSL_VERIFY", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    config = AIConfig(
        provider=AIProvider.ANTHROPIC,
        model="claude-3-5-sonnet-20241022",
        api_key_env="ANTHROPIC_API_KEY",
    )
    client = AnthropicClient(config)
    assert _ssl_mode(client.client._client) == ssl.CERT_NONE


def test_azure_client_ssl_disabled(monkeypatch):
    monkeypatch.setenv("HORIZON_SSL_VERIFY", "0")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    config = AIConfig(
        provider=AIProvider.AZURE,
        model="gpt-4",
        api_key_env="AZURE_OPENAI_API_KEY",
        azure_endpoint_env="AZURE_OPENAI_ENDPOINT",
        api_version="2024-10-21",
    )
    client = AzureOpenAIClient(config)
    assert _ssl_mode(client.client._client) == ssl.CERT_NONE
