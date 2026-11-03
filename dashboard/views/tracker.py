"""Ship tracker: every ship's last known position, our radar detections, and where Sentinel-1 is now, on one map.

Positions come from Global Fishing Watch (a few days behind) and, when the collector is running, live AIS. Each ship
shows its source and age. When a ship goes quiet, the area it could have reached is worked out over water from its speed.
"""
import pandas as pd
import streamlit as st

from components import ATTRIBUTION, GFW_ATTRIBUTION, MAP_PAGE_JS
from live_ais import ais_dir, key_present, read_reports
from tracker_data import build_payload

MAP_PX = 600
REFRESH_S = 120

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.1.14/dist.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/satellite.js@5.0.0/dist/satellite.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/globe.gl@2.46.2/dist/globe.gl.min.js"></script>
<style>
  :root { --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781; --surface:#1a1a19; --line:#2f3a3a; --hud:#56c7e8; --live:#3ddc97; --amber:#e9b949; --red:#d03b3b; }
  html,body { margin:0; background:#0d0d0d; color:var(--ink); font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
  .maplibregl-ctrl-bottom-right { display:none; }
  #strip { display:flex; flex-wrap:wrap; gap:6px 18px; padding:8px 10px; border:1px solid var(--line); border-radius:8px 8px 0 0; background:#0f1414; color:var(--ink2); }
  #strip b { color:var(--hud); font-weight:600; letter-spacing:.06em; margin-right:6px; }
  #strip .on { color:var(--live); }
  #wrap { display:flex; border:1px solid var(--line); border-top:none; border-radius:0 0 8px 8px; overflow:hidden; }
  #map { position:relative; flex:1 1 auto; height:__MAP__px; background:#0d0d0d; }
  #grid { position:absolute; inset:0; pointer-events:none; z-index:1;
    background-image:linear-gradient(rgba(86,199,232,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(86,199,232,.05) 1px,transparent 1px); background-size:60px 60px; }
  .corner { position:absolute; width:18px; height:18px; border:0 solid var(--hud); opacity:.7; z-index:2; pointer-events:none; }
  #hud { position:absolute; left:12px; top:12px; background:rgba(8,12,12,.82); border:1px solid var(--line); border-radius:4px; padding:7px 10px; line-height:1.55; z-index:2; pointer-events:none; }
  #hud .k { color:var(--hud); }
  .dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin:0 4px 0 10px; vertical-align:-1px; }
  .dot:first-child { margin-left:0; }
  .ring { background:none !important; border:2px solid; width:6px; height:6px; }
  #attr { position:absolute; left:8px; bottom:6px; color:var(--ink2); font-size:11px; background:rgba(8,12,12,.7); padding:1px 6px; border-radius:3px; z-index:2; }
  #attr a { color:var(--ink2); }
  #orbit { position:absolute; right:10px; bottom:10px; width:270px; background:rgba(8,12,12,.88); border:1px solid var(--line); border-radius:4px; z-index:3; }
  #orbit h4 { margin:0; padding:6px 10px 0; color:var(--hud); font-size:12px; letter-spacing:.08em; font-weight:600; display:flex; justify-content:space-between; }
  #orbit h4 button { background:none; border:none; color:var(--muted); cursor:pointer; font:inherit; padding:0; }
  #globe { height:170px; }
  #pass { padding:2px 10px 8px; line-height:1.45; color:var(--ink2); font-size:11.5px; }
  #pass .big { color:var(--ink); font-size:14px; }
  #pass .ok { color:var(--live); }
  #side { flex:0 0 300px; height:__MAP__px; display:flex; flex-direction:column; background:#0f1414; border-left:1px solid var(--line); }
  #controls { padding:10px; display:grid; gap:7px; border-bottom:1px solid var(--line); }
  input[type=search], select { background:var(--surface); color:var(--ink); border:1px solid #383835; border-radius:4px; padding:6px 8px; font:inherit; min-width:0; }
  .row2 { display:grid; grid-template-columns:1fr 1fr; gap:7px; }
  #card { padding:10px; border-bottom:1px solid var(--line); line-height:1.5; display:none; }
  #card b.name { font-size:15px; color:var(--ink); }
  #card .src { display:inline-block; font-size:11px; padding:0 6px; border-radius:3px; margin-left:6px; border:1px solid; }
  #card .note { color:var(--muted); font-size:12px; margin-top:4px; }
  #card .reach { color:var(--amber); }
  #card input[type=range] { width:100%; accent-color:#e9b949; }
  #card button { background:var(--surface); color:var(--ink); border:1px solid #383835; border-radius:4px; padding:4px 10px; font:inherit; cursor:pointer; margin-top:4px; }
  #count { padding:6px 10px; color:var(--muted); font-size:12px; }
  #list { overflow-y:auto; flex:1 1 auto; }
  #list div { padding:5px 10px; cursor:pointer; border-bottom:1px solid #161c1c; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  #list div:hover, #list div.sel { background:#16222a; }
  #list small { color:var(--muted); }
  #note { color:var(--muted); font:13px system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.5; padding:10px 2px 0; }
  @media (max-width: 760px) {
    #wrap { flex-direction:column; }
    #map { height:460px; }
    #side { flex:none; height:auto; max-height:520px; border-left:none; border-top:1px solid var(--line); }
    #orbit { left:10px; right:10px; width:auto; }  /* the globe starts hidden on a phone so the map stays visible */
  }
</style></head><body>
<div id="strip"></div>
<div id="wrap">
  <div id="map">
    <div id="grid"></div>
    <div class="corner" style="left:4px;top:4px;border-left-width:2px;border-top-width:2px"></div>
    <div class="corner" style="right:4px;top:4px;border-right-width:2px;border-top-width:2px"></div>
    <div class="corner" style="left:4px;bottom:4px;border-left-width:2px;border-bottom-width:2px"></div>
    <div class="corner" style="right:4px;bottom:4px;border-right-width:2px;border-bottom-width:2px"></div>
    <div id="hud"></div>
    <div id="attr"><a href="https://globalfishingwatch.org" target="_blank" rel="noopener">Powered by Global Fishing Watch</a> · Contains modified Copernicus Sentinel data (2026) · Orbits: CelesTrak · © OpenStreetMap contributors · © CARTO</div>
    <div id="orbit"><h4><span>SENTINEL-1 · ORBIT</span><button id="hideGlobe" title="Hide or show the globe">–</button></h4><div id="globe"></div><div id="pass">Working out the next passes…</div></div>
  </div>
  <aside id="side">
    <div id="controls">
      <input id="find" type="search" placeholder="Search name, MMSI or IMO">
      <div class="row2">
        <select id="type"></select>
        <select id="fresh">
          <option value="all">All ships</option>
          <option value="moving">Moving at last fix</option>
          <option value="live">Live AIS only</option>
          <option value="heading">With a heading</option>
        </select>
      </div>
      <select id="radar">
        <option value="latest">Radar: latest pass</option>
        <option value="all">Radar: all passes</option>
        <option value="leads">Radar: possibly dark only</option>
        <option value="off">Radar: hide</option>
      </select>
    </div>
    <div id="card"></div>
    <div id="count"></div>
    <div id="list"></div>
  </aside>
</div>
<div id="note"></div>
<script>
__MAP_JS__
const D = __DATA__;
const $ = id => document.getElementById(id);
const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
const HOUR = 3600e3, KM_PER_KN_H = 1.852;
const LIVE_MS = 15 * 60e3;
const RGB = { live:[61,220,151], gfw:[86,170,240], stale:[120,120,115], lead:[208,59,59], ship:[233,185,73], fixed:[201,133,0], uncertain:[137,135,129], reach:[233,185,73], trail:[86,199,232] };
const hex = c => `rgb(${c.join(",")})`;
// Hull lengths by type, for drawing only. Fishing Watch doesn't give a ship's size here.
const DRAW_LENGTH_M = { CARGO:190, PASSENGER:60, BUNKER:100, OTHER_NON_FISHING:40 };
const store = {
  get(key) { try { return JSON.parse(sessionStorage.getItem("tracker." + key)); } catch (e) { return null; } },
  set(key, value) { try { sessionStorage.setItem("tracker." + key, JSON.stringify(value)); } catch (e) {} },
};
const fmtTime = ms => new Date(ms).toISOString().slice(0, 16).replace("T", " ") + " UTC";
const fmtShort = ms => { const d = new Date(ms); return `${d.getUTCDate()} ${d.toLocaleString("en-GB", { month:"short", timeZone:"UTC" })} ${d.toISOString().slice(11, 16)} UTC`; };
function fmtAge(ms) {
  const s = Math.max(0, ms / 1000);
  if (s < 90) return `${s.toFixed(0)} s`;
  if (s < 5400) return `${(s / 60).toFixed(0)} min`;
  if (s < 48 * 3600) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} days`;
}
function fmtCountdown(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), r = s % 60;
  return `${d ? d + "d " : ""}${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}
const typeLabel = t => D.type_labels[t] || "Unknown";
const topKnots = s => D.top_knots[s.type] ?? D.default_top_knots;

// ---------- ships ----------
const SHIPS = D.ships.map((s, i) => ({ ...s, i, key: s.mmsi || `i${i}`, kn: s.kn ?? 0 }));
const staleBefore = (D.feed.gfw_as_of || 0) - 24 * HOUR;
function freshness(s) {
  if (s.source === "live") return Date.now() - s.t < LIVE_MS ? "live" : "gfw";
  return s.t < staleBefore ? "stale" : "gfw";
}
const colour = s => RGB[freshness(s)];
const S = { chosen:null, visible:SHIPS, view:null, hours:store.get("hours"), field:null, globeOn:store.get("globe") ?? !matchMedia("(max-width: 760px)").matches };

// ---------- water and reach ----------
const G = D.water;
const WATER = G ? (() => { const bin = atob(G.bits), out = new Uint8Array(G.rows * G.cols); for (let i = 0; i < out.length; i++) out[i] = (bin.charCodeAt(i >> 3) >> (7 - (i & 7))) & 1; return out; })() : null;
const WATER_CELLS = WATER ? WATER.reduce((a, b) => a + b, 0) : 0;
function cellOf(lat, lon) {
  const r = Math.floor((G.north - lat) / G.res), c = Math.floor((lon - G.west) / G.res);
  return r >= 0 && r < G.rows && c >= 0 && c < G.cols ? [r, c] : null;
}
// Shortest distance over water from one cell to every other, in km, up to maxKm. Dijkstra with 16 directions, so the edge
// is within about 3% of a true circle on open water rather than the 8% an 8-direction grid gives.
const STEPS = [[-1,-1],[-1,0],[-1,1],[0,-1],[0,1],[1,-1],[1,0],[1,1],[-2,-1],[-2,1],[2,-1],[2,1],[-1,-2],[1,-2],[-1,2],[1,2]];
function waterDistances(lat, lon, maxKm) {
  const start = cellOf(lat, lon);
  if (!WATER || !start) return null;
  const { rows, cols, res } = G;
  // Fishing Watch rounds positions to about 1 km, so a ship moored at a quay can land on a land cell. Start from the nearest water.
  let from = -1;
  for (let ring = 0; ring <= 6 && from < 0; ring++)
    for (let dr = -ring; dr <= ring && from < 0; dr++)
      for (let dc = -ring; dc <= ring; dc++) {
        const r = start[0] + dr, c = start[1] + dc;
        if (r >= 0 && r < rows && c >= 0 && c < cols && WATER[r * cols + c]) { from = r * cols + c; break; }
      }
  if (from < 0) return null;
  const dy = res * 110.54;
  const dxRow = new Float32Array(rows);
  for (let r = 0; r < rows; r++) dxRow[r] = res * 111.32 * Math.cos((G.north - (r + 0.5) * res) * Math.PI / 180);
  // 64-bit, the same as the queue's keys, or rounding makes a cell look already settled and the search stops early.
  const dist = new Float64Array(rows * cols).fill(Infinity);
  const heapD = [], heapI = [];
  const push = (d, i) => { let k = heapD.length; heapD.push(d); heapI.push(i); while (k > 0) { const p = (k - 1) >> 1; if (heapD[p] <= d) break; heapD[k] = heapD[p]; heapI[k] = heapI[p]; k = p; } heapD[k] = d; heapI[k] = i; };
  const pop = () => {
    const top = heapI[0], lastD = heapD.pop(), lastI = heapI.pop(), n = heapD.length;
    if (n) { let k = 0; while (true) { let c = 2 * k + 1; if (c >= n) break; if (c + 1 < n && heapD[c + 1] < heapD[c]) c++; if (heapD[c] >= lastD) break; heapD[k] = heapD[c]; heapI[k] = heapI[c]; k = c; } heapD[k] = lastD; heapI[k] = lastI; }
    return top;
  };
  dist[from] = 0; push(0, from);
  while (heapD.length) {
    const d0 = heapD[0], i = pop();
    if (d0 > dist[i] || d0 > maxKm) continue;
    const r = (i / cols) | 0, c = i - r * cols, dx = dxRow[r];
    for (const [dr, dc] of STEPS) {
      const rr = r + dr, cc = c + dc;
      if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
      const j = rr * cols + cc;
      if (!WATER[j]) continue;
      // A knight's move passes two cells on the way, and both must be water so it can't hop a thin spit of land.
      if (Math.abs(dr) + Math.abs(dc) === 3) {
        const [ar, ac, br, bc] = Math.abs(dr) === 2 ? [r + dr / 2, c, r + dr / 2, c + dc] : [r, c + dc / 2, r + dr, c + dc / 2];
        if (!WATER[ar * cols + ac] || !WATER[br * cols + bc]) continue;
      }
      const nd = d0 + Math.hypot(dr * dy, dc * dx);
      if (nd < dist[j]) { dist[j] = nd; push(nd, j); }
    }
  }
  return dist;
}
function reachKm(s, hours) { return { inner: s.kn * KM_PER_KN_H * hours, outer: Math.max(s.kn, topKnots(s)) * KM_PER_KN_H * hours }; }
function quietHours(s) { return Math.max(0, (Date.now() - s.t) / HOUR); }
function reachImage(dist, inner, outer) {
  const canvas = document.createElement("canvas");
  canvas.width = G.cols; canvas.height = G.rows;
  const ctx = canvas.getContext("2d"), img = ctx.createImageData(G.cols, G.rows), px = img.data;
  let covered = 0, edge = false;
  for (let i = 0; i < dist.length; i++) {
    const d = dist[i];
    if (d > outer) continue;
    covered++;
    const r = (i / G.cols) | 0, c = i - r * G.cols;
    if (r === 0 || c === 0 || r === G.rows - 1 || c === G.cols - 1) edge = true;
    const o = i * 4;
    px[o] = RGB.reach[0]; px[o + 1] = RGB.reach[1]; px[o + 2] = RGB.reach[2]; px[o + 3] = d <= inner ? 120 : 45;
  }
  ctx.putImageData(img, 0, 0);
  return { url: canvas.toDataURL(), share: WATER_CELLS ? covered / WATER_CELLS : 0, edge };
}
function paintReach() {
  const f = S.field;
  if (!f || !f.dist) return;
  const r = reachKm(f.ship, Math.min(48, S.hours ?? 0));
  const image = reachImage(f.dist, r.inner, r.outer);
  f.url = image.url; f.share = image.share; f.edge = image.edge;
}
function selectShip(s, fly, keepHours) {
  S.chosen = s;
  S.field = null;
  store.set("chosen", s ? s.key : null);
  if (s) {
    const maxHours = 48;
    S.field = { ship:s, dist: waterDistances(s.lat, s.lon, Math.max(s.kn, topKnots(s)) * KM_PER_KN_H * maxHours) };
    // Each new ship starts at its own silence so far, up to 12 h. A restored view keeps the saved slider.
    if (!keepHours || S.hours === null || S.hours === undefined) S.hours = Math.min(12, quietHours(s));
    paintReach();
    if (fly && map) {
      S.view = { ...S.view, longitude:s.lon, latitude:s.lat, zoom:Math.max(S.view.zoom, 11.5), transitionDuration:1000, transitionInterpolator:new deck.FlyToInterpolator() };
    }
  }
  renderCard(); renderList(); draw();
}
function updateReachText() {
  const s = S.chosen, el = $("reachText");
  if (!s || !el) return;
  const hours = Math.min(48, S.hours ?? 0), r = reachKm(s, hours), top = Math.max(s.kn, topKnots(s));
  let text;
  if (!S.field || !S.field.dist) text = `Outside the mapped water, so drawn as plain circles: ${r.inner.toFixed(0)} km at its last speed, ${r.outer.toFixed(0)} km at ${top} knots.`;
  else text = `After ${hours.toFixed(1)} h, over water: up to ${r.inner.toFixed(0)} km at its last speed (solid), ${r.outer.toFixed(0)} km at up to ${top} knots (faint). That's ${(S.field.share * 100).toFixed(0)}% of the mapped water.${S.field.edge ? " It also reaches the edge of the mapped area, and beyond that it isn't drawn." : ""}`;
  const age = Date.now() - s.t;
  if (quietHours(s) > 48) text += ` It has been quiet ${fmtAge(age)}, past the 48 h limit, so it could be anywhere in this area or have left it.`;
  el.textContent = text;
}
function renderCard() {
  const s = S.chosen, box = $("card");
  if (!s) { box.style.display = "none"; return; }
  const fresh = freshness(s);
  const srcText = s.source === "live" ? (fresh === "live" ? "LIVE AIS" : "AIS, NOT HEARD") : "LAST KNOWN · GFW";
  const age = Date.now() - s.t;
  const hours = Math.min(48, S.hours ?? 0);
  box.innerHTML = `<b class="name">${esc(s.name || "Name not reported")}</b><span class="src" style="color:${hex(colour(s))}">${srcText}</span><br>
    ${esc(s.flag || "Flag not reported")} · ${esc(typeLabel(s.type))}<br>
    IMO ${esc(s.imo || "not reported")} · MMSI ${esc(s.mmsi || "unknown")}<br>
    Last fix ${esc(fmtTime(s.t))}, <b>${fmtAge(age)} ago</b><br>
    ${s.kn.toFixed(1)} knots${s.course !== null && s.course !== undefined ? ` · heading ${s.course.toFixed(0)}°` : " · no heading"}
    <div class="reach">Could have reached</div>
    <input id="hours" type="range" min="0" max="48" step="0.5" value="${hours}">
    <div class="note" id="reachText"></div>
    <div class="note">AIS carries no fuel data. This is speed × time over water, not a forecast of where it went.</div>
    <button id="fly">Fly to</button> <button id="unselect">Close</button>`;
  $("hours").oninput = e => { S.hours = +e.target.value; store.set("hours", S.hours); paintReach(); updateReachText(); draw(); };
  updateReachText();
  $("fly").onclick = () => selectShip(s, true);
  $("unselect").onclick = () => selectShip(null);
  box.style.display = "block";
}

// ---------- list and filters ----------
const types = [...new Set(SHIPS.map(s => s.type).filter(Boolean))].sort();
$("type").innerHTML = `<option value="">All types</option>` + types.map(t => `<option value="${esc(t)}">${esc(typeLabel(t))}</option>`).join("");
function applyFilters() {
  const q = $("find").value.trim().toLowerCase(), type = $("type").value, fresh = $("fresh").value;
  S.visible = SHIPS.filter(s => (!type || s.type === type)
    && (fresh !== "moving" || s.kn >= 1) && (fresh !== "live" || s.source === "live") && (fresh !== "heading" || s.course !== null && s.course !== undefined)
    && (!q || [s.name, s.mmsi, s.imo].some(v => v && String(v).toLowerCase().includes(q))));
  renderList(); draw();
}
function renderList() {
  // Live first, then ships under way, then by name, with unnamed ones last.
  const sorted = [...S.visible].sort((a, b) => (b.source === "live") - (a.source === "live") || (b.kn >= 1) - (a.kn >= 1) || !a.name - !b.name || String(a.name).localeCompare(String(b.name)));
  const shown = sorted.slice(0, 300);
  $("count").textContent = `${S.visible.length} of ${SHIPS.length} ships${S.visible.length > shown.length ? `, first ${shown.length} listed` : ""}`;
  $("list").innerHTML = shown.map(s => `<div data-i="${s.i}" class="${S.chosen === s ? "sel" : ""}"><span class="dot" style="background:${hex(colour(s))}"></span>${esc(s.name || "Name not reported")} <small>${esc(typeLabel(s.type))} · ${s.kn.toFixed(0)} kn · ${fmtAge(Date.now() - s.t)}</small></div>`).join("");
}
$("list").onclick = e => { const row = e.target.closest("[data-i]"); if (row) selectShip(SHIPS[+row.dataset.i], true); };
$("find").oninput = applyFilters; $("type").onchange = applyFilters; $("fresh").onchange = applyFilters;
$("radar").onchange = () => { store.set("radar", $("radar").value); draw(); };

// ---------- radar detections ----------
const latestPass = D.detections.reduce((m, d) => Math.max(m, d.t), 0);
function radarShown() {
  const mode = $("radar").value;
  if (mode === "off") return [];
  if (mode === "leads") return D.detections.filter(d => d.lead);
  return mode === "latest" ? D.detections.filter(d => d.t === latestPass) : D.detections;
}
const radarColour = d => d.lead ? RGB.lead : d.cls === "ship" ? RGB.ship : d.cls === "likely_fixed" ? RGB.fixed : RGB.uncertain;

// ---------- 3D hull, built here so no model file is needed ----------
function hullMesh() {
  const pos = [], nrm = [];
  const centre = [0, 0, 0.04];
  function tri(a, b, c) {
    const u = [b[0]-a[0], b[1]-a[1], b[2]-a[2]], v = [c[0]-a[0], c[1]-a[1], c[2]-a[2]];
    let n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]];
    const mid = [(a[0]+b[0]+c[0])/3 - centre[0], (a[1]+b[1]+c[1])/3 - centre[1], (a[2]+b[2]+c[2])/3 - centre[2]];
    // Face outward whichever way the corners were listed.
    if (n[0]*mid[0] + n[1]*mid[1] + n[2]*mid[2] < 0) { n = n.map(x => -x); [b, c] = [c, b]; }
    const len = Math.hypot(...n) || 1;
    for (const p of [a, b, c]) { pos.push(...p); nrm.push(n[0]/len, n[1]/len, n[2]/len); }
  }
  const quad = (a, b, c, d) => { tri(a, b, c); tri(a, c, d); };
  // Bow along +y. Length 1, beam 0.16, deck height 0.06.
  const w = 0.08, h = 0.06;
  const outline = [[-w, -0.5], [w, -0.5], [w, 0.28], [0, 0.5], [-w, 0.28]];
  outline.forEach((p, k) => { const q = outline[(k + 1) % outline.length]; quad([p[0], p[1], 0], [q[0], q[1], 0], [q[0], q[1], h], [p[0], p[1], h]); });
  for (let k = 1; k < outline.length - 1; k++) tri([outline[0][0], outline[0][1], h], [outline[k][0], outline[k][1], h], [outline[k+1][0], outline[k+1][1], h]);
  // Bridge block near the stern.
  const bx = 0.06, y0 = -0.44, y1 = -0.28, z0 = h, z1 = h + 0.09;
  const c = [[-bx, y0], [bx, y0], [bx, y1], [-bx, y1]];
  c.forEach((p, k) => { const q = c[(k + 1) % 4]; quad([p[0], p[1], z0], [q[0], q[1], z0], [q[0], q[1], z1], [p[0], p[1], z1]); });
  quad([-bx, y0, z1], [bx, y0, z1], [bx, y1, z1], [-bx, y1, z1]);
  return { positions:{ size:3, value:new Float32Array(pos) }, normals:{ size:3, value:new Float32Array(nrm) } };
}
const HULL = window.deck ? hullMesh() : null;
const MESH_ZOOM = 11;
const hasHeading = s => s.course !== null && s.course !== undefined;

