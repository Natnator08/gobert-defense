"""Verify candidate videos of Gobert defending each opponent.

Candidates live in data/video_candidates.yaml (found by web search). Each is checked
with YouTube's public oEmbed endpoint, which confirms the video exists, allows
embedding, and reports its real title and channel. A video is kept only if:
  * the channel is on the official allowlist in config.yaml, and
  * the official title names Gobert ("Gobert" or "Rudy"), so it's about his play,
    not just the game.
Nothing is downloaded or re-hosted; the site embeds the official upload.
"""
from __future__ import annotations

import json
import re

import yaml

from common import DATA, RAW, get, log

OEMBED = "https://www.youtube.com/oembed"
ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def oembed(video_id: str) -> tuple[int, dict | None]:
    cache = RAW / "oembed" / f"{video_id}.json"
    if cache.exists():
        d = json.loads(cache.read_text())
        return d["status"], d.get("data")
    r = get(OEMBED, params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"})
    data = r.json() if r.status_code == 200 else None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"status": r.status_code, "data": data}))
    return r.status_code, data


def build(cfg: dict, games: list[dict]) -> dict:
    path = DATA / "video_candidates.yaml"
    candidates = (yaml.safe_load(path.read_text()) or []) if path.exists() else []
    allow = {c.lower() for c in cfg["video_channels"]}
    by_date = {(g["opponent"], g["date"]): g for g in games}
    kept, rejected = [], []
    for c in candidates:
        m = ID_RE.search(c["url"])
        if not m:
            rejected.append({"url": c["url"], "reason": "not a YouTube video URL"})
            continue
        vid = m.group(1)
        status, data = oembed(vid)
        if status != 200 or not data:
            reason = {401: "embedding disabled", 403: "private or blocked", 404: "not found"}.get(status, f"HTTP {status}")
            rejected.append({"url": c["url"], "reason": reason})
            continue
        channel, title = data.get("author_name", ""), data.get("title", "")
        if channel.lower() not in allow:
            rejected.append({"url": c["url"], "reason": f"channel not on allowlist: {channel}"})
            continue
        if not any(n in title.lower() for n in ("gobert", "rudy")):
            rejected.append({"url": c["url"], "reason": f"title doesn't name Gobert: {title}"})
            continue
        game = by_date.get((c.get("opponent"), c.get("date")))
        kept.append({
            "id": vid, "title": title, "channel": channel, "thumbnail": data.get("thumbnail_url"),
            "short": "/shorts/" in c["url"],  # vertical video
            "opponent": c.get("opponent"), "date": c.get("date"), "shows": c.get("shows", ""),
            "game": game["id"] if game else None,
            "game_label": f"{game['season_label']} {game['season_type']}, {game['date']}" if game else None,
        })
    for r in rejected:
        log(f"video rejected ({r['reason']}): {r['url']}")
    log(f"{len(kept)} of {len(candidates)} candidate videos verified")
    return {"videos": kept, "rejected": len(rejected)}
