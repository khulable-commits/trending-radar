"""GitHub Trending page scraper.

GitHub publishes no API for its Trending page, so this scraper reads the
public HTML at https://github.com/trending and parses each repository row
with BeautifulSoup.

The page has no publication timestamps. Each snapshot therefore closes over
the concepts GitHub itself shows:

- the period window (``daily`` / ``weekly`` / ``monthly``)
- the rank inside that window
- the stars gained during that window

A repository that appears in more than one window is emitted once, and every
observed window is kept under ``metadata["periods"]`` so downstream AI stages
can describe, for example, "trending daily #1, monthly #9".
"""

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from ..models import ContentItem, GitHubTrendingConfig, SourceType
from .base import BaseScraper, FetchResult

_PERIOD_GAIN_LABELS = {
    "daily": "today",
    "weekly": "this week",
    "monthly": "this month",
}

_NUMBER = re.compile(r"[\d,]+")


class GitHubTrendingScraper(BaseScraper):
    """Scraper for the GitHub Trending page (daily/weekly/monthly)."""

    BASE_URL = "https://github.com/trending"

    HEADERS = {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 Horizon/1.0"
        ),
    }

    def __init__(self, config: GitHubTrendingConfig, http_client: httpx.AsyncClient):
        """Initialize scraper.

        Args:
            config: GitHub Trending source configuration
            http_client: Shared async HTTP client
        """
        super().__init__(config, http_client)
        self.cfg: GitHubTrendingConfig = config

    async def fetch(self, since: datetime) -> FetchResult:
        """Fetch every configured trending period and merge rows per repository.

        GitHub Trending is a snapshot of what is trending now, not a feed of
        dated publications, so ``since`` cannot filter rows. The orchestrator's
        collection window still bounds when the snapshot is used.
        """
        result = FetchResult()
        if not self.cfg.enabled:
            return result

        observed: Dict[str, dict] = {}
        for period in self.cfg.periods:
            try:
                rows = await self._fetch_period(period)
            except Exception as exc:
                result.fail(period, exc)
                continue
            result.successful += 1
            for row in rows:
                merged = observed.setdefault(
                    row["repo"],
                    {**row, "periods": {}},
                )
                merged["periods"][period] = {
                    "rank": row["rank"],
                    "stars_period": row["stars_period"],
                }

        ordered = sorted(
            observed.values(),
            key=lambda row: (row["periods"][row["period"]]["rank"], row["repo"]),
        )
        result.items = [self._row_to_item(row) for row in ordered]
        return result

    async def _fetch_period(self, period: str) -> List[dict]:
        """Fetch and parse one trending period."""
        params: Dict[str, str] = {"since": period}
        if self.cfg.language:
            params["language"] = self.cfg.language
        if self.cfg.spoken_language:
            params["spoken_language_code"] = self.cfg.spoken_language

        response = await self.client.get(
            self.BASE_URL,
            params=params,
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30.0,
        )
        response.raise_for_status()
        rows = self.parse_page(response.text, period)
        return rows[: self.cfg.max_items_per_period]

    def parse_page(self, html: str, period: str) -> List[dict]:
        """Parse a Trending page into raw row dictionaries."""
        soup = BeautifulSoup(html, "html.parser")
        rows: List[dict] = []

        for rank, article in enumerate(soup.select("article.Box-row"), start=1):
            link = article.select_one("h2 a[href]")
            if link is None or not link.get("href"):
                continue
            repo = link["href"].strip("/")
            if repo.count("/") != 1:
                continue

            description = ""
            description_el = article.select_one("p")
            if description_el is not None:
                description = description_el.get_text(" ", strip=True)

            language_el = article.select_one('[itemprop="programmingLanguage"]')
            primary_language = (
                language_el.get_text(" ", strip=True) if language_el is not None else None
            )

            stars_total = self._int_from(
                article.select_one('a[href$="/stargazers"]')
            )
            forks_total = self._int_from(article.select_one('a[href$="/forks"]'))
            gained_el = article.select_one("span.float-sm-right")
            stars_period = self._int_from(gained_el)

            rows.append(
                {
                    "repo": repo,
                    "rank": rank,
                    "period": period,
                    "description": description,
                    "primary_language": primary_language,
                    "stars_total": stars_total,
                    "stars_period": stars_period,
                    "forks_total": forks_total,
                }
            )

        return rows

    def _row_to_item(self, row: dict) -> ContentItem:
        """Convert one merged trending row into a ContentItem."""
        repo = row["repo"]
        period = row["period"]
        stars_period = row["stars_period"]
        rank = row["periods"][period]["rank"]
        gain_label = _PERIOD_GAIN_LABELS.get(period, period)

        title = f"{repo} — {stars_period:,} stars {gain_label} (GitHub trending #{rank})"

        content_lines = [
            f"GitHub Trending ({period}) rank #{rank}",
            f"Repository: {repo}",
        ]
        if row["description"]:
            content_lines.append(f"Description: {row['description']}")
        if row["primary_language"]:
            content_lines.append(f"Primary language: {row['primary_language']}")
        content_lines.append(f"Total stars: {row['stars_total']:,}")
        content_lines.append(f"Stars gained {gain_label}: {stars_period:,}")
        content_lines.append(f"Total forks: {row['forks_total']:,}")

        other_periods = [
            f"{name} #{info['rank']} (+{info['stars_period']:,} stars)"
            for name, info in row["periods"].items()
            if name != period
        ]
        if other_periods:
            content_lines.append(
                "Also on the trending page: " + ", ".join(other_periods)
            )
        content_lines.append(f"Link: https://github.com/{repo}")

        owner = repo.split("/")[0]

        return ContentItem(
            id=self._generate_id(SourceType.GITHUB_TRENDING.value, "repo", repo),
            source_type=SourceType.GITHUB_TRENDING,
            title=title,
            url=f"https://github.com/{repo}",
            content="\n".join(content_lines),
            author=owner,
            published_at=datetime.now(timezone.utc),
            profile=self.cfg.profile,
            metadata={
                "repo": repo,
                "rank": rank,
                "period": period,
                "periods": row["periods"],
                "stars_total": row["stars_total"],
                "stars_period": stars_period,
                "forks_total": row["forks_total"],
                "primary_language": row["primary_language"],
                "description": row["description"],
                "trending_url": f"{self.BASE_URL}?since={period}",
                "category": self.cfg.category,
            },
        )

    @staticmethod
    def _int_from(element) -> int:
        """Read the first integer shown inside an element, defaulting to 0."""
        if element is None:
            return 0
        text = element.get_text(" ", strip=True)
        match = _NUMBER.search(text)
        if match is None:
            return 0
        try:
            return int(match.group(0).replace(",", ""))
        except ValueError:
            return 0