// ---------- layers ----------
let map;
function layers() {
  const zoom = S.view ? S.view.zoom : 8.6;
  const chosen = S.chosen;
  const out = [];
  const trails = S.visible.filter(s => s.trail && s.kn >= 1).flatMap(s => s.trail.map(path => ({ ship:s, path })));
  out.push(new deck.PathLayer({ id:"trails", data:trails, getPath:t => t.path, getColor:t => [...colour(t.ship), 70], getWidth:1.2, widthUnits:"pixels", jointRounded:true }));
  if (chosen && chosen.trail) out.push(new deck.PathLayer({ id:"trail-chosen", data:chosen.trail, getPath:path => path, getColor:RGB.trail, getWidth:2.5, widthUnits:"pixels", jointRounded:true }));
  if (chosen && S.field) {
    const hours = Math.min(48, S.hours ?? 0), r = reachKm(chosen, hours);
    if (S.field.dist && S.field.url) {
      const south = G.north - G.rows * G.res, east = G.west + G.cols * G.res;
      out.push(new deck.BitmapLayer({ id:"reach", image:S.field.url, bounds:[G.west, south, east, G.north], _imageCoordinateSystem:deck.COORDINATE_SYSTEM.LNGLAT }));
    } else {
      out.push(new deck.ScatterplotLayer({ id:"reach-circles", data:[r.outer, r.inner], getPosition:() => [chosen.lon, chosen.lat], getRadius:km => km * 1000, radiusUnits:"meters",
        stroked:true, filled:true, getFillColor:[...RGB.reach, 25], getLineColor:[...RGB.reach, 200], lineWidthUnits:"pixels", getLineWidth:1.5 }));
    }
  }
  const radar = radarShown();
  out.push(new deck.ScatterplotLayer({ id:"radar", data:radar, getPosition:d => [d.lon, d.lat], getRadius:d => d.lead ? 6 : 5, radiusUnits:"pixels",
    filled:true, getFillColor:d => d.lead ? [...RGB.lead, 200] : [0, 0, 0, 0], stroked:true, getLineColor:radarColour, lineWidthUnits:"pixels", getLineWidth:1.6, pickable:true }));
  const meshMode = zoom >= MESH_ZOOM;
  const dots = meshMode ? S.visible.filter(s => !hasHeading(s)) : S.visible;
  out.push(new deck.ScatterplotLayer({ id:"ships", data:dots, getPosition:s => [s.lon, s.lat], getRadius:s => s.kn >= 1 ? 4.5 : 3, radiusUnits:"pixels",
    getFillColor:colour, stroked:true, lineWidthUnits:"pixels", getLineWidth:s => s === chosen ? 2 : 0, getLineColor:[240, 239, 236], pickable:true,
    updateTriggers:{ getLineWidth:chosen && chosen.key } }));
  if (meshMode) {
    // Ships are drawn larger than life below zoom 14 so they stay visible.
    out.push(new deck.SimpleMeshLayer({ id:"hulls", data:S.visible.filter(hasHeading), mesh:HULL, getPosition:s => [s.lon, s.lat, 0],
      getOrientation:s => [0, -s.course, 0], getScale:s => { const L = DRAW_LENGTH_M[s.type] || 40; return [L, L, L]; },
      sizeScale:Math.max(1, 2 ** (14 - zoom)), getColor:s => s === chosen ? [240, 239, 236] : colour(s), pickable:true,
      material:{ ambient:0.45, diffuse:0.6, shininess:24, specularColor:[90, 90, 90] }, updateTriggers:{ getColor:chosen && chosen.key } }));
  }
  if (zoom >= 12.5) out.push(new deck.TextLayer({ id:"names", data:S.visible.filter(s => s.name), getPosition:s => [s.lon, s.lat], getText:s => s.name, getSize:11,
    getColor:[195, 194, 183], getPixelOffset:[0, -14], fontFamily:"ui-monospace, Menlo, monospace", characterSet:"auto" }));
  if (PORT_LABELS) out.push(PORT_LABELS);
  return out;
}
function draw() { if (map) map.setProps({ layers:layers(), viewState:S.view }); }
function tooltip({ object, layer }) {
  if (!object || !layer) return null;
  const style = { background:"#0f1414", color:"#f0efec", fontSize:"12px", fontFamily:"ui-monospace, Menlo, monospace", border:"1px solid #2f3a3a" };
  if (layer.id === "radar") return { html:`<b>Radar detection</b> · ${esc(object.label || object.cls)}<br>Sentinel-1 pass ${esc(fmtShort(object.t))}<br>AIS: ${esc(object.ais || "not checked")}${object.lead ? "<br><b style='color:#e66767'>Possibly dark: a lead, not a verdict</b>" : ""}`, style };
  return { html:`<b>${esc(object.name || "Name not reported")}</b><br>${esc(typeLabel(object.type))} · ${object.kn.toFixed(1)} kn<br>${object.source === "live" ? "Live AIS" : "Last known (GFW)"}, ${fmtAge(Date.now() - object.t)} ago`, style };
}

