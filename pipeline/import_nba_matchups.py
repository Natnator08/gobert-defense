"""Optional: parse NBA.com matchup tables the user copied into data/nba_matchups.txt.

Paste format (see README): a line like "## 2025-26 Regular Season" above each table
copied from https://www.nba.com/stats/players/matchups (Defensive Player = Rudy
Gobert, Offensive Player = the opponent). Tab- or multi-space-separated pastes are
both accepted. Rows that can't be read are reported, not guessed at.
"""
from __future__ import annotations

import re

from common import DATA, log

SECTION_RE = re.compile(r"^##\s*(\d{4}-\d{2})\s*(Regular Season|Playoffs|Play-In)?", re.I)
COLUMN_ALIASES = {
    "gp": ["gp"], "matchup_min": ["matchup min", "matchupmin", "min"], "partial_poss": ["partial poss", "partialposs", "poss"],
    "player_pts": ["player pts", "playerpts", "pts"], "team_pts": ["team pts", "teampts"],
    "ast": ["ast"], "tov": ["tov"], "blk": ["blk"], "fgm": ["fgm"], "fga": ["fga"], "fg_pct": ["fg%"],
    "tpm": ["3pm"], "tpa": ["3pa"], "tp_pct": ["3p%"], "ftm": ["ftm"], "fta": ["fta"], "sfl": ["sfl"],
}


def _split(line: str) -> list[str]:
    return [c.strip() for c in (line.split("\t") if "\t" in line else re.split(r"\s{2,}", line)) if c.strip()]


def _num(v: str):
    v = v.strip().replace(",", "")
    if re.fullmatch(r"\d+:\d{2}", v):          # "12:34" minutes
        m, s = v.split(":")
        return round(int(m) + int(s) / 60, 2)
    try:
        return float(v)
    except ValueError:
        return None


def build(cfg: dict) -> dict:
    path = DATA / "nba_matchups.txt"
    if not path.exists():
        return {"rows": [], "problems": []}
    opponents = {o["slug"]: o["name"].split()[-1].lower() for o in cfg["opponents"]}
    rows, problems = [], []
    season = season_type = None
    header = None
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        m = SECTION_RE.match(line)
        if m:
            season, season_type, header = m.group(1), (m.group(2) or "Regular Season").title(), None
            continue
        cells = _split(raw)
        low = [c.lower() for c in cells]
        if any("partial" in c or "matchup" in c for c in low):
            header = low
            continue
        if header is None or season is None:
            continue
        opp = next((slug for slug, last in opponents.items() if last in line.lower()), None)
        if opp is None:
            continue  # other rows (e.g. a different offensive player) are ignored
        nums = [c for c in cells if _num(c) is not None]
        num_headers = [h for h in header if h not in ("off player", "def player", "player", "offensive player", "defensive player")]
        if len(nums) != len(num_headers):
            problems.append(f"line {n}: expected {len(num_headers)} numbers, found {len(nums)}")
            continue
        rec = {"season": season, "season_type": season_type, "opponent": opp}
        for h, v in zip(num_headers, nums):
            key = next((k for k, al in COLUMN_ALIASES.items() if h in al), None)
            if key:
                rec[key] = _num(v)
        if rec.get("partial_poss"):
            rec["pts_per_100_poss"] = round(rec.get("player_pts", 0) / rec["partial_poss"] * 100, 1)
        rows.append(rec)
    for p in problems:
        log(f"NBA matchups: {p}")
    log(f"NBA matchups: {len(rows)} rows read")
    return {"rows": rows, "problems": problems}
