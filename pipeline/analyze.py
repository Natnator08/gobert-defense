"""Turn ESPN box scores and play-by-play into head-to-head defensive analytics.

For each game:
  * box-score lines for Gobert and the opponent
  * when each of them was on the court, rebuilt from starters + substitutions
  * the opponent's shots, points, free throws and turnovers, split by whether
    Gobert was on the court at that moment (only counting time the opponent played)
  * every Gobert block on the opponent
"""
from __future__ import annotations

import re

PERIOD_SEC = 720
OT_SEC = 300
DIST_RE = re.compile(r"(\d+)-foot")
SPLIT_KEYS = ["sec", "pts", "fga", "fgm", "tpa", "tpm", "fta", "ftm", "rim_fga", "rim_fgm", "tov", "blocked_by_gobert"]


def _period_len(p: int) -> int:
    return PERIOD_SEC if p <= 4 else OT_SEC


def _period_start(p: int) -> int:
    return sum(_period_len(i) for i in range(1, p))


def _clock_sec(s: str) -> float:
    """'11:39' -> 699, '6.0' -> 6.0 (seconds remaining in the period)."""
    s = (s or "0").strip()
    if ":" in s:
        m, sec = s.split(":")
        return int(m) * 60 + float(sec)
    return float(s)


def _abs_time(play: dict) -> float:
    p = play["period"]["number"]
    return _period_start(p) + _period_len(p) - _clock_sec(play["clock"]["displayValue"])


def _ids(play: dict) -> list[str]:
    return [x["athlete"]["id"] for x in play.get("participants", []) if x.get("athlete")]


def _is_sub(play: dict) -> bool:
    return play.get("type", {}).get("text") == "Substitution"


# --------------------------------------------------------------------------- box score
def box_lines(summary: dict) -> dict[str, dict]:
    """{athlete_id: {label: value, 'starter': bool, 'team': abbr}} from the ESPN box score."""
    out = {}
    for team in summary["boxscore"].get("players", []):
        abbr = team["team"]["abbreviation"]
        for stat_block in team.get("statistics", []):
            labels = stat_block.get("names") or stat_block.get("labels") or []
            for a in stat_block.get("athletes", []):
                if not a.get("stats"):
                    continue
                line = dict(zip(labels, a["stats"]))
                line.update(starter=bool(a.get("starter")), team=abbr, name=a["athlete"]["displayName"])
                out[a["athlete"]["id"]] = line
    return out


# --------------------------------------------------------------------------- on-court intervals
def chronological(plays: list[dict]) -> list[dict]:
    """ESPN sequence numbers aren't always in time order, so sort by period and game
    clock, keeping sequence order for plays at the same moment (e.g. subs between
    free throws)."""
    return sorted(plays, key=lambda p: (p["period"]["number"], -_clock_sec(p["clock"]["displayValue"]),
                                        int(p.get("sequenceNumber", 0))))


def _period_walk(pp: list[dict], pid: str, on: bool, start: float, end: float) -> tuple[list, bool]:
    """Intervals within one period given the status at its start; returns (intervals, status at end)."""
    intervals, since = [], start if on else None
    for p in pp:
        if not _is_sub(p):
            continue
        ids = _ids(p)
        if len(ids) < 2:
            continue
        t = _abs_time(p)
        if ids[0] == pid and not on:          # enters
            on, since = True, t
        elif ids[1] == pid and on:            # leaves
            on = False
            intervals.append((since, t))
    if on:
        intervals.append((since, end))
    return intervals, on


def on_court_intervals(plays: list[dict], pid: str, starter: bool, box_min: float | None = None) -> list[tuple[float, float]]:
    """Time intervals (absolute seconds from tip-off) when player pid was on the court.

    Period starts aren't logged. For periods after the first, a player counts as on
    the court at the start if their first involvement in the period is anything other
    than checking in. A period where the player has no involvement at all is
    ambiguous: older ESPN data often skips the substitution when a player sits out a
    whole quarter. Each ambiguous period is either fully on or fully off, so we pick
    the combination whose total minutes best match the official box-score minutes
    (ties keep the status carried over from the previous period).
    """
    plays = chronological(plays)
    periods = sorted({p["period"]["number"] for p in plays})
    segments = []  # per period: ("fixed", intervals) or ("ambiguous", start, end)
    on = starter
    for per in periods:
        pp = [p for p in plays if p["period"]["number"] == per]
        start, end = _period_start(per), _period_start(per) + _period_len(per)
        involved = [p for p in pp if pid in _ids(p)]
        if per > 1:
            if not involved:
                segments.append(("ambiguous", start, end, on))
                continue
            first = involved[0]
            on = (_ids(first)[0] != pid) if _is_sub(first) else True
        ivs, on = _period_walk(pp, pid, on, start, end)
        segments.append(("fixed", ivs))

    ambiguous = [i for i, s in enumerate(segments) if s[0] == "ambiguous"]

    def assemble(choice: dict) -> list:
        out = []
        for i, s in enumerate(segments):
            if s[0] == "fixed":
                out += s[1]
            elif choice[i]:
                out.append((s[1], s[2]))
        return out

    # Default: carry over the status at the end of the previous period.
    best = {i: segments[i][3] for i in ambiguous}
    if ambiguous and box_min:
        def err(choice):
            return abs(sum(b - a for a, b in assemble(choice)) / 60 - box_min)
        candidates = []
        for mask in range(2 ** len(ambiguous)):
            choice = {i: bool(mask >> k & 1) for k, i in enumerate(ambiguous)}
            candidates.append((err(choice), choice != best, choice))
        best = min(candidates, key=lambda c: (round(c[0], 2), c[1]))[2]
    return [(a, b) for a, b in assemble(best) if b > a]