// ---------- HUD and data strip ----------
function hud() {
  const now = Date.now();
  const live = SHIPS.filter(s => freshness(s) === "live").length;
  $("hud").innerHTML = `<span class="k">UTC</span> ${new Date(now).toISOString().slice(11, 19)} · ${new Date(now).toISOString().slice(0, 10)}<br>
    <span class="k">SHIPS</span> ${S.visible.length} shown · ${live} live<br>
    <span class="dot" style="background:${hex(RGB.live)}"></span>live AIS <span class="dot" style="background:${hex(RGB.gfw)}"></span>last known <span class="dot" style="background:${hex(RGB.stale)}"></span>older<br>
    <span class="dot ring" style="border-color:${hex(RGB.ship)}"></span>radar: ship <span class="dot ring" style="border-color:${hex(RGB.uncertain)}"></span>uncertain <span class="dot" style="background:${hex(RGB.lead)}"></span>possibly dark`;
}
function strip() {
  const f = D.feed, now = Date.now();
  const liveF = f.live;
  const liveText = liveF.ships ? `<span class="on">${liveF.ships} ships heard in the last hour</span>, newest ${fmtAge(liveF.newest_age_s * 1000)} ago` : liveF.key ? "key saved, no reports in the last hour" : "off (no aisstream key)";
  const next = ORBIT.next ? `${ORBIT.next.sat} in ${fmtCountdown(ORBIT.next.t - now)}` : D.expected.length ? `expected in ${fmtCountdown(D.expected[0] - now)}` : "unknown";
  $("strip").innerHTML = `<span><b>SENTINEL-1</b>${f.passes} passes processed · latest ${esc(fmtShort(latestPass))} · ${f.detections} radar detections</span>
    <span><b>AIS</b>${SHIPS.filter(s => s.source === "gfw").length} ships from Global Fishing Watch, as of ${f.gfw_as_of ? esc(fmtShort(f.gfw_as_of)) + ` (${fmtAge(now - f.gfw_as_of)} old)` : "not built"}</span>
    <span><b>LIVE AIS</b>${liveText}</span>
    <span><b>NEXT PASS</b>${next}</span>`;
}

