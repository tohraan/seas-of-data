"""Play the real radar passes on the map, with a ring for how far a ship could have gone at an assumed speed.

Dots never move between passes, because radar has no speed or heading. Anything else would be invented.
"""
import json

import pandas as pd
import streamlit as st

from analysis import CLASS_LABELS
from components import MAP_HEIGHT_PX, MAP_PAGE_JS, cached_radar_image, pass_time
from data import Evidence, load_wide_radar

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.1.14/dist.min.js"></script>
<style>
  :root { --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781; --surface:#1a1a19; --line:#383835; --ship:#3987e5; --fixed:#c98500; --unc:#898781; }
  html,body { margin:0; background:#0d0d0d; color:var(--ink); font:14px system-ui,-apple-system,"Segoe UI",sans-serif; }
  /* The same credits are in #attr, which matches the page. */
  .maplibregl-ctrl-bottom-right { display:none; }
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
<div id="map"><div id="hud"></div><div id="attr">Contains modified Copernicus Sentinel data (2026) · © OpenStreetMap contributors · © CARTO</div></div>
<div id="bar">
  <button id="play">▶ Play</button>
  <div id="ticks"></div>
  <label>Assumed speed <input id="speed" type="range" min="0" max="25" value="12"><output id="speedv"></output></label>
  <label>Hours after the pass <input id="hours" type="range" min="0" max="6" step="0.5" value="0"><output id="hoursv"></output></label>
  <button id="radar" class="on">Radar image</button>
  <button id="unc">Show uncertain</button>
</div>
<div id="status"></div>
<div id="note">Each frame is a real satellite snapshot, and passes are days apart, so a dot that disappears has left the area or wasn't detected. Click a ship for a ring showing how far it could have gone at the speed you set: an estimate, because radar measures neither speed nor heading.
  <span class="key" style="background:var(--ship)"></span>Ship <span class="key" style="background:var(--unc)"></span>Uncertain <span class="key" style="background:var(--fixed)"></span>Likely fixed</div>
<script>
__MAP_JS__
const DATA = __DATA__;
const COLORS = { ship:[57,135,229], uncertain:[137,135,129], likely_fixed:[201,133,0] };
const NAMES = { ship:"Ship", uncertain:"Uncertain", likely_fixed:"Likely fixed" };
const $ = id => document.getElementById(id);
const esc = text => String(text).replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
const S = { i:DATA.passes.length-1, playing:false, radar:true, uncertain:false, speed:12, hours:0, pop:1, chosen:null };
let timer = null, raf = null;
function setHud(p, points) {
  const c = k => points.filter(d => d.c === k).length;
  $("hud").innerHTML = `<b>${p.label}</b> · ${p.satellite}${p.orbit ? " · " + p.orbit : ""}<br>${c("ship")} ship, ${c("uncertain")} uncertain, ${c("likely_fixed")} likely fixed`;
  const km = S.speed * 1.852 * S.hours;
  const gap = p.gap_hours === null ? "" : ` Next pass ${p.gap_hours} hours later.`;
  $("status").textContent = (S.hours > 0 && S.speed > 0)
    ? `After ${S.hours} h at ${S.speed} knots, a ship could be up to ${Math.round(km)} km away (estimate).${S.chosen ? " Ring shown for " + S.chosen + "." : " Click a ship to see its ring."}${gap}`
    : `Snapshot from ${p.label}. Click a ship to see how far it could have gone.${gap}`;
}
function layers() {
  const p = DATA.passes[S.i];
  const visible = d => d.p === S.i && (S.uncertain || d.c !== "uncertain");
  const points = DATA.points.filter(visible);
  const previous = S.i > 0 ? DATA.points.filter(d => d.p === S.i - 1 && (S.uncertain || d.c !== "uncertain")) : [];
  const ring = S.hours > 0 && S.speed > 0 ? points.filter(d => d.id === S.chosen) : [];
  setHud(p, DATA.points.filter(d => d.p === S.i));
  const out = [];
  if (S.radar) {
    const q = DATA.passes[S.i];
    if (q.wide) out.push(new deck.BitmapLayer({ id:"wide"+S.i, image:q.wide, bounds:q.wide_corners, opacity:0.7 }));
    if (q.image) out.push(new deck.BitmapLayer({ id:"radar"+S.i, image:q.image, bounds:q.corners, opacity:0.92 }));
  }
  out.push(new deck.ScatterplotLayer({ id:"chosen-ring", data:ring, getPosition:d=>[d.x,d.y], getRadius:S.speed*1852*S.hours, radiusUnits:"meters",
    getFillColor:[57,135,229,45], getLineColor:[240,239,236,230], stroked:true, lineWidthUnits:"pixels", getLineWidth:2, updateTriggers:{getRadius:[S.speed,S.hours]} }));
  out.push(new deck.ScatterplotLayer({ id:"ghost", data:previous, getPosition:d=>[d.x,d.y], getRadius:3, radiusUnits:"pixels", getFillColor:[240,239,236,70] }));
  out.push(new deck.ScatterplotLayer({ id:"now", data:points, getPosition:d=>[d.x,d.y], radiusUnits:"pixels", radiusScale:S.pop,
    getRadius:d=>d.c==="ship"?6:d.c==="likely_fixed"?7:4, getFillColor:d=>COLORS[d.c]||COLORS.ship, stroked:true, lineWidthUnits:"pixels",
    getLineWidth:d=>d.c==="likely_fixed"?2:0, getLineColor:[240,239,236], pickable:true }));
  out.push(PORT_LABELS);
  return out;
}
const view = { longitude:55.1, latitude:25.0, zoom:7.6, pitch:0, bearing:0 };
let map;
function boot() {
  map = new deck.DeckGL({ container:"map", initialViewState:view, controller:true, layers:[],
    onClick: info => {
      S.chosen = info.object && info.object.c === "ship" ? info.object.id : null;
      // A ring needs some time to grow, so give it a start if the slider is still at zero.
      if (S.chosen && S.hours === 0) { $("hours").value = 2; S.hours = 2; $("hoursv").textContent = "2 h"; }
      draw();
    },
    mapStyle:"https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json", map:maplibregl, attributionControl:false,
    getTooltip:({object}) => object && { html:`<b>${esc(NAMES[object.c]||object.c)}</b> · ${esc(object.id)}<br>about ${esc(object.l)} m · brightness ${esc(object.b)} dB<br>seen at this spot in ${esc(object.n)} pass(es)`,
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
    page = PAGE.replace("__MAP_JS__", MAP_PAGE_JS).replace("__MAP__", str(MAP_HEIGHT_PX))
    return page.replace("__DATA__", data.replace("</", "<\\/"))


def render(frame: pd.DataFrame, evidence: Evidence | None, manifest: dict | None) -> None:
    wide_radar = load_wide_radar()
    moments = frame.groupby("scene_id")["timestamp"].first().sort_values()
    order = {scene: index for index, scene in enumerate(moments.index)}
    gaps = moments.diff().shift(-1).dt.total_seconds() / 3600
    passes = []
    for scene, moment in moments.items():
        info = evidence.pass_info(scene) if evidence else None
        wide = wide_radar.get(scene) if info else None
        gap = gaps[scene]
        passes.append({
            "label": pass_time(moment),
            "short": f"{moment:%d %b}",
            "satellite": scene.split("_")[0],
            "orbit": info.get("orbit") if info else None,
            "image": cached_radar_image(info["image"]) if info else None,
            "corners": info["corners"] if info else None,
            "wide": cached_radar_image(wide["image"]) if wide else None,
            "wide_corners": wide["corners"] if wide else None,
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
    st.iframe(build_page(json.dumps(points), json.dumps(passes)))