def _covers(intervals, t: float) -> bool:
    return any(a <= t <= b for a, b in intervals)


def _overlap(a_int, b_int) -> float:
    total = 0.0
    for a1, a2 in a_int:
        for b1, b2 in b_int:
            total += max(0.0, min(a2, b2) - max(a1, b1))
    return total


def _minutes(box_min: str) -> float:
    try:
        return float(box_min)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- one game
def analyze_game(game: dict, summary: dict, gobert_id: str, opp_id: str) -> dict:
    plays = chronological(summary["plays"])
    box = box_lines(summary)
    g_box, o_box = box.get(gobert_id, {}), box.get(opp_id, {})

    # Who was on the court, and when. Status at an exact play is tracked sequentially
    # so substitutions between free throws are handled in order.
    g_int = on_court_intervals(plays, gobert_id, g_box.get("starter", False), _minutes(g_box.get("MIN")))
    o_int = on_court_intervals(plays, opp_id, o_box.get("starter", False), _minutes(o_box.get("MIN")))
    total_game = _period_start(max(p["period"]["number"] for p in plays) + 1)
    g_off = []
    cursor = 0.0
    for a, b in sorted(g_int):
        if a > cursor:
            g_off.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < total_game:
        g_off.append((cursor, total_game))

    split = {k: {key: 0 for key in SPLIT_KEYS} for k in ("on", "off")}
    split["on"]["sec"] = round(_overlap(o_int, g_int), 1)
    split["off"]["sec"] = round(_overlap(o_int, g_off), 1)

    # Sequential on/off state for Gobert so same-timestamp subs resolve in play order.
    g_state = g_box.get("starter", False)
    period_seen = set()
    shots, blocks = [], []
    for p in plays:
        per = p["period"]["number"]
        if per not in period_seen:
            period_seen.add(per)
            g_state = _covers(g_int, _period_start(per) + 0.5)
        ids = _ids(p)
        if _is_sub(p) and len(ids) >= 2:
            if ids[0] == gobert_id:
                g_state = True
            elif ids[1] == gobert_id:
                g_state = False
            continue
        if not ids or ids[0] != opp_id:
            continue
        s = split["on" if g_state else "off"]
        ttype = p.get("type", {}).get("text", "")
        text = p.get("text", "")
        if p.get("shootingPlay"):
            if ttype.startswith("Free Throw") or "free throw" in text.lower():
                # Older ESPN data gives made free throws a scoreValue of 0, so count 1 point directly.
                made_ft = bool(p.get("scoringPlay")) and "misses" not in text.lower()
                s["fta"] += 1
                s["ftm"] += made_ft
                s["pts"] += 1 if made_ft else 0
                continue
            pts = int(p.get("scoreValue") or 0) if p.get("scoringPlay") else 0
            s["pts"] += pts
            made = bool(p.get("scoringPlay"))
            three = p.get("pointsAttempted") == 3 or "three point" in text.lower()
            m = DIST_RE.search(text)
            dist = int(m.group(1)) if m else None
            rim = (dist is not None and dist <= 4) or (dist is None and any(w in ttype.lower() for w in ("layup", "dunk", "tip")))
            blocked = "blocks" in text and len(ids) > 1 and ids[1] == gobert_id
            s["fga"] += 1
            s["fgm"] += made
            s["tpa"] += three
            s["tpm"] += three and made
            s["rim_fga"] += rim
            s["rim_fgm"] += rim and made
            s["blocked_by_gobert"] += blocked
            c = p.get("coordinate") or {}
            x, y = c.get("x"), c.get("y")
            valid = x is not None and y is not None and -5 <= x <= 55 and -5 <= y <= 94
            shots.append({"x": x if valid else None, "y": y if valid else None, "made": made, "three": three,
                          "dist": dist, "gobert_on": g_state, "blocked": blocked,
                          "period": per, "clock": p["clock"]["displayValue"], "type": ttype})
            if blocked:
                blocks.append({"period": per, "clock": p["clock"]["displayValue"], "text": text, "type": ttype, "dist": dist})
        elif "turnover" in ttype.lower():
            s["tov"] += 1

    pts_pbp = split["on"]["pts"] + split["off"]["pts"]
    g_min_pbp = sum(b - a for a, b in g_int) / 60
    o_min_pbp = sum(b - a for a, b in o_int) / 60
    checks = {
        "pts_box": int(o_box.get("PTS", 0) or 0), "pts_pbp": pts_pbp,
        "gobert_min_box": _minutes(g_box.get("MIN")), "gobert_min_pbp": round(g_min_pbp, 1),
        "opp_min_box": _minutes(o_box.get("MIN")), "opp_min_pbp": round(o_min_pbp, 1),
    }
    header = summary.get("header", {}).get("competitions", [{}])[0]
    return {
        **{k: game[k] for k in ("id", "season", "season_label", "season_type", "date", "at_vs", "team", "opponent_team", "result", "score", "opponent")},
        "gobert_box": {k: g_box.get(k) for k in ("MIN", "PTS", "REB", "AST", "STL", "BLK", "FG", "PF", "+/-")},
        "opp_box": {k: o_box.get(k) for k in ("MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "+/-")},
        "split": split, "blocks": blocks, "shots": shots, "checks": checks,
        "url": f"https://www.espn.com/nba/game/_/gameId/{game['id']}",
        "neutral_or_note": header.get("notes", [{}])[0].get("headline") if header.get("notes") else None,
    }
