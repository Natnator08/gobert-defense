"""Find every game where Gobert and an opponent both played, from ESPN game logs.

A head-to-head game is any regular-season or playoff game that appears in BOTH
players' ESPN game logs (so games either of them missed are excluded).
"""
from __future__ import annotations

import datetime as dt

from common import RAW, cached_json, log, season_label

GAMELOG = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{pid}/gamelog"


def current_season() -> int:
    today = dt.date.today()
    return today.year + 1 if today.month >= 10 else today.year


def gamelog(pid: str, season: int) -> dict:
    """{event_id: {...game info, 'stats': {label: value}}} for one player-season (no preseason)."""
    data = cached_json(GAMELOG.format(pid=pid), RAW / "gamelogs" / f"{pid}_{season}.json",
                       params={"season": season}, refresh=season >= current_season())
    if not data or not data.get("seasonTypes"):
        return {}
    labels = data["labels"]
    out = {}
    for st in data["seasonTypes"]:
        name = st.get("displayName", "")
        if "Preseason" in name:
            continue
        kind = "Playoffs" if "Postseason" in name else ("Play-In" if "Play" in name and "In" in name else "Regular Season")
        for cat in st.get("categories", []):
            for e in cat.get("events", []):
                ev = data["events"].get(e["eventId"], {})
                out[e["eventId"]] = {
                    "id": e["eventId"],
                    "season": season,
                    "season_label": season_label(season),
                    "season_type": kind,
                    "date": ev.get("gameDate", "")[:10],
                    "at_vs": ev.get("atVs"),
                    "team": (ev.get("team") or {}).get("abbreviation"),
                    "opponent_team": (ev.get("opponent") or {}).get("abbreviation"),
                    "result": ev.get("gameResult"),
                    "score": ev.get("score"),
                    "stats": dict(zip(labels, e["stats"])),
                }
    return out


def head_to_head(cfg: dict) -> tuple[list[dict], dict]:
    """Head-to-head games for every opponent, plus each opponent's full game logs by season."""
    d = cfg["defender"]
    last = min(cfg["last_season"], current_season())
    games, opp_logs = [], {}
    for opp in cfg["opponents"]:
        first = max(d["first_season"], opp["first_season"])
        opp_logs[opp["slug"]] = {}
        for season in range(first, last + 1):
            g_log = gamelog(d["espn_id"], season)
            o_log = gamelog(opp["espn_id"], season)
            opp_logs[opp["slug"]][season] = o_log
            common = sorted(set(g_log) & set(o_log), key=lambda e: g_log[e]["date"])
            for eid in common:
                g = dict(g_log[eid])
                g["opponent"] = opp["slug"]
                g["gobert_line"] = g.pop("stats")
                g["opponent_line_log"] = o_log[eid]["stats"]
                games.append(g)
            if common:
                log(f"{season_label(season)}: {len(common)} games vs {opp['short']}")
    return games, opp_logs
