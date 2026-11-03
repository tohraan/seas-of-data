"""Ship movement: replay real hourly AIS positions, a few days behind, above whatever the live feed is hearing now."""
import json
from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from components import (
    FLAG_COLUMN_PX,
    GFW_ATTRIBUTION,
    MAP_HEIGHT_PX,
    MAP_PAGE_JS,
    reported,
    ship_type_label,
)
from data import ship_movement_text
from views import live

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.1.14/dist.min.js"></script>
<style>
  :root { --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781; --surface:#1a1a19; --line:#383835; --blue:#3987e5; --amber:#c98500; }
  html,body { margin:0; background:#0d0d0d; color:var(--ink); font:14px system-ui,-apple-system,"Segoe UI",sans-serif; }
  /* The same credits are in #attr, which matches the page. */
  .maplibregl-ctrl-bottom-right { display:none; }
  #map { position:relative; height:__MAP__px; border-radius:8px; overflow:hidden; background:#0d0d0d; }
  #hud { position:absolute; left:12px; top:12px; background:rgba(13,13,13,.8); border-radius:6px; padding:8px 12px; pointer-events:none; line-height:1.5; z-index:2; }
  #who { position:absolute; right:12px; top:12px; width:290px; background:rgba(13,13,13,.88); border-radius:6px; padding:10px 12px; line-height:1.45; z-index:2; display:none; }
  #who b { font-size:15px; }
  #who .quiet { color:#e9b949; margin-top:6px; }
  #attr { position:absolute; left:8px; bottom:6px; color:#c3c2b7; font-size:11px; background:rgba(13,13,13,.6); padding:1px 6px; border-radius:4px; z-index:2; }
  #attr a { color:#c3c2b7; }
  #bar { display:flex; flex-wrap:wrap; gap:10px 14px; align-items:center; padding:12px 2px 6px; }
  button { background:var(--surface); color:var(--ink); border:1px solid var(--line); border-radius:6px; padding:7px 13px; font:inherit; cursor:pointer; }
  button:hover { border-color:var(--muted); }
  button.on { background:#22344a; border-color:var(--blue); }
  input[type=range] { accent-color:var(--blue); }
  #time { flex:1 1 280px; min-width:200px; }
  input[type=search] { background:var(--surface); color:var(--ink); border:1px solid var(--line); border-radius:6px; padding:7px 10px; font:inherit; width:190px; }
  select { background:var(--surface); color:var(--ink); border:1px solid var(--line); border-radius:6px; padding:7px 10px; font:inherit; max-width:340px; }
  #ringbar { display:flex; flex-wrap:wrap; gap:8px 10px; align-items:center; padding:2px 2px 8px; }
  #ringbar label { color:var(--ink2); }
  #chips { display:contents; }
  .chip { display:inline-flex; align-items:center; background:#2b2210; border:1px solid var(--amber); border-radius:16px; }
  .chip button { background:none; border:none; padding:4px 4px 4px 11px; }
  .chip button.x { padding:4px 11px 4px 6px; color:var(--ink2); }
  .chip small { color:#e9b949; margin-left:6px; }
  .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin:0 5px 0 12px; }
  #note { color:var(--muted); font-size:13px; line-height:1.45; }
</style></head><body>
<div id="map"><div id="hud"></div><div id="who"></div><div id="attr"><a href="https://globalfishingwatch.org" target="_blank" rel="noopener">Powered by Global Fishing Watch</a> · © OpenStreetMap contributors · © CARTO</div></div>
<div id="bar">
  <button id="play">▶ Play</button>
  <input id="time" type="range" min="0" step="0.05">
  <button id="speed">1 h per second</button>
  <button id="moving">Moving only</button>
  <input id="find" type="search" list="names" placeholder="Find a ship">
  <datalist id="names"></datalist>
</div>
<div id="ringbar">
  <label for="ringpick">Reach ring</label>
  <select id="ringpick"></select>
  <span id="chips"></span>
  <button id="clear" hidden>Clear all</button>
</div>
<div id="note">Real AIS positions, one per hour per ship, rounded to about 1 km. Between hours a ship follows a straight line or, where that would cross land, the shortest way over water. Neither is its exact path.
  An amber outline means the ship stopped appearing, and it may just be out of receiver range. To see how far it could have gone at its last reported speed, click it, or pick ships under Reach ring to keep several on the map. The blue lines are the Dubai Canal and Creek, so boats on them really are inside the city.
  <span class="dot" style="background:#3987e5"></span>Cargo <span class="dot" style="background:#d95926"></span>Passenger <span class="dot" style="background:#199e70"></span>Other</div>
<script>
__MAP_JS__
const D = __DATA__;
const $ = id => document.getElementById(id);
const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
const COLORS = { CARGO:[57,135,229], PASSENGER:[217,89,38] };
const OTHER = [25,158,112];
const MAX_LINE_HOURS = D.max_line_hours;
const reachKm = a => a.kn * 1.852 * a.quietHours;
const isQuiet = a => a.quietHours >= 1 && a.kn >= 1;
const SHIPS = D.ships.map((s, i) => ({ ...s, i, t:[], x:[], y:[], k:[], jump:[], color:COLORS[s.type] || OTHER }));
for (const [s, h, lat, lon, kn, jump] of D.fixes) { const ship = SHIPS[s]; ship.t.push(h); ship.x.push(lon); ship.y.push(lat); ship.k.push(kn); ship.jump.push(jump === 1); }
const LAST = D.hours.length - 1;
// One trail per unbroken run of positions, so no line is drawn across a silence or a jump.
function runs(ship) {
  const out = [];
  let path = [], times = [];
  ship.t.forEach((hour, i) => {
    path.push([ship.x[i], ship.y[i]]); times.push(hour);
    const next = ship.t[i+1];
    if (next === undefined || next - hour > MAX_LINE_HOURS || ship.jump[i]) {
      if (path.length > 1) out.push({ path, times, color:ship.color });
      path = []; times = [];
    }
  });
  return out;
}
const TRIPS = SHIPS.filter(s => s.t.length > 1 && Math.max(...s.k) >= 1).flatMap(runs);
// A ring only means something for a ship that went quiet while moving. Each is listed once, by its longest silence.
const RING_SHIPS = SHIPS.flatMap(ship => {
  let longest = null;
  ship.t.forEach((hour, i) => {
    const next = ship.t[i+1];
    if (next !== undefined && next - hour > MAX_LINE_HOURS && ship.k[i] >= 1 && (!longest || next - hour > longest.hours)) longest = { ship, from:hour, hours:next - hour };
  });
  return longest ? [longest] : [];
}).sort((a, b) => b.hours - a.hours);
const S = { T:0, playing:false, rate:1, movingOnly:false, chosen:null, rings:new Map(), last:0 };
function locate(ship, T) {
  const t = ship.t;
  if (T < t[0] - 0.5 || T > t[t.length-1] + 1) return null;
  let lo = 0, hi = t.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (t[mid] <= T) lo = mid; else hi = mid - 1; }
  const next = lo + 1 < t.length ? lo + 1 : null;
  const gap = next === null ? 0 : t[next] - t[lo];
  if (next !== null && gap <= MAX_LINE_HOURS && !ship.jump[lo]) {
    const f = Math.max(0, (T - t[lo]) / gap);
    return { x:ship.x[lo] + f*(ship.x[next]-ship.x[lo]), y:ship.y[lo] + f*(ship.y[next]-ship.y[lo]), kn:ship.k[lo], quietHours:0, ship };
  }
  // A long gap inside the data: hold the last known position and let the ring grow until the ship reappears.
  const quiet = next !== null && gap > MAX_LINE_HOURS;
  return { x:ship.x[lo], y:ship.y[lo], kn:ship.k[lo], quietHours:quiet ? Math.max(0, T - t[lo]) : 0, ship, reappear:quiet ? { hours:gap, x:ship.x[next], y:ship.y[next], at:D.hours[t[next]] } : null };
}
function km(a, b, c, d) { return Math.hypot((c-a)*111.32*Math.cos(b*Math.PI/180), (d-b)*110.54); }
function who() {
  const box = $("who");
  const ship = S.chosen === null ? null : SHIPS[S.chosen];
  if (!ship) { box.style.display = "none"; return; }
  const at = locate(ship, S.T);
  const bits = [esc(ship.flag || "Flag not reported"), esc((ship.type || "Unknown type").replace(/_/g," ").toLowerCase())];
  let html = `<b>${esc(ship.name || "Name not reported")}</b><br>${bits.join(" · ")}<br>IMO ${esc(ship.imo || "not reported")} · MMSI ${esc(ship.mmsi || "unknown")}`;
  if (!at) html += `<br>Not in the area at this time.`;
  else {
    html += `<br>${at.kn.toFixed(1)} knots`;
    if (at.quietHours >= 1 && at.reappear) {
      const reach = reachKm(at);
      const moved = km(at.x, at.y, at.reappear.x, at.reappear.y);
      html += `<div class="quiet">Not heard for ${at.quietHours.toFixed(0)} h. At its last speed it could be up to ${reach.toFixed(0)} km away (estimate). It reappears after ${at.reappear.hours} h, ${moved.toFixed(0)} km from here.</div>`;
    }
  }
  box.innerHTML = html;
  box.style.display = "block";
}
function updateChips() {
  for (const chip of document.querySelectorAll(".chip")) {
    const at = locate(SHIPS[+chip.dataset.ship], S.T);
    chip.querySelector("small").textContent = at && isQuiet(at) ? `up to ${reachKm(at).toFixed(0)} km` : "not quiet now";
  }
}
function renderChips() {
  $("chips").innerHTML = [...S.rings.values()].map(({ ship }) => `<span class="chip" data-ship="${ship.i}"><button class="go" title="Go to when this ship went quiet">${esc(ship.name || "Name not reported")}<small></small></button><button class="x" title="Remove this ring">×</button></span>`).join("");
  $("clear").hidden = S.rings.size < 2;
  updateChips();
}
function showRing(entry) {
  setPlaying(false);
  // An hour into the silence, when the ring starts to show.
  S.T = Math.min(LAST, entry.from + 1);
  $("time").value = S.T;
  S.chosen = entry.ship.i;
  draw();
}
function layers() {
  const now = [];
  for (const ship of SHIPS) {
    const at = locate(ship, S.T);
    if (at && (!S.movingOnly || at.kn >= 1)) now.push(at);
  }
  const chosen = S.chosen === null ? null : SHIPS[S.chosen];
  const quiet = now.filter(isQuiet);
  const rings = quiet.filter(a => S.rings.has(a.ship.i) || a.ship === chosen);
  const moving = now.filter(a => a.kn >= 1).length;
  const hour = D.hours[Math.min(LAST, Math.floor(S.T))];
  $("hud").innerHTML = `<b>${esc(hour)} UTC</b><br>${now.length} ships shown, ${moving} moving, ${quiet.length} quiet<br>This replay is ${esc(D.age_label)}`;
  who();
  updateChips();
  return [
    WATERWAYS,
    new deck.TripsLayer({ id:"trails", data:TRIPS, getPath:d=>d.path, getTimestamps:d=>d.times, getColor:d=>d.color, currentTime:S.T, trailLength:6, fadeTrail:true, widthMinPixels:2, opacity:0.75, jointRounded:true, capRounded:true }),
    new deck.ScatterplotLayer({ id:"quiet", data:rings, getPosition:a=>[a.x,a.y], getRadius:a=>reachKm(a)*1000, radiusUnits:"meters", filled:false, stroked:true, getLineColor:[201,133,0,190], lineWidthUnits:"pixels", getLineWidth:1.5, updateTriggers:{getRadius:S.T} }),
    new deck.ScatterplotLayer({ id:"ships", data:now, getPosition:a=>[a.x,a.y], getRadius:a=>a.kn>=1?5:3, radiusUnits:"pixels", getFillColor:a=>a.kn>=1?a.ship.color:[...a.ship.color,150], stroked:true, lineWidthUnits:"pixels",
      getLineWidth:a=>a.ship===chosen?2:isQuiet(a)?1.5:0, getLineColor:a=>a.ship===chosen?[240,239,236]:[201,133,0], pickable:true, updateTriggers:{getPosition:S.T, getLineWidth:[S.chosen,S.T], getLineColor:S.chosen} }),
    WATERWAY_NAMES,
    PORT_LABELS,
  ];
}
const WATERWAYS = window.deck ? new deck.PathLayer({ id:"waterways", data:D.waterways, getPath:d=>d.path, getColor:[96,150,210,200], getWidth:2, widthUnits:"pixels", jointRounded:true, capRounded:true }) : null;
const WATERWAY_NAMES = window.deck ? new deck.TextLayer({ id:"waterway-names", data:D.waterways, getPosition:d=>d.path[Math.floor(d.path.length/4)], getText:d=>d.name, getSize:11, getColor:[150,190,235], fontFamily:"system-ui, sans-serif", getPixelOffset:[0,11] }) : null;
let map;
function draw() { if (map) map.setProps({ layers:layers() }); }
function tick(time) {
  if (S.playing) {
    // Keeps time on a slow machine, without a big jump after the tab has been hidden.
    const dt = Math.min(0.5, (time - S.last) / 1000);
    S.T += dt * S.rate;
    if (S.T > LAST) S.T = 0;
    $("time").value = S.T;
    draw();
  }
  S.last = time;
  requestAnimationFrame(tick);
}
function setPlaying(on) { S.playing = on; $("play").textContent = on ? "❚❚ Pause" : "▶ Play"; }
if (!window.deck || !window.maplibregl) {
  $("map").innerHTML = '<div style="padding:20px;color:#c3c2b7">The replay map needs an internet connection to load.</div>';
} else {
  S.T = Math.max(0, LAST - 12);
  $("time").max = LAST; $("time").value = S.T;
  const names = [...new Set(SHIPS.map(s => s.name).filter(Boolean))].sort();
  $("names").innerHTML = names.map(n => `<option value="${esc(n)}">`).join("");
  $("play").onclick = () => setPlaying(!S.playing);
  $("time").oninput = e => { S.T = +e.target.value; draw(); };
  const rates = [1, 3, 8];
  $("speed").onclick = e => { S.rate = rates[(rates.indexOf(S.rate)+1)%rates.length]; e.target.textContent = `${S.rate} h per second`; };
  $("moving").onclick = e => { S.movingOnly = !S.movingOnly; e.target.classList.toggle("on", S.movingOnly); draw(); };
  $("find").onchange = e => { const i = SHIPS.findIndex(s => s.name === e.target.value); S.chosen = i < 0 ? null : i; draw(); };
  $("ringpick").innerHTML = `<option value="">Pick a ship that went quiet (${RING_SHIPS.length})</option>` + RING_SHIPS.map((entry, i) => `<option value="${i}">${esc(entry.ship.name || "Name not reported")}, ${entry.hours} h quiet</option>`).join("");
  $("ringpick").onchange = e => {
    if (e.target.value === "") return;
    const entry = RING_SHIPS[+e.target.value];
    e.target.value = "";
    S.rings.set(entry.ship.i, entry);
    renderChips();
    showRing(entry);
  };
  $("chips").onclick = e => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const i = +chip.dataset.ship;
    if (e.target.closest(".x")) {
      S.rings.delete(i);
      if (S.chosen === i) S.chosen = null;
      renderChips();
      draw();
    } else showRing(S.rings.get(i));
  };
  $("clear").onclick = () => { S.rings.clear(); S.chosen = null; renderChips(); draw(); };
  map = new deck.DeckGL({ container:"map", initialViewState:{ longitude:54.88, latitude:24.92, zoom:8.6, pitch:0, bearing:0 }, controller:true, layers:[],
    mapStyle:"https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json", map:maplibregl,
    onClick: info => { S.chosen = info.object ? info.object.ship.i : null; draw(); },
    getTooltip: ({object}) => object && { html:`<b>${esc(object.ship.name || "Name not reported")}</b><br>${object.kn.toFixed(1)} knots`, style:{ background:"#1a1a19", color:"#f0efec", fontSize:"13px" } } });
  draw();
  requestAnimationFrame(tick);
}
</script></body></html>"""


def days_old(newest_hour: str, now: datetime) -> float:
    return (now - datetime.strptime(newest_hour, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)).total_seconds() / 86400


@st.cache_data(show_spinner=False)
def build_page(movement_json: str, age_label: str) -> str:
    data = json.loads(movement_json)
    payload = {key: data[key] for key in ("hours", "ships", "fixes")}
    payload["age_label"] = age_label
    payload["waterways"] = data.get("waterways", [])
    payload["max_line_hours"] = data.get("max_line_hours", 3)
    # Inside a <script> block, so "</" must not end it early.
    text = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    page = PAGE.replace("__MAP_JS__", MAP_PAGE_JS).replace("__MAP__", str(MAP_HEIGHT_PX))
    return page.replace("__DATA__", text)


def render_quiet_spells(spells: list[dict]) -> None:
    st.subheader("Ships that went quiet inside this area")
    if not spells:
        st.info("No ship in this replay stopped appearing for 12 hours or more and then came back somewhere else.")
        return
    table = pd.DataFrame(spells).sort_values("hours", ascending=False)
    table["type_label"] = table["type"].map(ship_type_label)
    table["name"] = reported(table["name"], "Name not reported")
    table["flag"] = reported(table["flag"])
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        height=min(420, 38 + 35 * len(table)),
        column_order=["name", "flag", "type_label", "from", "to", "hours", "km", "speed_before"],
        column_config={
            "name": st.column_config.TextColumn("Ship", width="medium"),
            "flag": st.column_config.TextColumn("Flag", width=FLAG_COLUMN_PX),
            "type_label": "Type",
            "from": "Last heard (UTC)",
            "to": "Heard again (UTC)",
            "hours": st.column_config.NumberColumn("Hours quiet", format="%d"),
            "km": st.column_config.NumberColumn("Moved (km)", format="%.0f"),
            "speed_before": st.column_config.NumberColumn("Speed before (knots)", format="%.1f"),
        },
    )
    st.caption(
        "Both ends of each spell are inside the area, and the ship reappeared at least 5 km away. "
        "It may have switched AIS off, or may just have been out of reception, so this is only a reason to look closer."
    )


def render() -> None:
    text = ship_movement_text()
    if text is None:
        st.info("The recent-movement data hasn't been built yet. Run dashboard/pipeline/build_gfw.py.")
    else:
        movement = json.loads(text)
        age = days_old(movement["hours"][-1], datetime.now(UTC))
        st.subheader("Recent movement: real ships, about 3-4 days behind")
        st.markdown(
            f"**{len(movement['ships']):,} real ships** in this area over {len(movement['hours']) // 24} days, from AIS. "
            "Press Play, or click a ship to see who it is."
        )
        st.iframe(build_page(text, f"{age:.1f} days old."))
        st.markdown(GFW_ATTRIBUTION)
        checks = movement.get("position_checks")
        if checks:
            st.caption(
                f"Positions are checked against OpenStreetMap water. Fishing Watch's rounding to about 1 km left {checks['moved_to_water']:,} of {checks['positions']:,} on the shoreline or on land, "
                f"so those were moved to the nearest water, no further than the rounding could have shifted them. "
                f"Another {checks['removed']} positions, from {checks['removed_ships']} ships, were too far from water to be real and are left out."
            )
        render_quiet_spells(movement.get("quiet_spells", []))
    st.subheader("Right now: live AIS")
    live.render()
