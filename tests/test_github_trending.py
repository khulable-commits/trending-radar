"""Unit tests for the GitHub Trending scraper."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.models import GitHubTrendingConfig
from src.scrapers.github_trending import GitHubTrendingScraper

SINCE = datetime(2026, 11, 11, 0, 0, 0, tzinfo=timezone.utc)

_ARTICLE = """
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a href="/meta/astryx" data-view-component="true">meta / astryx</a>
  </h2>
  <p class="col-9 color-fg-muted my-1 pr-4">An open source design system</p>
  <div class="f6 color-fg-muted mt-2">
    <span itemprop="programmingLanguage">TypeScript</span>
    <a href="/meta/astryx/stargazers">22,852</a>
    <a href="/meta/astryx/forks">1,821</a>
    <span class="float-sm-right">3,108 stars today</span>
  </div>
</article>
"""

_ARTICLE_SECOND = """
<article class="Box-row">
  <h2><a href="/anthropics/skills">anthropics / skills</a></h2>
  <p>Public repository for Agent Skills</p>
  <div class="f6">
    <span itemprop="programmingLanguage">Python</span>
    <a href="/anthropics/skills/stargazers">192,339</a>
    <a href="/anthropics/skills/forks">22,646</a>
    <span class="float-sm-right">1,679 stars this week</span>
  </div>
</article>
"""


def _html(*articles: str) -> str:
    return "<html><body>" + "".join(articles) + "</body></html>"


def _mock_client_by_period(html_by_period: dict[str, str]) -> AsyncMock:
    client = AsyncMock()

    def _get(url, params=None, **kwargs):
        response = MagicMock()
        response.text = html_by_period[params["since"]]
        response.raise_for_status.return_value = None
        return response

    client.get.side_effect = _get
    return client


def test_parse_page_extracts_rank_and_metrics() -> None:
    scraper = GitHubTrendingScraper(
        GitHubTrendingConfig(enabled=True), AsyncMock()
    )

    rows = scraper.parse_page(_html(_ARTICLE), "daily")

    assert len(rows) == 1
    row = rows[0]
    assert row["repo"] == "meta/astryx"
    assert row["rank"] == 1
    assert row["description"] == "An open source design system"
    assert row["primary_language"] == "TypeScript"
    assert row["stars_total"] == 22852
    assert row["stars_period"] == 3108
    assert row["forks_total"] == 1821


def test_parse_page_skips_rows_without_a_repository_link() -> None:
    scraper = GitHubTrendingScraper(
        GitHubTrendingConfig(enabled=True), AsyncMock()
    )

    rows = scraper.parse_page("<article class='Box-row'><p>no link</p></article>", "daily")

    assert rows == []


def test_fetch_merges_a_repository_across_periods() -> None:
    shared = _html(_ARTICLE)
    client = _mock_client_by_period(
        {"daily": shared, "weekly": shared, "monthly": _html(_ARTICLE_SECOND)}
    )
    config = GitHubTrendingConfig(
        enabled=True,
        periods=["daily", "weekly", "monthly"],
        profile="trending",
        category="github-trending",
    )
    scraper = GitHubTrendingScraper(config, client)

    result = asyncio.run(scraper.fetch(SINCE))

    assert result.status == "success"
    assert result.successful == 3
    items = {item.metadata["repo"]: item for item in result.items}
    assert set(items) == {"meta/astryx", "anthropics/skills"}

    astryx = items["meta/astryx"]
    assert astryx.id == "github_trending:repo:meta/astryx"
    assert astryx.source_type.value == "github_trending"
    assert astryx.profile == "trending"
    assert astryx.metadata["category"] == "github-trending"
    assert astryx.metadata["period"] == "daily"
    assert astryx.metadata["stars_period"] == 3108
    assert set(astryx.metadata["periods"]) == {"daily", "weekly"}
    assert astryx.metadata["periods"]["weekly"]["rank"] == 1
    assert "Also on the trending page: weekly #1" in astryx.content
    assert str(astryx.url) == "https://github.com/meta/astryx"


def test_fetch_reports_a_failed_period_and_keeps_the_others() -> None:
    from httpx import HTTPStatusError, Request, Response

    client = AsyncMock()

    def _get(url, params=None, **kwargs):
        if params["since"] == "weekly":
            request = Request("GET", "https://github.com/trending")
            response = Response(429, request=request)
            raise HTTPStatusError("rate limited", request=request, response=response)
        response = MagicMock()
        response.text = _html(_ARTICLE)
        response.raise_for_status.return_value = None
        return response

    client.get.side_effect = _get
    config = GitHubTrendingConfig(enabled=True, periods=["daily", "weekly"])
    scraper = GitHubTrendingScraper(config, client)

    result = asyncio.run(scraper.fetch(SINCE))

    assert result.status == "partial_failure"
    assert "weekly" in result.failures
    assert result.successful == 1
    assert [item.metadata["repo"] for item in result.items] == ["meta/astryx"]


def test_disabled_source_fetches_nothing() -> None:
    client = AsyncMock()
    scraper = GitHubTrendingScraper(GitHubTrendingConfig(enabled=False), client)

    result = asyncio.run(scraper.fetch(SINCE))

    assert result.items == []
    client.get.assert_not_called()
