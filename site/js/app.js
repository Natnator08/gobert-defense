import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6.17/+esm";

const VERSION = "__VERSION__";
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(1)}%`);
const num = (v, d = 1) => (v === null || v === undefined ? "–" : Number(v).toFixed(d));
const getJSON = (f) => fetch(`data/${f}?v=${VERSION}`).then((r) => { if (!r.ok) throw new Error(`Could not load ${f}`); return r.json(); });

let S, games, shots, blocks, videos, matchups;
const state = { opp: null, season: "all" };

// ------------------------------------------------------------------ helpers
const opp = () => S.opponents.find((o) => o.slug === state.opp);
function scope() {
  // Season-level aggregates when one season is selected, career otherwise.
  const o = opp();
  return state.season === "all" ? o : o.by_season.find((s) => s.season_label === state.season);
}
const inScope = (row) => row.opponent === state.opp && (state.season === "all" || row.season === state.season || row.season_label === state.season);

/** Signed difference with wording from Gobert's point of view (lower = better defense). */
function delta(v, base, fmt, lowerIsGood = true) {
  if (v === null || base === null || v === undefined || base === undefined) return "";
  const d = v - base;
  if (Math.abs(d) < 1e-9) return `<span class="delta">Same as his other games</span>`;
  const good = lowerIsGood ? d < 0 : d > 0;
  const sign = d > 0 ? "+" : "−";
  return `<span class="delta ${good ? "good" : "bad"}">${sign}${fmt(Math.abs(d))} vs his other games ${good ? "▼" : "▲"}</span>`;
}

// ------------------------------------------------------------------ controls
function renderControls() {
  document.getElementById("opp-buttons").innerHTML = S.opponents.map((o) =>
    `<button type="button" data-opp="${o.slug}" aria-pressed="${o.slug === state.opp}">${esc(o.short)}</button>`).join("");
  document.querySelectorAll("[data-opp]").forEach((b) => b.addEventListener("click", () => {
    state.opp = b.dataset.opp; state.season = "all";
    history.replaceState(null, "", `?vs=${state.opp}`);
    renderAll();
  }));
  const sel = document.getElementById("season-select");
  const o = opp();
  sel.innerHTML = `<option value="all">All seasons (${o.games} games)</option>` +
    o.by_season.slice().reverse().map((s) => `<option value="${s.season_label}">${s.season_label} (${s.games} game${s.games > 1 ? "s" : ""})</option>`).join("");
  sel.value = state.season;
  sel.onchange = () => { state.season = sel.value; renderAll(false); };
}

// ------------------------------------------------------------------ tiles
function renderTiles() {
  const o = opp(), sc = scope();
  const v = sc.vs_gobert, b = sc.other_games;
  const blocksN = sc.gobert_blocks_on_him;
  const record = state.season === "all" ? `${o.wins}–${o.losses}` : `${sc.wins}–${sc.games - sc.wins}`;
  document.getElementById("tiles").innerHTML = `
    <div class="tile stat"><span class="stat-label">Games vs. Gobert</span><span class="stat-value">${sc.games}</span>
      <span class="stat-note">Gobert's team went ${record}${state.season === "all" ? ` · ${o.playoff_games} playoff games` : ""}</span></div>
    <div class="tile stat"><span class="stat-label">${esc(o.short)}'s points per game</span><span class="stat-value">${num(v.pts)}</span>
      ${delta(v.pts, b.pts, (x) => x.toFixed(1))}<span class="stat-note">${num(b.pts)} in his other games${state.season === "all" ? " those seasons" : ""}</span></div>
    <div class="tile stat"><span class="stat-label">${esc(o.short)}'s true shooting</span><span class="stat-value">${pct(v.ts_pct)}</span>
      ${delta(v.ts_pct, b.ts_pct, (x) => `${(x * 100).toFixed(1)} pts`)}<span class="stat-note">${pct(b.ts_pct)} in his other games · shooting efficiency incl. 3s and free throws</span></div>
    <div class="tile stat"><span class="stat-label">Gobert's blocks on ${esc(o.short)}</span><span class="stat-value">${blocksN}</span>
      <span class="stat-note">${(blocksN / sc.games).toFixed(2)} per game, from play-by-play</span></div>`;
}

// ------------------------------------------------------------------ on/off pairs
const PAIR_METRICS = [
  ["pts_per36", "Points per 36 minutes", (v) => num(v), true],
  ["fg_pct", "Field-goal %", pct, true],
  ["rim_fga_per36", "Shots at the rim per 36", (v) => num(v), true],
  ["rim_fg_pct", "Field-goal % at the rim", pct, true],
  ["tov_per36", "Turnovers per 36", (v) => num(v), false],
];
function renderPairs() {
  const oo = scope().on_off;
  const on = oo.on, off = oo.off;
  document.getElementById("onoff-note").innerHTML =
    `${esc(opp().short)} played <strong>${num(on.minutes, 0)} minutes</strong> with Gobert on the court and <strong>${num(off.minutes, 0)} minutes</strong> with Gobert on the bench in the selected games.` +
    (on.small_sample || off.small_sample ? ` <span class="flag">small sample: under ${S.min_split_minutes} minutes</span>` : "");
  document.getElementById("pairs").innerHTML = PAIR_METRICS.map(([k, label, f, lowerGood]) => {
    const a = on[k], b = off[k];
    const max = Math.max(a ?? 0, b ?? 0) || 1;
    let verdict = "";
    if (a !== null && b !== null && a !== b) {
      const better = lowerGood ? a < b : a > b;
      const why = lowerGood ? "" : better ? " (more turnovers forced)" : " (fewer turnovers forced)";
      verdict = `<div class="note">${better ? "Better" : "Worse"} for Gobert's team with him on the court${why}</div>`;
    }
    const row = (cls, name, v) => `<div class="pair-row"><span>${name}</span><span class="pair-track"><span class="pair-scale"><span class="pair-bar ${cls}" style="width:${((v ?? 0) / max) * 100}%"></span></span><span class="pair-val">${f(v)}</span></span></div>`;
    return `<figure class="card pair-card" style="margin:0" role="img" aria-label="${esc(label)}: ${f(a)} with Gobert on the court, ${f(b)} with Gobert on the bench">
      <h3>${esc(label)}</h3>${row("on", "Gobert on", a)}${row("off", "Gobert off", b)}${verdict}</figure>`;
  }).join("");
}

