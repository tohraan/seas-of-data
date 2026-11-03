"""Play the real radar passes on the map, with a ring for how far a ship could have gone at an assumed speed.

Dots never move between passes, because radar has no speed or heading. Anything else would be invented.
"""
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from analysis import CLASS_LABELS
from components import MAP_HEIGHT_PX, cached_radar_image, pass_time
from data import Evidence

HEIGHT_PX = MAP_HEIGHT_PX + 190
PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.1.14/dist.min.js"></script>
<style>
  :root { --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781; --surface:#1a1a19; --line:#383835; --ship:#3987e5; --fixed:#c98500; --unc:#898781; }
  html,body { margin:0; background:#0d0d0d; color:var(--ink); font:14px system-ui,-apple-system,"Segoe UI",sans-serif; }
  #map { position:relative; height:__MAP__px; border-radius:8px; overflow:hidden; background:#0d0d0d; }
  #bar { display:flex; flex-wrap:wrap; gap:10px 16px; align-items:center; padding:12px 2px 6px; }
  button { background:var(--surface); color:var(--ink); border:1px solid var(--line); border-radius:6px; padding:7px 14px; font:inherit; cursor:pointer; }
  button:hover { border-color:var(--muted); }
  button.on { background:#22344a; border-color:var(--ship); }
  #ticks { display:flex; gap:6px; flex-wrap:wrap; }
  label { color:var(--ink2); display:flex; align-items:center; gap:8px; }
  input[type=range] { width:120px; accent-color:var(--ship); }
  output { color:var(--ink); min-width:34px; font-variant-numeric:tabular-nums; }
  #status { font-weight:600; font-size:15px; }
  #note { color:var(--muted); font-size:13px; line-height:1.45; }
  #hud { position:absolute; left:12px; top:12px; background:rgba(13,13,13,.78); border-radius:6px; padding:8px 12px; pointer-events:none; line-height:1.5; z-index:2; }
  .key { display:inline-block; width:10px; height:10px; border-radius:50%; margin:0 5px 0 12px; }
  #attr { position:absolute; left:8px; bottom:6px; color:#c3c2b7; font-size:11px; background:rgba(13,13,13,.6); padding:1px 6px; border-radius:4px; z-index:2; }
  #error { padding:20px; color:var(--ink2); }
</style></head><body>
<div id="map"><div id="hud"></div><div id="attr">Contains modified Copernicus Sentinel data (2026) · OpenStreetMap · CARTO</div></div>
<div id="bar">
  <button id="play">▶ Play</button>
  <div id="ticks"></div>
  <label>Assumed speed <input id="speed" type="range" min="0" max="25" value="12"><output id="speedv"></output></label>
  <label>Hours after the pass <input id="hours" type="range" min="0" max="6" step="0.5" value="0"><output id="hoursv"></output></label>
  <button id="radar" class="on">Radar image</button>
  <button id="unc">Show uncertain</button>
</div>
<div id="status"></div>
<div id="note">Each frame is a real satellite snapshot, and passes are days apart, so a dot that disappears has left the area or wasn't detected. Rings show how far a ship could have gone at the speed you set: an estimate, because radar measures neither speed nor heading.
  <span class="key" style="background:var(--ship)"></span>Ship <span class="key" style="background:var(--unc)"></span>Uncertain <span class="key" style="background:var(--fixed)"></span>Likely fixed</div>
<script>
const DATA = __DATA__;
const COLORS = { ship:[57,135,229], uncertain:[137,135,129], likely_fixed:[201,133,0] };
const NAMES = { ship:"Ship", uncertain:"Uncertain", likely_fixed:"Likely fixed" };
const $ = id => document.getElementById(id);
const S = { i:DATA.passes.length-1, playing:false, radar:true, uncertain:false, speed:12, hours:0, pop:1, chosen:null };
let timer = null, raf = null;
function setHud(p, points) {
  const c = k => points.filter(d => d.c === k).length;
  $("hud").innerHTML = `<b>${p.label}</b> · ${p.satellite}${p.orbit ? " · " + p.orbit : ""}<br>${c("ship")} ship, ${c("uncertain")} uncertain, ${c("likely_fixed")} likely fixed`;
  const km = S.speed * 1.852 * S.hours;
  const gap = p.gap_hours === null ? "" : ` Next pass ${p.gap_hours} hours later.`;
  $("status").textContent = (S.hours > 0 && S.speed > 0)
    ? `After ${S.hours} h at ${S.speed} knots, a ship could be up to ${Math.round(km)} km away (estimate).${S.chosen ? " Highlighted: " + S.chosen + "." : " Click a ship to highlight its ring."}${gap}`
    : `Snapshot from ${p.label}.${gap}`;
}
function layers() {
  const p = DATA.passes[S.i];
  const visible = d => d.p === S.i && (S.uncertain || d.c !== "uncertain");
  const points = DATA.points.filter(visible);
  const previous = S.i > 0 ? DATA.points.filter(d => d.p === S.i - 1 && (S.uncertain || d.c !== "uncertain")) : [];
  const rings = S.hours > 0 && S.speed > 0 ? points.filter(d => d.c === "ship") : [];
  setHud(p, DATA.points.filter(d => d.p === S.i));
  const out = [];
  if (S.radar) {
    DATA.passes.forEach((q, n) => { if (q.image && n === S.i) out.push(new deck.BitmapLayer({ id:"radar"+n, image:q.image, bounds:q.corners, opacity:0.92 })); });
  }
  // Thin outlines only: filled rings stack into a fog that hides the radar.
  out.push(new deck.ScatterplotLayer({ id:"rings", data:rings, getPosition:d=>[d.x,d.y], getRadius:S.speed*1852*S.hours, radiusUnits:"meters",
    filled:false, getLineColor:[109,167,236,S.chosen?35:70], stroked:true, lineWidthUnits:"pixels", getLineWidth:1, updateTriggers:{getRadius:[S.speed,S.hours], getLineColor:[S.chosen]} }));
  out.push(new deck.ScatterplotLayer({ id:"chosen-ring", data:rings.filter(d=>d.id===S.chosen), getPosition:d=>[d.x,d.y], getRadius:S.speed*1852*S.hours, radiusUnits:"meters",
    getFillColor:[57,135,229,45], getLineColor:[240,239,236,230], stroked:true, lineWidthUnits:"pixels", getLineWidth:2, updateTriggers:{getRadius:[S.speed,S.hours]} }));
  out.push(new deck.ScatterplotLayer({ id:"ghost", data:previous, getPosition:d=>[d.x,d.y], getRadius:3, radiusUnits:"pixels", getFillColor:[240,239,236,70] }));
  out.push(new deck.ScatterplotLayer({ id:"now", data:points, getPosition:d=>[d.x,d.y], radiusUnits:"pixels", radiusScale:S.pop,
    getRadius:d=>d.c==="ship"?6:d.c==="likely_fixed"?7:4, getFillColor:d=>COLORS[d.c]||COLORS.ship, stroked:true, lineWidthUnits:"pixels",
    getLineWidth:d=>d.c==="likely_fixed"?2:0, getLineColor:[240,239,236], pickable:true }));
  return out;
}
const view = { longitude:54.875, latitude:24.925, zoom:8.25, pitch:0, bearing:0 };
let map;
function boot() {
  map = new deck.DeckGL({ container:"map", initialViewState:view, controller:true, layers:[],
    onClick: info => { S.chosen = info.object ? info.object.id : null; draw(); },
    mapStyle:"https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json", map:maplibregl, attributionControl:false,
    getTooltip:({object}) => object && { html:`<b>${NAMES[object.c]||object.c}</b> · ${object.id}<br>about ${object.l} m · brightness ${object.b} dB<br>seen at this spot in ${object.n} pass(es)`,
      style:{ background:"#1a1a19", color:"#f0efec", fontSize:"13px" } } });
  draw();
}
function draw() { if (map) map.setProps({ layers:layers() }); }
function popIn() {
  cancelAnimationFrame(raf);
  const t0 = performance.now();
  const step = now => { const t = Math.min(1,(now-t0)/450); S.pop = t + Math.sin(t*Math.PI)*0.6; draw(); if (t<1) raf = requestAnimationFrame(step); };
  raf = requestAnimationFrame(step);
}
function setPass(i) {
  S.i = i; S.chosen = null;
  document.querySelectorAll("#ticks button").forEach((b,n) => b.classList.toggle("on", n===i));
  popIn();
}
function setPlaying(on) {
  S.playing = on; $("play").textContent = on ? "❚❚ Pause" : "▶ Play"; clearInterval(timer);
  if (on) { setPass((S.i+1)%DATA.passes.length); timer = setInterval(() => setPass((S.i+1)%DATA.passes.length), 2600); }
}
function controls() {
  DATA.passes.forEach((p,n) => { const b = document.createElement("button"); b.textContent = p.short; b.onclick = () => { setPlaying(false); setPass(n); }; $("ticks").appendChild(b); });
  document.querySelectorAll("#ticks button")[S.i].classList.add("on");
  $("play").onclick = () => setPlaying(!S.playing);
  $("radar").onclick = e => { S.radar = !S.radar; e.target.classList.toggle("on", S.radar); draw(); };
  $("unc").onclick = e => { S.uncertain = !S.uncertain; e.target.classList.toggle("on", S.uncertain); draw(); };
  const speed = () => { S.speed = +$("speed").value; $("speedv").textContent = S.speed + " kn"; draw(); };
  const hours = () => { S.hours = +$("hours").value; $("hoursv").textContent = S.hours + " h"; draw(); };
  $("speed").oninput = speed; $("hours").oninput = hours; speed(); hours();
}
if (!window.deck || !window.maplibregl) {
  $("map").innerHTML = '<div id="error">The playback map needs an internet connection to load.</div>';
} else {
  controls(); boot();
}
</script></body></html>"""


@st.cache_data(show_spinner=False)
def build_page(points_json: str, passes_json: str) -> str:
    data = json.dumps({"points": json.loads(points_json), "passes": json.loads(passes_json)}, separators=(",", ":"))
    # Inside a <script> block, so "</" must not end it early.
    return PAGE.replace("__DATA__", data.replace("</", "<\\/")).replace("__MAP__", str(MAP_HEIGHT_PX))


def render(frame: pd.DataFrame, evidence: Evidence | None, manifest: dict | None) -> None:
    moments = frame.groupby("scene_id")["timestamp"].first().sort_values()
    order = {scene: index for index, scene in enumerate(moments.index)}
    gaps = moments.diff().shift(-1).dt.total_seconds() / 3600
    passes = []
    for scene, moment in moments.items():
        info = evidence.pass_info(scene) if evidence else None
        gap = gaps[scene]
        passes.append({
            "label": pass_time(moment),
            "short": f"{moment:%d %b}",
            "satellite": scene.split("_")[0],
            "orbit": info.get("orbit") if info else None,
            "image": cached_radar_image(info["image"]) if info else None,
            "corners": info["corners"] if info else None,
            "gap_hours": None if pd.isna(gap) else round(gap),
        })
    points = [
        {
            "x": round(row["lon"], 5), "y": round(row["lat"], 5), "p": order[row["scene_id"]], "c": row["radar_class"],
            "id": row["id"], "l": None if pd.isna(row["length_m"]) else round(row["length_m"]),
            "b": None if pd.isna(row["contrast_db"]) else round(row["contrast_db"], 1), "n": int(row["persistence"]),
        }
        for row in frame.to_dict("records")
    ]
    st.markdown(f"The {len(passes)} real radar passes over this water, played in order. {CLASS_LABELS['ship']}-class dots are shown first; add the uncertain ones with the button below the map.")
    components.html(build_page(json.dumps(points), json.dumps(passes)), height=HEIGHT_PX, scrolling=False)
