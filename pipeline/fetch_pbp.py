"""ESPN game summaries (box score + play-by-play), cached per game."""
from __future__ import annotations

from common import RAW, cached_json

SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"


def summary(event_id: str) -> dict | None:
    """Box score + play-by-play, or None when ESPN has no summary/play-by-play for the game."""
    data = cached_json(SUMMARY, RAW / "summaries" / f"{event_id}.json", params={"event": event_id})
    if not data or not data.get("plays"):
        return None
    return data