// ---------- Sentinel-1 orbit ----------
const ORBIT = { sats:[], passes:[], next:null, check:null, globe:null };
const R_EARTH = 6371;
function subpoint(rec, date) {
  const pv = satellite.propagate(rec, date);
  if (!pv || !pv.position) return null;
  const geo = satellite.eciToGeodetic(pv.position, satellite.gstime(date));
  return { lat:satellite.degreesLat(geo.latitude), lon:satellite.degreesLong(geo.longitude), alt:geo.height };
}
const unit = (lat, lon) => { const a = lat * Math.PI / 180, b = lon * Math.PI / 180; return [Math.cos(a) * Math.cos(b), Math.cos(a) * Math.sin(b), Math.sin(a)]; };
const AREA_U = unit(D.area.lat, D.area.lon);
function groundKm(p) { const u = unit(p.lat, p.lon); return R_EARTH * Math.acos(Math.min(1, u[0]*AREA_U[0] + u[1]*AREA_U[1] + u[2]*AREA_U[2])); }
// Closest approaches to our area. A pass can image it when the area sits inside the swath to the right of the track (Sentinel-1 looks right).
function findPasses(sat, from, to) {
  const found = [], step = 30e3;
  let a = null, b = null;
  for (let t = from; t <= to; t += step) {
    const p = subpoint(sat.rec, new Date(t));
    if (!p) continue;
    const c = { t, d:groundKm(p) };
    if (a && b && b.d < a.d && b.d <= c.d && b.d < 1200) {
      // Narrow the minimum to about a second.
      let lo = b.t - step, hi = b.t + step;
      for (let k = 0; k < 24; k++) { const m1 = lo + (hi - lo) / 3, m2 = hi - (hi - lo) / 3; if (groundKm(subpoint(sat.rec, new Date(m1))) < groundKm(subpoint(sat.rec, new Date(m2)))) hi = m2; else lo = m1; }
      const tm = (lo + hi) / 2, p0 = subpoint(sat.rec, new Date(tm)), p1 = subpoint(sat.rec, new Date(tm + 1000));
      const u0 = unit(p0.lat, p0.lon), u1 = unit(p1.lat, p1.lon);
      const n = [u0[1]*u1[2]-u0[2]*u1[1], u0[2]*u1[0]-u0[0]*u1[2], u0[0]*u1[1]-u0[1]*u1[0]];
      const right = -(n[0]*AREA_U[0] + n[1]*AREA_U[1] + n[2]*AREA_U[2]) > 0;
      const d = groundKm(p0);
      found.push({ sat:sat.id, t:tm, km:d, right, asc:p1.lat > p0.lat, imaging:right && d >= D.swath_km[0] && d <= D.swath_km[1] });
    }
    a = b; b = c;
  }
  return found;
}
function setupOrbit() {
  const now = Date.now();
  const fresh = D.tles.filter(t => now - t.epoch < 14 * 86400e3);
  if (!window.satellite || !fresh.length) {
    ORBIT.sats = [];
    $("globe").style.display = "none";
    passText();
    return;
  }
  ORBIT.sats = fresh.map(t => ({ ...t, rec:satellite.twoline2satrec(t.line1, t.line2) }));
  const first = D.acquisitions.length ? Math.min(...D.acquisitions.map(a => a.t)) - 86400e3 : now - 86400e3;
  ORBIT.passes = ORBIT.sats.flatMap(s => findPasses(s, first, now + 13 * 86400e3)).sort((x, y) => x.t - y.t);
  ORBIT.next = ORBIT.passes.find(p => p.imaging && p.t > now) || null;
  // Check the orbit maths against the passes we really have: each real scene should sit on a predicted imaging pass.
  const offsets = D.acquisitions.map(a => { const m = ORBIT.passes.filter(p => p.imaging).map(p => Math.abs(p.t - a.t)); return m.length ? Math.min(...m) : Infinity; });
  ORBIT.check = { matched:offsets.filter(o => o < 10 * 60e3).length, total:offsets.length, worst:Math.max(0, ...offsets.filter(o => o < 10 * 60e3)) };
  window.__orbit = ORBIT;
  if (window.Globe && S.globeOn) startGlobe();
  else { $("globe").style.display = "none"; $("hideGlobe").textContent = "+"; }
  passText();
}
function orbitPath(sat, from, minutes, altitude) {
  const pts = [];
  for (let m = 0; m <= minutes; m += 1) { const p = subpoint(sat.rec, new Date(from + m * 60e3)); if (p) pts.push([p.lat, p.lon, altitude === null ? p.alt / R_EARTH : altitude]); }
  return pts;
}
function startGlobe() {
  const el = $("globe");
  el.style.display = "block";
  const area = D.area, h = 0.25;
  const areaBox = [[area.lat - h, area.lon - h, 0.004], [area.lat - h, area.lon + h, 0.004], [area.lat + h, area.lon + h, 0.004], [area.lat + h, area.lon - h, 0.004], [area.lat - h, area.lon - h, 0.004]];
  const globe = new Globe(el, { animateIn:false })
    .width(el.clientWidth || 270).height(170).backgroundColor("rgba(0,0,0,0)")
    .globeImageUrl("https://cdn.jsdelivr.net/npm/three-globe@2.41.12/example/img/earth-night.jpg")
    .showAtmosphere(true).atmosphereColor("#56c7e8").atmosphereAltitude(0.12)
    .pathPoints("pts").pathPointLat(p => p[0]).pathPointLng(p => p[1]).pathPointAlt(p => p[2]).pathColor("color").pathStroke("width").pathTransitionDuration(0)
    .htmlLat("lat").htmlLng("lng").htmlAltitude("alt").htmlTransitionDuration(0)
    .htmlElement(d => { const e = document.createElement("div"); e.style.cssText = "color:#56c7e8;font:11px ui-monospace,Menlo,monospace;white-space:nowrap;transform:translate(-4px,-6px);pointer-events:none"; e.textContent = "◆ " + d.id; return e; });
  globe.pointOfView({ lat:22, lng:52, altitude:2.4 }, 0);
  globe.controls().enableZoom = true;
  ORBIT.globe = globe;
  ORBIT.areaBox = areaBox;
  updateGlobe(true);
}
function updateGlobe(paths) {
  const g = ORBIT.globe;
  if (!g) return;
  const now = Date.now();
  if (paths) {
    const data = [{ pts:ORBIT.areaBox, color:"#d03b3b", width:1.2 }];
    for (const s of ORBIT.sats) {
      data.push({ pts:orbitPath(s, now, 100, null), color:"rgba(86,199,232,0.9)", width:0.6 });
      data.push({ pts:orbitPath(s, now, 100, 0.002), color:"rgba(86,199,232,0.3)", width:0.3 });
    }
    g.pathsData(data);
  }
  g.htmlElementsData(ORBIT.sats.map(s => { const p = subpoint(s.rec, new Date(now)); return p ? { id:s.id, lat:p.lat, lng:p.lon, alt:p.alt / R_EARTH } : null; }).filter(Boolean));
}
function passText() {
  const now = Date.now();
  const rows = [];
  if (ORBIT.sats.length) {
    if (ORBIT.next) {
      const n = ORBIT.next;
      rows.push(`<span class="big">${esc(n.sat)} over our area in ${fmtCountdown(n.t - now)}</span>`);
      rows.push(`${esc(fmtShort(n.t))} · ${n.asc ? "ascending" : "descending"} · new scene about 3–24 h later (assumed)`);
    }
    const where = ORBIT.sats.map(s => { const p = subpoint(s.rec, new Date(now)); return p ? `${esc(s.id)} ${Math.abs(p.lat).toFixed(0)}°${p.lat >= 0 ? "N" : "S"} ${Math.abs(p.lon).toFixed(0)}°${p.lon >= 0 ? "E" : "W"}` : ""; }).filter(Boolean);
    rows.push(`Now: ${where.join(" · ")}, ${ORBIT.sats.length > 1 ? "both" : ""} about 700 km up`);
    if (ORBIT.check && ORBIT.check.total) {
      const c = ORBIT.check;
      rows.push(c.matched === c.total ? `<span class="ok">✓ All ${c.total} of our real scenes fall on predicted passes (±${Math.ceil(c.worst / 1000)} s)</span>` : `Only ${c.matched} of ${c.total} real scenes fall on predicted passes, so treat these times as rough`);
    }
    rows.push(`Orbits: CelesTrak, ${fmtAge(now - Math.min(...ORBIT.sats.map(s => s.epoch)))} old`);
  } else {
    rows.push(D.tles.length ? "Saved orbits are over 14 days old, so the live position is hidden. Run dashboard/pipeline/fetch_tle.py." : "No orbits saved. Run dashboard/pipeline/fetch_tle.py.");
    if (D.expected.length) rows.push(`<span class="big">Next expected scene in ${fmtCountdown(D.expected[0] - now)}</span><br>${esc(fmtShort(D.expected[0]))}, from the 12-day repeat of our real scenes`);
  }
  $("pass").innerHTML = rows.join("<br>");
}
$("hideGlobe").onclick = () => {
  S.globeOn = !S.globeOn; store.set("globe", S.globeOn);
  $("hideGlobe").textContent = S.globeOn ? "–" : "+";
  if (S.globeOn && !ORBIT.globe && window.Globe && ORBIT.sats.length) startGlobe();
  $("globe").style.display = S.globeOn && ORBIT.globe ? "block" : "none";
};

