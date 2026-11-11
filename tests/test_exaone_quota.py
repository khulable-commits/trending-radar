"""A spent daily allowance must stop the run instead of being retried per item."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import APIStatusError

from src.ai.client import OpenAIClient
from src.ai.errors import AIProviderUnavailableError
from src.models import AIConfig


def _config() -> AIConfig:
    return AIConfig(
        provider="openai",
        model="k-exaone_v2.5",
        base_url="https://api.exaone.ai/v1",
        api_key_env="EXAONE_API_KEY",
    )


def _status_error(status: int, message: str) -> APIStatusError:
    request = httpx.Request("POST", "https://api.exaone.ai/v1/chat/completions")
    response = httpx.Response(status, request=request, json={"error": {"message": message}})
    return APIStatusError(message, response=response, body={"error": {"message": message}})


def _client_with_error(error: Exception) -> OpenAIClient:
    client = OpenAIClient(_config())
    completions = MagicMock()
    completions.create = AsyncMock(side_effect=error)
    client.client = MagicMock()
    client.client.chat.completions = completions
    return client


def test_daily_limit_stops_the_run(monkeypatch) -> None:
    monkeypatch.setenv("EXAONE_API_KEY", "sk-test")
    client = _client_with_error(
        _status_error(429, "day limit(100), called 100 times today")
    )

    with pytest.raises(AIProviderUnavailableError, match="daily allowance"):
        asyncio.run(client.complete(system="s", user="u"))


def test_per_second_limit_is_not_treated_as_a_daily_limit(monkeypatch) -> None:
    monkeypatch.setenv("EXAONE_API_KEY", "sk-test")
    error = _status_error(429, "second limit(1), called 2 times per second")
    client = _client_with_error(error)

    with pytest.raises(APIStatusError):
        asyncio.run(client.complete(system="s", user="u"))