// ------------------------------------------------------------------ season chart (Observable Plot)
function renderSeasons() {
  const o = opp();
  const rows = o.by_season.map((s) => ({ season: s.season_label, kind: "vs. Gobert", pts: s.vs_gobert.pts, games: s.games, ts: s.vs_gobert.ts_pct }))
    .concat(o.by_season.map((s) => ({ season: s.season_label, kind: "His other games", pts: s.other_games.pts, games: s.other_games.games, ts: s.other_games.ts_pct })));
  const box = document.getElementById("season-chart");
  const width = Math.min(1100, box.clientWidth || 900);
  const blue = css("--accent"), muted = css("--muted"), surface = css("--surface");
  const selected = state.season;
  const chart = Plot.plot({
    width, height: 300, marginLeft: 48, marginBottom: 40,
    style: { background: "transparent", color: css("--text-2"), fontSize: "13px", fontFamily: css("--font") },
    x: { label: null, domain: o.by_season.map((s) => s.season_label), padding: 0.4 },
    y: { label: "↑ Points per game", grid: true, zero: true },
    marks: [
      Plot.gridY({ stroke: css("--grid"), strokeOpacity: 1 }),
      Plot.ruleY([0], { stroke: css("--axis") }),
      Plot.ruleX(o.by_season, { x: "season_label", y1: (d) => d.vs_gobert.pts, y2: (d) => d.other_games.pts, stroke: css("--axis"), strokeWidth: 2 }),
      Plot.dot(rows.filter((r) => r.kind === "His other games"), { x: "season", y: "pts", r: 5, stroke: muted, strokeWidth: 2, fill: surface }),
      Plot.dot(rows.filter((r) => r.kind === "vs. Gobert"), { x: "season", y: "pts", r: 6, fill: blue, stroke: surface, strokeWidth: 2,
        fillOpacity: (d) => (selected === "all" || d.season === selected ? 1 : 0.3) }),
      Plot.tip(rows, Plot.pointer({ x: "season", y: "pts", fill: surface, stroke: css("--axis"),
        title: (d) => `${d.season} · ${d.kind}\n${d.pts} points per game (${d.games} games)\nTrue shooting ${pct(d.ts)}` })),
    ],
  });
  chart.setAttribute("role", "img");
  chart.setAttribute("aria-label", `${o.short}'s points per game against Gobert's team by season, compared with his other games. Full numbers in the table below.`);
  box.replaceChildren(chart);
  document.getElementById("season-legend").innerHTML =
    `<span><span class="swatch-dot" style="background:${blue}"></span>vs. Gobert's team</span>
     <span><span class="swatch-dot" style="background:${surface};box-shadow:0 0 0 2px ${muted}"></span>His other games that season</span>`;
  document.getElementById("season-table").innerHTML = `<table><thead><tr><th>Season</th><th class="n">Games vs. Gobert</th><th class="n">Pts vs. Gobert</th><th class="n">TS% vs. Gobert</th><th class="n">Pts other games</th><th class="n">TS% other games</th><th class="n">Pts/36 Gobert on</th><th class="n">Pts/36 Gobert off</th></tr></thead><tbody>${
    o.by_season.map((s) => `<tr><td>${s.season_label}</td><td class="n">${s.games}</td><td class="n">${num(s.vs_gobert.pts)}</td><td class="n">${pct(s.vs_gobert.ts_pct)}</td><td class="n">${num(s.other_games.pts)}</td><td class="n">${pct(s.other_games.ts_pct)}</td><td class="n">${num(s.on_off.on.pts_per36)}</td><td class="n">${num(s.on_off.off.pts_per36)}</td></tr>`).join("")}</tbody></table>`;
}

