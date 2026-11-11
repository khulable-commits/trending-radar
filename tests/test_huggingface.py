"""Unit tests for the Hugging Face trending models scraper."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.models import HuggingFaceConfig
from src.scrapers.huggingface import HuggingFaceScraper

SINCE = datetime(2026, 11, 11, 0, 0, 0, tzinfo=timezone.utc)

_MODELS = [
    {
        "id": "moonshotai/Kimi-K3.1-Pro",
        "likes": 1867,
        "downloads": 30721,
        "trendingScore": 616,
        "pipeline_tag": "image-text-to-text",
        "library_name": "transformers",
        "createdAt": "2026-11-02T04:13:51.000Z",
        "tags": [
            "transformers",
            "safetensors",
            "text-generation",
            "base_model:some/model",
            "license:apache-2.0",
            "region:us",
        ],
    },
    {
        "id": "Lightricks/LTX-2.5",
        "likes": 11381,
        "downloads": 2791606,
        "trendingScore": 390,
        "pipeline_tag": "image-to-video",
        "library_name": "diffusion-single-file",
        "tags": ["diffusion", "video"],
    },
]


def _mock_client(payload) -> AsyncMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    return client


def test_fetch_builds_ranked_items_with_metrics() -> None:
    client = _mock_client(_MODELS)
    config = HuggingFaceConfig(
        enabled=True, limit=50, profile="trending", category="hf-trending"
    )
    scraper = HuggingFaceScraper(config, client)

    result = asyncio.run(scraper.fetch(SINCE))

    assert result.status == "success"
    assert result.successful == 1
    assert len(result.items) == 2

    top = result.items[0]
    assert top.id == "huggingface:model:moonshotai/Kimi-K3.1-Pro"
    assert top.source_type.value == "huggingface"
    assert top.profile == "trending"
    assert str(top.url) == "https://huggingface.co/moonshotai/Kimi-K3.1-Pro"
    assert top.author == "moonshotai"
    assert top.metadata["rank"] == 1
    assert top.metadata["likes"] == 1867
    assert top.metadata["downloads"] == 30721
    assert top.metadata["trending_score"] == 616.0
    assert top.metadata["pipeline_tag"] == "image-text-to-text"
    assert top.metadata["category"] == "hf-trending"
    assert "Kimi-K3.1-Pro" in top.title
    assert result.items[1].metadata["rank"] == 2


def test_request_uses_trending_score_ranking() -> None:
    client = _mock_client(_MODELS)
    config = HuggingFaceConfig(enabled=True, limit=50)
    scraper = HuggingFaceScraper(config, client)

    asyncio.run(scraper.fetch(SINCE))

    params = client.get.call_args.kwargs["params"]
    assert params == {"sort": "trendingScore", "direction": -1, "limit": 50}


def test_noise_tags_are_filtered_from_metadata() -> None:
    client = _mock_client(_MODELS)
    scraper = HuggingFaceScraper(HuggingFaceConfig(enabled=True), client)

    result = asyncio.run(scraper.fetch(SINCE))

    tags = result.items[0].metadata["tags"]
    assert tags == ["transformers", "safetensors", "text-generation"]


def test_rows_without_a_model_id_are_skipped() -> None:
    client = _mock_client([{"likes": 5}, *_MODELS])
    scraper = HuggingFaceScraper(HuggingFaceConfig(enabled=True), client)

    result = asyncio.run(scraper.fetch(SINCE))

    assert [item.metadata["rank"] for item in result.items] == [2, 3]


def test_request_failure_is_reported() -> None:
    from httpx import HTTPStatusError, Request, Response

    request = Request("GET", "https://huggingface.co/api/models")
    response = Response(503, request=request)
    client = AsyncMock()
    client.get.side_effect = HTTPStatusError(
        "unavailable", request=request, response=response
    )
    scraper = HuggingFaceScraper(HuggingFaceConfig(enabled=True), client)

    result = asyncio.run(scraper.fetch(SINCE))

    assert result.status == "failure"
    assert result.items == []
    assert "models" in result.failures


def test_limit_is_applied_to_results() -> None:
    client = _mock_client(_MODELS)
    scraper = HuggingFaceScraper(HuggingFaceConfig(enabled=True, limit=1), client)

    result = asyncio.run(scraper.fetch(SINCE))

    assert len(result.items) == 1
