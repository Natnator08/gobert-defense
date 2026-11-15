# Gobert Defense Tracker

Head-to-head defensive analytics for **Rudy Gobert** against **Victor Wembanyama** and **Kevin Durant**, built
from every game they've played (ESPN box scores and play-by-play), with official video clips embedded from YouTube.

- Points, shooting and turnovers against Gobert's team vs. each player's other games
- On/off splits: how each player scored with Gobert on the court vs. on the bench
- Shot charts, every Gobert block on them, a season-by-season view, and a full game log

## Run it locally

```bash
python3 -m http.server 8000 -d site
# open http://localhost:8000
```

## Rebuild the data

```bash
python3 -m venv .venv
.venv/bin/pip install -r pipeline/requirements.txt
.venv/bin/python pipeline/build_all.py
```

ESPN responses are cached in `data_raw/` (git-ignored). The current season is refreshed on every build, so
re-running picks up new games. The build checks that play-by-play points and minutes match the box scores
and stops if too many games don't.

## Add NBA.com tracking data (optional)

NBA.com's matchup data credits each possession to a primary defender. It can't be downloaded automatically
here, but you can copy it from your browser:

1. Open https://www.nba.com/stats/players/matchups
2. Set **Season** (one at a time), **Season Type** (Regular Season, then Playoffs),
   **Defensive Player** = Rudy Gobert, **Offensive Player** = Victor Wembanyama (then Kevin Durant).
3. Select the results table with the mouse, copy it (Cmd+C), and paste it into `data/nba_matchups.txt`.
   Put a line like `## 2025-26 Regular Season` above each pasted table. Tracking data starts in 2017-18.
4. Rebuild. The importer reports any rows it couldn't read, and a "Gobert as primary defender" section
   appears on the site.

## Videos

Candidates are listed in `data/video_candidates.yaml`. The build checks each one with YouTube's oEmbed
endpoint and keeps it only if it exists, allows embedding, comes from an official channel listed in
`config.yaml`, and its title names Gobert. To add a clip, add its URL there and rebuild.

## Deploy

GitHub Actions publishes `site/` to GitHub Pages on every push to `main`
(`.github/workflows/pages.yml`), stamping file links with the commit id to avoid stale browser caches.