// ------------------------------------------------------------------ shot charts (SVG half court, feet)
// ESPN coordinates: x 0–50 across the court, y = feet from the rim toward half court (rim ≈ (25, 0)).
function courtSVG(list, color, title) {
  const X = (x) => x, Y = (y) => 42 - y;            // flip so the rim is at the bottom
  const line = css("--axis"), surface = css("--surface");
  const arc = (r, a0, a1, cy = 0) => {
    const pts = [];
    for (let a = a0; a <= a1 + 1e-6; a += (a1 - a0) / 40) pts.push(`${X(25 + r * Math.cos(a)).toFixed(2)},${Y(cy + r * Math.sin(a)).toFixed(2)}`);
    return `<polyline points="${pts.join(" ")}" fill="none" stroke="${line}" stroke-width=".25"/>`;
  };
  const t3 = Math.asin(8.95 / 23.75);
  const court = `
    <rect x="0" y="${Y(42)}" width="50" height="${42 + 5.25}" fill="none" stroke="${line}" stroke-width=".3"/>
    <rect x="17" y="${Y(13.75)}" width="16" height="19" fill="none" stroke="${line}" stroke-width=".25"/>
    ${arc(6, 0, Math.PI, 13.75)}
    <line x1="3" y1="${Y(-5.25)}" x2="3" y2="${Y(8.95)}" stroke="${line}" stroke-width=".25"/>
    <line x1="47" y1="${Y(-5.25)}" x2="47" y2="${Y(8.95)}" stroke="${line}" stroke-width=".25"/>
    ${arc(23.75, t3, Math.PI - t3)}
    ${arc(4, 0, Math.PI)}
    <line x1="22" y1="${Y(-1.25)}" x2="28" y2="${Y(-1.25)}" stroke="${line}" stroke-width=".4"/>
    <circle cx="25" cy="${Y(0)}" r=".75" fill="none" stroke="${line}" stroke-width=".3"/>`;
  const marks = list.filter((s) => s.x !== null && s.y <= 41).map((s) => {
    const tip = `<title>${esc(`${s.date} · Q${s.period} ${s.clock} · ${s.made ? "made" : "missed"} ${s.dist !== null ? `${s.dist}-ft ` : ""}${s.type}${s.blocked ? " · blocked by Gobert" : ""}`)}</title>`;
    if (s.blocked) return `<g>${tip}<path d="M${s.x - .7},${Y(s.y) - .7} l1.4,1.4 M${s.x - .7},${Y(s.y) + .7} l1.4,-1.4" stroke="${css("--text")}" stroke-width=".45"/></g>`;
    return s.made
      ? `<circle cx="${s.x}" cy="${Y(s.y)}" r=".75" fill="${color}" stroke="${surface}" stroke-width=".25">${tip}</circle>`
      : `<circle cx="${s.x}" cy="${Y(s.y)}" r=".65" fill="none" stroke="${color}" stroke-width=".3">${tip}</circle>`;
  }).join("");
  return `<svg viewBox="-0.5 ${Y(42) - 0.5} 51 ${47.25 + 1}" role="img" aria-label="${esc(title)}">${court}${marks}</svg>`;
}
function renderCourts() {
  const list = shots.filter(inScope);
  const panel = (on) => {
    const sel = list.filter((s) => s.gobert_on === on);
    const made = sel.filter((s) => s.made).length;
    const color = on ? css("--accent") : css("--off");
    const label = on ? "Gobert on the court" : "Gobert on the bench";
    const title = `${opp().short}'s shots with ${label.toLowerCase()}: ${made} of ${sel.length} made`;
    return `<figure class="card court-card" style="margin:0"><h3>${label}</h3>
      <p class="note" style="margin:0 0 .5rem">${made} of ${sel.length} made (${sel.length ? pct(made / sel.length) : "–"})</p>
      ${sel.length ? courtSVG(sel, color, title) : `<p class="empty">No shots in the selected games.</p>`}</figure>`;
  };
  document.getElementById("courts").innerHTML = panel(true) + panel(false);
}

