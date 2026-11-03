"""The dashboard's look: one stylesheet, the header and the footer. Numbers in the header come from the data, never typed in."""
import base64
import html

import streamlit as st

LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="44" height="44">
  <defs>
    <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#38d9c6" stop-opacity=".0"/><stop offset="1" stop-color="#38d9c6" stop-opacity=".55"/></linearGradient>
  </defs>
  <circle cx="24" cy="24" r="21" fill="#0b1418" stroke="#1f3a3e"/>
  <circle cx="24" cy="24" r="14" fill="none" stroke="#1f3a3e"/>
  <circle cx="24" cy="24" r="7" fill="none" stroke="#1f3a3e"/>
  <path d="M24 24 L24 3 A21 21 0 0 1 43.2 15.6 Z" fill="url(#sweep)"/>
  <path d="M24 24 L43.2 15.6" stroke="#38d9c6" stroke-width="1.4"/>
  <path d="M15.5 30.5 l9-3.2 4.5 1.6 -1.6 2.4 -10.6 1.2 z" fill="#e9eef1"/>
  <circle cx="33" cy="12.5" r="2.2" fill="#ff5d5d"/>
</svg>"""
# st.html drops <svg> and data: images, so the logo is a CSS background.
LOGO_URL = f"data:image/svg+xml;base64,{base64.b64encode(LOGO.encode()).decode()}"

CSS = """<style>
.sod-logo { width:44px; height:44px; flex:none; background:url("LOGO_URL") center/contain no-repeat; }
:root { --sod-teal:#38d9c6; --sod-blue:#4ea8ff; --sod-red:#ff5d5d; --sod-amber:#f2b84b; --sod-ink:#e9eef1; --sod-muted:#8a9aa3; --sod-line:#1d2a31; --sod-card:#0c1418; }
[data-testid="stHeader"] { background:transparent; height:0; }
[data-testid="stMainBlockContainer"] { padding-top:1.4rem; padding-bottom:3rem; max-width:1500px; }
[data-testid="stAppViewContainer"] { background:
  radial-gradient(1200px 500px at 85% -10%, rgba(56,217,198,.10), transparent 60%),
  radial-gradient(900px 400px at -10% 0%, rgba(78,168,255,.08), transparent 60%), #070b0e; }

/* Header */
.sod-hero { position:relative; overflow:hidden; border:1px solid var(--sod-line); border-radius:18px; padding:26px 30px 22px;
  background:linear-gradient(135deg, rgba(15,28,34,.95), rgba(7,11,14,.95)); margin-bottom:18px; }
.sod-hero::after { content:""; position:absolute; inset:0; pointer-events:none;
  background-image:linear-gradient(rgba(56,217,198,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(56,217,198,.05) 1px, transparent 1px);
  background-size:44px 44px; mask-image:linear-gradient(90deg, transparent, #000 40%, #000); }
.sod-brand { display:flex; align-items:center; gap:14px; }
.sod-word { font-weight:800; letter-spacing:.22em; font-size:13px; color:var(--sod-teal); }
.sod-word span { color:var(--sod-muted); font-weight:500; letter-spacing:.12em; margin-left:10px; }
.sod-hero h1 { font-size:clamp(28px, 3.4vw, 44px); line-height:1.08; margin:16px 0 8px; padding:0; font-weight:750; letter-spacing:-.02em; color:var(--sod-ink); }
.sod-hero h1 em { font-style:normal; background:linear-gradient(90deg, #38d9c6, #4ea8ff); -webkit-background-clip:text; background-clip:text; color:transparent; }
.sod-hero p.sod-sub { color:var(--sod-muted); font-size:16px; max-width:820px; margin:0 0 18px; }
.sod-pills { display:flex; flex-wrap:wrap; gap:8px; position:relative; z-index:1; }
.sod-pill { display:inline-flex; align-items:center; gap:8px; padding:6px 12px; border-radius:999px; border:1px solid var(--sod-line);
  background:rgba(12,20,24,.85); font-size:13px; color:var(--sod-ink); font-family:"Geist Mono", ui-monospace, monospace; }
.sod-pill i { width:8px; height:8px; border-radius:50%; display:inline-block; background:var(--sod-teal); box-shadow:0 0 10px var(--sod-teal); }
.sod-pill.red i { background:var(--sod-red); box-shadow:0 0 10px var(--sod-red); }
.sod-pill.blue i { background:var(--sod-blue); box-shadow:0 0 10px var(--sod-blue); }
.sod-pill.amber i { background:var(--sod-amber); box-shadow:0 0 10px var(--sod-amber); }
.sod-live { animation:sod-pulse 2.2s ease-in-out infinite; }
@keyframes sod-pulse { 50% { opacity:.35; } }
@media (prefers-reduced-motion: reduce) { .sod-live { animation:none; } }
@media (max-width: 640px) { .sod-hero { padding:20px 18px; } .sod-word span { display:none; } }

/* Metric tiles */
[data-testid="stMetric"] { background:linear-gradient(180deg, rgba(15,25,30,.9), rgba(10,16,20,.9)); border:1px solid var(--sod-line);
  border-radius:14px; padding:14px 16px 12px; }
[data-testid="stMetricLabel"] p { text-transform:uppercase; letter-spacing:.12em; font-size:11.5px; color:var(--sod-muted); font-weight:600; }
[data-testid="stMetricValue"] { font-family:"Geist Mono", ui-monospace, monospace; letter-spacing:-.02em; }

/* Tabs as a navigation bar */
[data-testid="stTabs"] [role="tablist"], [role="tablist"] { gap:4px; border:1px solid var(--sod-line); border-radius:14px; padding:5px; background:rgba(12,20,24,.8);
  flex-wrap:wrap; height:auto; box-shadow:none; }
[data-testid="stTab"] { border-radius:10px; padding:8px 14px; height:auto; color:var(--sod-muted); border:none; box-shadow:none; transition:background .15s, color .15s; }
[data-testid="stTab"]::before, [data-testid="stTab"]::after { display:none !important; }
[data-testid="stTab"]:hover { color:var(--sod-ink); background:rgba(56,217,198,.07); }
[data-testid="stTab"][aria-selected="true"] { background:linear-gradient(90deg, #38d9c6, #5cc8ff); }
[data-testid="stTab"][aria-selected="true"] p, [data-testid="stTab"][aria-selected="true"] span { color:#04201c !important; font-weight:650; }
[data-testid="stTab"] p { font-size:14px; margin:0; }

/* Notes, captions, footer */
[data-testid="stAlert"] { border-radius:12px; border:1px solid var(--sod-line); }
[data-testid="stCaptionContainer"] { color:var(--sod-muted); }
.sod-footer { margin-top:28px; padding:18px 4px 0; border-top:1px solid var(--sod-line); color:var(--sod-muted); font-size:13px; display:flex; flex-wrap:wrap; gap:6px 18px; }
.sod-footer b { color:var(--sod-ink); font-weight:600; }
.sod-footer a { color:var(--sod-teal); text-decoration:none; }
</style>""".replace("LOGO_URL", LOGO_URL)


def apply_style() -> None:
    st.html(CSS)


def hero(passes: int, detections: int, ships: int, leads: int, latest: str, checked: bool) -> None:
    """The page header. Every pill is a count from the loaded data."""
    lead_pill = f'<span class="sod-pill red"><i></i>{leads} possibly dark leads</span>' if checked else '<span class="sod-pill amber"><i></i>AIS check pending</span>'
    st.html(f"""
<div class="sod-hero">
  <div class="sod-brand"><span class="sod-logo"></span><div class="sod-word">SEAS OF DATA<span>GULF MARITIME INTELLIGENCE</span></div></div>
  <h1>Finding <em>dark ships</em> in the Gulf from space.</h1>
  <p class="sod-sub">Real Sentinel-1 radar, checked against AIS, on one map with every ship's last known position and where each one could have gone since.
  Free and open data only. Every number says where it came from.</p>
  <div class="sod-pills">
    <span class="sod-pill"><i class="sod-live"></i>{passes} Sentinel-1 passes · latest {html.escape(latest)}</span>
    <span class="sod-pill blue"><i></i>{detections:,} radar detections · {ships:,} ship class</span>
    {lead_pill}
  </div>
</div>""")


def footer() -> None:
    st.html("""
<div class="sod-footer">
  <span><b>Seas of Data</b> · Supernova × SpacePoint Hackathon 2026</span>
  <span>Radar: Copernicus Sentinel-1 (ESA)</span>
  <span>AIS: <a href="https://globalfishingwatch.org" target="_blank" rel="noopener">Global Fishing Watch</a></span>
  <span>Orbits: CelesTrak</span>
  <span>Map: © OpenStreetMap, © CARTO</span>
</div>""")