// ---------- start ----------
$("note").innerHTML = `Positions are real AIS. The blue ones are each ship's last fix from Global Fishing Watch, which runs a few days behind, so they show where ships were, not where they are now.
  Green ones come from the live AIS collector when it's running, and only count as live within 15 minutes of a report. Coastal receivers miss ships further out, so a missing ship isn't proof of anything.
  Hulls appear when you zoom in, drawn only for ships whose last two fixes give a heading, at a size by type rather than measured.
  Click a ship for the area it could have reached over water since its last fix.
  Radar rings are our own Sentinel-1 detections, and red ones are possibly dark: a ship-class target with no AIS match, a reason to look closer rather than proof.
  The next-pass countdown comes from the satellites' published orbits and is checked against our real scenes, but ESA decides which passes are imaged.`;
if (!window.deck || !window.maplibregl) {
  $("map").innerHTML = '<div style="padding:20px;color:#c3c2b7">The tracker map needs an internet connection to load.</div>';
} else {
  const saved = store.get("view");
  S.view = saved && typeof saved.zoom === "number" ? saved : { longitude:54.88, latitude:24.92, zoom:8.7, pitch:45, bearing:-10, maxPitch:70 };
  const savedRadar = store.get("radar");
  if (savedRadar) $("radar").value = savedRadar;
  map = new deck.DeckGL({ container:"map", viewState:S.view, controller:true, layers:[],
    mapStyle:"https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json", map:maplibregl,
    onViewStateChange:({ viewState }) => { S.view = viewState; store.set("view", { longitude:viewState.longitude, latitude:viewState.latitude, zoom:viewState.zoom, pitch:viewState.pitch, bearing:viewState.bearing, maxPitch:70 }); draw(); },
    onClick:info => { if (info.object && info.layer && info.layer.id !== "radar") selectShip(info.object, false); else if (!info.object) selectShip(null); },
    getTooltip:tooltip });
  // The map's own canvas sits under the HUD and grid.
  for (const id of ["grid", "hud", "attr", "orbit"]) $("map").appendChild($(id));
  for (const el of [...document.querySelectorAll(".corner")]) $("map").appendChild(el);
  applyFilters();
  const chosenKey = store.get("chosen");
  const again = chosenKey && SHIPS.find(s => s.key === chosenKey);
  if (again) selectShip(again, false, true);
}
hud(); strip();
// Orbit maths after the first paint, so the map shows straight away.
setTimeout(() => { setupOrbit(); strip(); }, 50);
let ticks = 0;
setInterval(() => {
  ticks++;
  hud(); strip(); passText();
  updateGlobe(ticks % 60 === 0);
  if (ticks % 30 === 0) { renderList(); if (S.chosen) renderCard(); }
}, 1000);
</script></body></html>"""


@st.cache_data(show_spinner=False, max_entries=4)
def build_page(payload: str) -> str:
    page = PAGE.replace("__MAP_JS__", MAP_PAGE_JS).replace("__MAP__", str(MAP_PX))
    return page.replace("__DATA__", payload)


def show(frame: pd.DataFrame) -> None:
    st.iframe(build_page(build_payload(frame, pd.Timestamp.now(tz="UTC"))))


@st.fragment(run_every=REFRESH_S)
def live_tracker(frame: pd.DataFrame) -> None:
    show(frame)


def render(frame: pd.DataFrame) -> None:
    st.subheader("Ship tracker")
    st.markdown(
        "Every ship we have AIS for, at its **last known position**, with our own Sentinel-1 radar detections and where the satellites are now. "
        "Search or click a ship to see who it is and where it could have got to since."
    )
    now = pd.Timestamp.now(tz="UTC").timestamp()
    # Only worth redrawing while the live collector could be adding ships.
    if key_present() or not read_reports(ais_dir(), now).empty:
        live_tracker(frame)
    else:
        show(frame)
    st.caption(f"{ATTRIBUTION} Ship positions: AIS via Global Fishing Watch and aisstream.io. Orbits: CelesTrak.")
    st.markdown(GFW_ATTRIBUTION)