// ------------------------------------------------------------------ blocks, videos, NBA tracking, game log
function renderBlocks() {
  const list = blocks.filter(inScope).sort((a, b) => b.date.localeCompare(a.date));
  document.getElementById("blocks").innerHTML = list.length ? list.map((b) => `
    <li><span class="when">${b.date}<br>${esc(b.season_type)}</span>
      <span>${esc(b.text.replace(/\s+'s/, "'s").replace(/\s{2,}/g, " "))}<br><span class="note">Quarter ${b.period}, ${esc(b.clock)} left</span></span>
      <a href="${esc(b.url)}" target="_blank" rel="noopener">Gamecast</a></li>`).join("")
    : `<li class="empty">No blocks by Gobert on ${esc(opp().short)} in the selected games.</li>`;
}

function renderVideos() {
  const list = videos.videos.filter((v) => v.opponent === state.opp);
  const el = document.getElementById("videos");
  if (!list.length) { el.innerHTML = `<p class="empty">No official clips found for this matchup yet.</p>`; return; }
  el.innerHTML = list.map((v) => {
    return `<article class="video-card">
      <div class="video-frame${v.short ? " short" : ""}" data-video="${esc(v.id)}">
        <button type="button" aria-label="Play: ${esc(v.title)}">
          <img src="${esc(v.thumbnail)}" alt="" loading="lazy"><span class="play" aria-hidden="true"></span></button></div>
      <div class="video-body"><div class="video-title">${esc(v.title)}</div>
        <div class="video-meta">${esc(v.channel)}${v.game_label ? ` · ${esc(v.game_label)}` : ""}</div>
        <div class="note">${esc(v.shows)}</div></div></article>`;
  }).join("");
  el.querySelectorAll("[data-video] button").forEach((btn) => btn.addEventListener("click", () => {
    const frame = btn.parentElement;
    frame.innerHTML = `<iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(frame.dataset.video)}?autoplay=1&rel=0"
      title="${esc(btn.getAttribute("aria-label"))}" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe>`;
  }));
}

