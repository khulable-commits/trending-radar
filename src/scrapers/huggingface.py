"""Hugging Face trending models scraper.

Reads the public models API at https://huggingface.co/api/models sorted by
``trendingScore`` and emits the top N models. No API key is required.

The API returns the current trending ordering rather than dated publications,
so each model is emitted at fetch time and the model's own ``createdAt`` is
kept in metadata.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from ..models import ContentItem, HuggingFaceConfig, SourceType
from .base import BaseScraper, FetchResult

# Tags that describe repository plumbing rather than the model itself.
_NOISE_TAG_PREFIXES = (
    "base_model:",
    "license:",
    "region:",
    "dataset:",
    "arxiv:",
    "doi:",
    "autotrain_",
)


class HuggingFaceScraper(BaseScraper):
    """Scraper for the Hugging Face trending models ranking."""

    BASE_URL = "https://huggingface.co/api/models"

    def __init__(self, config: HuggingFaceConfig, http_client: httpx.AsyncClient):
        """Initialize scraper.

        Args:
            config: Hugging Face source configuration
            http_client: Shared async HTTP client
        """
        super().__init__(config, http_client)
        self.cfg: HuggingFaceConfig = config

    async def fetch(self, since: datetime) -> FetchResult:
        """Fetch the current trending models.

        The ranking is a live snapshot, so ``since`` does not filter rows.
        """
        result = FetchResult()
        if not self.cfg.enabled:
            return result

        try:
            rows = await self._fetch_models()
        except Exception as exc:
            result.fail("models", exc)
            return result

        result.successful += 1
        items: List[ContentItem] = []
        for rank, row in enumerate(rows, start=1):
            item = self._row_to_item(row, rank)
            if item is not None:
                items.append(item)
        result.items = items[: self.cfg.limit]
        return result

    async def _fetch_models(self) -> List[dict]:
        """Call the models API for the configured ranking."""
        params: Dict[str, Any] = {
            "sort": self.cfg.sort,
            "direction": -1,
            "limit": self.cfg.limit,
        }
        if self.cfg.pipeline_tag:
            params["filter"] = self.cfg.pipeline_tag
        if self.cfg.search:
            params["search"] = self.cfg.search

        response = await self.client.get(
            self.BASE_URL,
            params=params,
            headers={"Accept": "application/json", "User-Agent": "Horizon/1.0"},
            follow_redirects=True,
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Hugging Face models API returned a non-list payload")
        return [row for row in payload if isinstance(row, dict)]

    def _row_to_item(self, row: dict, rank: int) -> Optional[ContentItem]:
        """Convert one API row into a ContentItem."""
        model_id = row.get("id") or row.get("modelId")
        if not model_id:
            return None

        likes = self._int(row.get("likes"))
        downloads = self._int(row.get("downloads"))
        trending_score = self._float(row.get("trendingScore"))
        pipeline_tag = row.get("pipeline_tag")
        library_name = row.get("library_name")
        created_at = row.get("createdAt")
        tags = self._meaningful_tags(row.get("tags"))

        title = f"#{rank} {model_id} — HF trending (score {trending_score:g})"

        content_lines = [
            f"Hugging Face trending model rank #{rank}",
            f"Model: {model_id}",
        ]
        if pipeline_tag:
            content_lines.append(f"Task: {pipeline_tag}")
        if library_name:
            content_lines.append(f"Library: {library_name}")
        content_lines.append(f"Likes: {likes:,}")
        content_lines.append(f"Downloads (last 30 days): {downloads:,}")
        content_lines.append(f"Trending score: {trending_score:g}")
        if created_at:
            content_lines.append(f"Created: {created_at}")
        if tags:
            content_lines.append("Tags: " + ", ".join(tags))
        content_lines.append(f"Link: https://huggingface.co/{model_id}")

        return ContentItem(
            id=self._generate_id(SourceType.HUGGINGFACE.value, "model", model_id),
            source_type=SourceType.HUGGINGFACE,
            title=title,
            url=f"https://huggingface.co/{model_id}",
            content="\n".join(content_lines),
            author=model_id.split("/")[0] if "/" in model_id else None,
            published_at=datetime.now(timezone.utc),
            profile=self.cfg.profile,
            metadata={
                "model_id": model_id,
                "rank": rank,
                "sort": self.cfg.sort,
                "trending_score": trending_score,
                "likes": likes,
                "downloads": downloads,
                "pipeline_tag": pipeline_tag,
                "library_name": library_name,
                "tags": tags,
                "created_at": created_at,
                "category": self.cfg.category,
            },
        )

    @staticmethod
    def _meaningful_tags(value: Any) -> List[str]:
        """Keep model-describing tags and drop repository plumbing tags."""
        if not isinstance(value, list):
            return []
        tags: List[str] = []
        for tag in value:
            if not isinstance(tag, str) or not tag.strip():
                continue
            normalized = tag.strip()
            if normalized.startswith(_NOISE_TAG_PREFIXES):
                continue
            tags.append(normalized)
        return tags

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
