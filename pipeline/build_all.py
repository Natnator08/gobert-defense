"""Build all site data.

    .venv/bin/python pipeline/build_all.py

ESPN responses are cached in data_raw/ (the current season is always refreshed).
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze import SPLIT_KEYS, analyze_game  # noqa: E402
from common import DATA, SITE_DATA, load_config, log, write_json  # noqa: E402
from fetch_games import head_to_head  # noqa: E402
from fetch_pbp import summary  # noqa: E402
import import_nba_matchups  # noqa: E402
import videos  # noqa: E402

MIN_SPLIT_MINUTES = 30  # below this, an on/off split is flagged as a small sample


def _made_att(s: str | None) -> tuple[int, int]:
    try:
        m, a = str(s).split("-")
        return int(m), int(a)
    except ValueError:
        return 0, 0


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def line_totals(lines: list[dict]) -> dict:
    """Sum box-score style lines ({'PTS','FG','3PT','FT','TO','MIN'}) into per-game averages."""
    n = len(lines)
    t = {"pts": 0, "fgm": 0, "fga": 0, "tpm": 0, "tpa": 0, "ftm": 0, "fta": 0, "tov": 0, "min": 0.0}
    for ln in lines:
        t["pts"] += _num(ln.get("PTS"))
        fgm, fga = _made_att(ln.get("FG")); t["fgm"] += fgm; t["fga"] += fga
        tpm, tpa = _made_att(ln.get("3PT")); t["tpm"] += tpm; t["tpa"] += tpa
        ftm, fta = _made_att(ln.get("FT")); t["ftm"] += ftm; t["fta"] += fta
        t["tov"] += _num(ln.get("TO"))
        t["min"] += _num(ln.get("MIN"))
    if not n:
        return {"games": 0}
    ts_den = 2 * (t["fga"] + 0.44 * t["fta"])
    return {
        "games": n,
        "pts": round(t["pts"] / n, 1), "fga": round(t["fga"] / n, 1), "tpa": round(t["tpa"] / n, 1),
        "fta": round(t["fta"] / n, 1), "tov": round(t["tov"] / n, 1), "min": round(t["min"] / n, 1),
        "fg_pct": round(t["fgm"] / t["fga"], 3) if t["fga"] else None,
        "tp_pct": round(t["tpm"] / t["tpa"], 3) if t["tpa"] else None,
        "ts_pct": round(t["pts"] / ts_den, 3) if ts_den else None,
    }


def split_summary(splits: list[dict]) -> dict:
    """Sum per-game on/off splits and derive rates."""
    out = {}
    for side in ("on", "off"):
        s = {k: sum(g[side][k] for g in splits) for k in SPLIT_KEYS}
        mins = s["sec"] / 60
        per36 = (lambda v: round(v / mins * 36, 1)) if mins else (lambda v: None)
        ts_den = 2 * (s["fga"] + 0.44 * s["fta"])
        out[side] = {
            "minutes": round(mins, 1), "pts": s["pts"], "fga": s["fga"], "fgm": s["fgm"],
            "rim_fga": s["rim_fga"], "rim_fgm": s["rim_fgm"], "tov": s["tov"], "blocked_by_gobert": s["blocked_by_gobert"],
            "pts_per36": per36(s["pts"]), "fga_per36": per36(s["fga"]), "rim_fga_per36": per36(s["rim_fga"]),
            "tov_per36": per36(s["tov"]),
            "fg_pct": round(s["fgm"] / s["fga"], 3) if s["fga"] else None,
            "rim_fg_pct": round(s["rim_fgm"] / s["rim_fga"], 3) if s["rim_fga"] else None,
            "tp_pct": round(s["tpm"] / s["tpa"], 3) if s["tpa"] else None,
            "ts_pct": round(s["pts"] / ts_den, 3) if ts_den else None,
            "small_sample": mins < MIN_SPLIT_MINUTES,
        }
    return out


def gamelog_line(stats: dict) -> dict:
    """ESPN game-log stats use the same labels as the box score except turnovers."""
    return {"PTS": stats.get("PTS"), "FG": stats.get("FG"), "3PT": stats.get("3PT"), "FT": stats.get("FT"),
            "TO": stats.get("TO"), "MIN": stats.get("MIN")}


def opponent_summary(opp: dict, games: list[dict], opp_logs: dict) -> dict:
    h2h_ids = {g["id"] for g in games}
    seasons = sorted({g["season"] for g in games})

    def baseline(season_list):
        lines = [gamelog_line(e["stats"]) for s in season_list for eid, e in opp_logs.get(s, {}).items()
                 if eid not in h2h_ids and _num(e["stats"].get("MIN")) > 0]
        return line_totals(lines)

    wins = sum(1 for g in games if g["result"] == "W")
    by_season = []
    for s in seasons:
        gs = [g for g in games if g["season"] == s]
        by_season.append({
            "season": s, "season_label": gs[0]["season_label"],
            "games": len(gs), "wins": sum(1 for g in gs if g["result"] == "W"),
            "vs_gobert": line_totals([g["opp_box"] for g in gs]),
            "other_games": baseline([s]),
            "on_off": split_summary([g["split"] for g in gs]),
            "gobert_blocks_on_him": sum(len(g["blocks"]) for g in gs),
        })
    return {
        "slug": opp["slug"], "name": opp["name"], "short": opp["short"],
        "games": len(games), "wins": wins, "losses": len(games) - wins,
        "playoff_games": sum(1 for g in games if g["season_type"] == "Playoffs"),
        "seasons": [s["season_label"] for s in by_season],
        "vs_gobert": line_totals([g["opp_box"] for g in games]),
        "other_games": baseline(seasons),
        "on_off": split_summary([g["split"] for g in games]),
        "gobert_blocks_on_him": sum(len(g["blocks"]) for g in games),
        "by_season": by_season,
    }


def game_without_pbp(g: dict) -> dict:
    """A head-to-head game ESPN has no play-by-play for: keep the game-log lines only."""
    gl, ol = g["gobert_line"], g["opponent_line_log"]
    empty = {k: 0 for k in SPLIT_KEYS}
    return {
        **{k: g[k] for k in ("id", "season", "season_label", "season_type", "date", "at_vs", "team", "opponent_team", "result", "score", "opponent")},
        "gobert_box": {"MIN": gl.get("MIN"), "PTS": gl.get("PTS"), "REB": gl.get("REB"), "AST": gl.get("AST"),
                       "STL": gl.get("STL"), "BLK": gl.get("BLK"), "FG": gl.get("FG"), "PF": gl.get("PF"), "+/-": None},
        "opp_box": {"MIN": ol.get("MIN"), "PTS": ol.get("PTS"), "FG": ol.get("FG"), "3PT": ol.get("3PT"),
                    "FT": ol.get("FT"), "REB": ol.get("REB"), "AST": ol.get("AST"), "TO": ol.get("TO"), "+/-": None},
        "split": {"on": dict(empty), "off": dict(empty)}, "blocks": [], "shots": [], "checks": None,
        "url": f"https://www.espn.com/nba/game/_/gameId/{g['id']}", "neutral_or_note": None, "pbp": False,
    }


def check(all_games: list[dict]) -> dict:
    with_pbp = [g for g in all_games if g["pbp"]]
    missing = [g["id"] for g in all_games if not g["pbp"]]
    assert len(missing) <= max(2, 0.10 * len(all_games)), f"too many games without play-by-play: {missing}"
    all_games = with_pbp
    pts_bad = [g["id"] for g in all_games if g["checks"]["pts_box"] != g["checks"]["pts_pbp"]]
    min_bad = [g["id"] for g in all_games
               if abs(g["checks"]["gobert_min_box"] - g["checks"]["gobert_min_pbp"]) > 2
               or abs(g["checks"]["opp_min_box"] - g["checks"]["opp_min_pbp"]) > 2]
    for gid in pts_bad:
        c = next(g for g in all_games if g["id"] == gid)["checks"]
        log(f"points mismatch in game {gid}: box {c['pts_box']} vs play-by-play {c['pts_pbp']}")
    for gid in min_bad:
        c = next(g for g in all_games if g["id"] == gid)["checks"]
        log(f"minutes off by >2 in game {gid}: Gobert {c['gobert_min_box']} vs {c['gobert_min_pbp']}, "
            f"opponent {c['opp_min_box']} vs {c['opp_min_pbp']}")
    assert len(pts_bad) <= max(1, 0.05 * len(all_games)), f"too many point mismatches: {pts_bad}"
    assert len(min_bad) <= max(2, 0.10 * len(all_games)), f"too many minute mismatches: {min_bad}"
    # Known series: all four 2024 first-round games vs Phoenix.
    sweep = [g for g in all_games if g["opponent"] == "durant" and g["season"] == 2024 and g["season_type"] == "Playoffs"]
    assert len(sweep) == 4, f"expected 4 playoff games vs Durant in 2024, found {len(sweep)}"
    log("sanity checks passed")
    return {"points_mismatch_games": pts_bad, "minutes_mismatch_games": min_bad, "no_pbp_games": missing}


def main():
    cfg = load_config()
    gid = cfg["defender"]["espn_id"]
    print("1/4 Finding head-to-head games")
    games, opp_logs = head_to_head(cfg)

    print("2/4 Analyzing play-by-play")
    all_games = []
    for g in games:
        opp = next(o for o in cfg["opponents"] if o["slug"] == g["opponent"])
        sm = summary(g["id"])
        if sm is None:
            log(f"no play-by-play on ESPN for {g['date']} ({g['id']}); using game-log lines only")
            all_games.append(game_without_pbp(g))
            continue
        a = analyze_game(g, sm, gid, opp["espn_id"])
        a["pbp"] = True
        all_games.append(a)
    # Names really belong to the ids in config.
    from analyze import box_lines
    sample = {}
    for g in all_games:
        if not g["pbp"]:
            continue
        for pid, line in box_lines(summary(g["id"])).items():
            sample.setdefault(pid, line["name"])
    for person in [cfg["defender"], *cfg["opponents"]]:
        assert sample.get(person["espn_id"]) == person["name"], f"ESPN id {person['espn_id']} is {sample.get(person['espn_id'])}, not {person['name']}"
    checks = check(all_games)

    print("3/4 Videos and NBA.com matchup data")
    vids = videos.build(cfg, all_games)
    matchups = import_nba_matchups.build(cfg)

    print("4/4 Writing site data")
    opponents = [opponent_summary(o, [g for g in all_games if g["opponent"] == o["slug"]], opp_logs[o["slug"]])
                 for o in cfg["opponents"]]
    shots = [{"game": g["id"], "date": g["date"], "season": g["season_label"], "opponent": g["opponent"], **s}
             for g in all_games for s in g["shots"]]
    blocks = [{"game": g["id"], "date": g["date"], "season": g["season_label"], "season_type": g["season_type"],
               "opponent": g["opponent"], "url": g["url"], **b} for g in all_games for b in g["blocks"]]
    game_rows = [{k: v for k, v in g.items() if k not in ("shots", "blocks")} | {"blocks": len(g["blocks"])}
                 for g in all_games]
    write_json(SITE_DATA / "summary.json", {
        "defender": cfg["defender"]["name"], "opponents": opponents, "checks": checks,
        "built": dt.date.today().isoformat(), "min_split_minutes": MIN_SPLIT_MINUTES,
        "has_nba_matchups": bool(matchups["rows"]),
    })
    write_json(SITE_DATA / "games.json", game_rows)
    write_json(SITE_DATA / "shots.json", shots)
    write_json(SITE_DATA / "blocks.json", blocks)
    write_json(SITE_DATA / "videos.json", vids)
    write_json(SITE_DATA / "matchups.json", matchups)

    for o in opponents:
        v, b, on, off = o["vs_gobert"], o["other_games"], o["on_off"]["on"], o["on_off"]["off"]
        print(f"\n{o['name']}: {o['games']} games ({o['playoff_games']} playoff), Gobert's team {o['wins']}-{o['losses']}")
        print(f"  vs Gobert:   {v['pts']} pts, {v['fg_pct']:.3f} FG%, TS {v['ts_pct']:.3f}")
        print(f"  other games: {b['pts']} pts, {b['fg_pct']:.3f} FG%, TS {b['ts_pct']:.3f}")
        print(f"  Gobert ON  ({on['minutes']} min): {on['pts_per36']} pts/36, FG {on['fg_pct']}, rim FGA/36 {on['rim_fga_per36']}, rim FG {on['rim_fg_pct']}")
        print(f"  Gobert OFF ({off['minutes']} min): {off['pts_per36']} pts/36, FG {off['fg_pct']}, rim FGA/36 {off['rim_fga_per36']}, rim FG {off['rim_fg_pct']}")
        print(f"  Gobert blocks on him: {o['gobert_blocks_on_him']}")
    print(f"\nVideos verified: {len(vids['videos'])}; NBA.com matchup rows: {len(matchups['rows'])}")


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    main()