function renderNBA() {
  const rows = (matchups.rows || []).filter((r) => r.opponent === state.opp && (state.season === "all" || r.season === state.season));
  const sec = document.getElementById("nba-section");
  sec.hidden = !S.has_nba_matchups;
  if (!S.has_nba_matchups) return;
  document.getElementById("nba-table").innerHTML = rows.length ? `<table><thead><tr><th>Season</th><th>Type</th><th class="n">Games</th><th class="n">Matchup min</th><th class="n">Partial poss.</th><th class="n">His points</th><th class="n">FG</th><th class="n">Pts per 100 poss.</th></tr></thead><tbody>${
    rows.map((r) => `<tr><td>${esc(r.season)}</td><td>${esc(r.season_type)}</td><td class="n">${num(r.gp, 0)}</td><td class="n">${num(r.matchup_min)}</td><td class="n">${num(r.partial_poss)}</td><td class="n">${num(r.player_pts, 0)}</td><td class="n">${num(r.fgm, 0)}-${num(r.fga, 0)}</td><td class="n">${num(r.pts_per_100_poss)}</td></tr>`).join("")}</tbody></table>`
    : `<p class="empty">No NBA.com tracking rows for this selection.</p>`;
}

function renderGames() {
  const list = games.filter(inScope).sort((a, b) => b.date.localeCompare(a.date));
  const o = opp();
  document.getElementById("games").innerHTML = `<table><caption class="visually-hidden">Head-to-head games</caption>
    <thead><tr><th>Date</th><th>Game</th><th>Result</th><th class="n">${esc(o.short)} MIN</th><th class="n">PTS</th><th class="n">FG</th><th class="n">3PT</th><th class="n">FT</th><th class="n">TO</th>
      <th class="n">Gobert MIN</th><th class="n">PTS</th><th class="n">REB</th><th class="n">BLK</th><th class="n">Blocks on him</th><th></th></tr></thead>
    <tbody>${list.map((g) => {
      const ob = g.opp_box, gb = g.gobert_box;
      return `<tr class="${g.season_type === "Playoffs" ? "playoff" : ""}"><td>${g.date}</td>
        <td>${esc(g.team || "")} ${g.at_vs === "@" ? "at" : "vs."} ${esc(g.opponent_team)}<br><span class="note">${esc(g.season_label)} ${esc(g.season_type)}</span></td>
        <td>${esc(g.result)} ${esc(g.score)}</td>
        <td class="n">${esc(ob.MIN)}</td><td class="n"><strong>${esc(ob.PTS)}</strong></td><td class="n">${esc(ob.FG)}</td><td class="n">${esc(ob["3PT"])}</td><td class="n">${esc(ob.FT)}</td><td class="n">${esc(ob.TO)}</td>
        <td class="n">${esc(gb.MIN)}</td><td class="n">${esc(gb.PTS)}</td><td class="n">${esc(gb.REB)}</td><td class="n">${esc(gb.BLK)}</td>
        <td class="n">${g.pbp ? g.blocks : `<span title="ESPN has no play-by-play for this game">n/a</span>`}</td>
        <td><a href="${esc(g.url)}" target="_blank" rel="noopener">ESPN</a></td></tr>`;
    }).join("")}</tbody></table>`;
}

function renderAll(withControls = true) {
  if (withControls) renderControls();
  document.querySelectorAll(".opp-name").forEach((e) => (e.textContent = opp().short));
  document.title = `Rudy Gobert vs. ${opp().name} · Defense Tracker`;
  document.getElementById("title").textContent = `Rudy Gobert vs. ${opp().name}`;
  renderTiles(); renderPairs(); renderSeasons(); renderCourts(); renderBlocks(); renderVideos(); renderNBA(); renderGames();
}

async function init() {
  [S, games, shots, blocks, videos, matchups] = await Promise.all(
    ["summary.json", "games.json", "shots.json", "blocks.json", "videos.json", "matchups.json"].map(getJSON));
  const wanted = new URLSearchParams(location.search).get("vs");
  state.opp = S.opponents.some((o) => o.slug === wanted) ? wanted : S.opponents[0].slug;
  document.getElementById("footer").innerHTML = `Data from ESPN box scores and play-by-play, built ${S.built}. Not affiliated with the NBA. · <a href="methodology.html">Methodology</a>`;
  renderAll();
  let t;
  addEventListener("resize", () => { clearTimeout(t); t = setTimeout(renderSeasons, 150); });
}

init().catch((err) => {
  console.error(err);
  document.getElementById("main").insertAdjacentHTML("afterbegin",
    `<div class="callout caution"><strong>Couldn't load the data.</strong> ${esc(err.message)}. Serve the site/ folder with a local web server (see README).</div>`);
});
