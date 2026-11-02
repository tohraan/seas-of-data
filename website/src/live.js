// Chapter 05: dashboard screenshots, a live MapLibre map of all 250 detections with a pass picker, and ships per port.
import gsap from 'gsap';

const TEAL = '#3FB8A6';
const AMBER = '#F0A93B';
const STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

export function initLive({ reduced }) {
  if (!reduced) {
    gsap.utils.toArray('.browser').forEach((b, i) => {
      gsap.fromTo(b, { rotateX: 14, y: 80 + i * 60, autoAlpha: 0.2 }, {
        rotateX: 0, y: 0, autoAlpha: 1, ease: 'none',
        scrollTrigger: { trigger: b, start: 'top 95%', end: 'top 45%', scrub: 0.6 },
      });
    });
  }

  // The map library is large; load it only when the map is near the screen.
  const mapEl = document.querySelector('#map');
  const io = new IntersectionObserver((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    io.disconnect();
    initMap(mapEl, reduced);
  }, { rootMargin: '600px 0px' });
  io.observe(mapEl);

  portChart(reduced);
}

async function initMap(container, reduced) {
  const [{ default: maplibregl }, data] = await Promise.all([
    import('maplibre-gl'),
    fetch('/data/detections.geojson').then((r) => r.json()),
    import('maplibre-gl/dist/maplibre-gl.css'),
  ]);
  const map = new maplibregl.Map({
    container,
    style: STYLE,
    bounds: bounds(data.features),
    fitBoundsOptions: { padding: 48 },
    attributionControl: { compact: true },
    cooperativeGestures: true,
    fadeDuration: 0,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

  const stats = {
    total: document.querySelector('.ms-total'),
    matched: document.querySelector('.ms-matched'),
    dark: document.querySelector('.ms-dark'),
  };
  const shown = { total: 0, matched: 0, dark: 0 };
  const setStats = (feats) => {
    const next = { total: feats.length, dark: feats.filter((f) => f.properties.dark).length };
    next.matched = next.total - next.dark;
    for (const k of Object.keys(next)) {
      gsap.to(shown, {
        [k]: next[k], duration: reduced ? 0 : 0.6, ease: 'power2.out', overwrite: 'auto',
        onUpdate: () => { stats[k].textContent = Math.round(shown[k]); },
      });
    }
  };

  map.on('load', () => {
    map.addSource('det', { type: 'geojson', data });
    map.addLayer({
      id: 'det-halo', type: 'circle', source: 'det', filter: ['==', ['get', 'dark'], true],
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 7, 12, 14], 'circle-color': AMBER, 'circle-opacity': 0.18, 'circle-blur': 0.6 },
    });
    map.addLayer({
      id: 'det', type: 'circle', source: 'det',
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 3, 12, 7],
        'circle-color': 'rgba(0,0,0,0)',
        'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 8, 1.5, 12, 2.5],
        'circle-stroke-color': ['case', ['get', 'dark'], AMBER, TEAL],
      },
    });
    setStats(data.features);

    const popup = new maplibregl.Popup({ closeButton: false, offset: 10, className: 'det-pop' });
    map.on('mouseenter', 'det', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'det', () => { map.getCanvas().style.cursor = ''; });
    map.on('click', 'det', (e) => {
      const f = e.features[0];
      const p = f.properties;
      popup.setLngLat(f.geometry.coordinates).setHTML(`
        <b class="${p.dark ? 'a' : 't'}">${p.dark ? 'Dark lead' : 'Matched'}</b>
        <span>${p.id} · ${Math.round(p.length_m)} m · conf ${(+p.confidence).toFixed(2)}</span>
        <span>${p.timestamp.slice(0, 16).replace('T', ' ')} UTC${p.port && p.port !== 'null' ? ` · ${p.port}` : ''}</span>`).addTo(map);
    });
  });

  // Pass picker.
  document.querySelectorAll('.pass-chips button').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.pass-chips button').forEach((b) => b.classList.toggle('on', b === btn));
      const pass = btn.dataset.pass;
      const feats = pass === 'all' ? data.features : data.features.filter((f) => f.properties.timestamp.startsWith(pass));
      const src = map.getSource('det');
      if (src) src.setData({ ...data, features: feats });
      setStats(feats);
    });
  });
}

function bounds(features) {
  const lons = features.map((f) => f.geometry.coordinates[0]);
  const lats = features.map((f) => f.geometry.coordinates[1]);
  return [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
}

// Ships counted in each port box on each pass: grouped bars, Jebel Ali and Khalifa Port.
async function portChart(reduced) {
  const rows = await fetch('/data/port_activity.json').then((r) => r.json());
  const svg = document.querySelector('.port-chart');
  const NS = 'http://www.w3.org/2000/svg';
  const add = (tag, attrs, parent = svg) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    parent.appendChild(n);
    return n;
  };
  const dates = [...new Set(rows.map((r) => r.date))].sort();
  const ports = [...new Set(rows.map((r) => r.port))];
  const max = Math.max(...rows.map((r) => r.vessel_count), 1);
  const top = Math.ceil(max / 5) * 5;
  const L = 34, R = 548, T = 30, B = 200;
  const yOf = (v) => B - (v / top) * (B - T);
  for (let v = 0; v <= top; v += 5) {
    add('line', { x1: L, x2: R, y1: yOf(v), y2: yOf(v), class: 'grid' });
    add('text', { x: L - 8, y: yOf(v) + 4, class: 'axis', 'text-anchor': 'end' }).textContent = v;
  }
  const groupW = (R - L) / dates.length;
  const barW = 28;
  const bars = [];
  dates.forEach((d, i) => {
    const gx = L + groupW * i + groupW / 2;
    ports.forEach((p, j) => {
      const r = rows.find((x) => x.date === d && x.port === p);
      const v = r ? r.vessel_count : 0;
      const x = gx + (j - ports.length / 2) * (barW + 6) + 3;
      const bar = add('rect', { x, y: yOf(v), width: barW, height: Math.max(B - yOf(v), 0), rx: 3, class: `bar bar--${j}` });
      const lbl = add('text', { x: x + barW / 2, y: yOf(v) - 7, class: 'val', 'text-anchor': 'middle' });
      lbl.textContent = v;
      bars.push({ bar, lbl });
    });
    const day = new Date(`${d}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
    add('text', { x: gx, y: B + 22, class: 'axis', 'text-anchor': 'middle' }).textContent = day;
  });
  ports.forEach((p, j) => {
    const g = add('g', { transform: `translate(${L + j * 130} 8)` });
    add('rect', { width: 10, height: 10, rx: 2, class: `bar bar--${j}` }, g);
    add('text', { x: 16, y: 9, class: 'axis' }, g).textContent = p;
  });
  if (reduced) return;
  gsap.timeline({ scrollTrigger: { trigger: svg, start: 'top 80%' } })
    .from(bars.map((b) => b.bar), { scaleY: 0, transformOrigin: '50% 100%', duration: 0.9, stagger: 0.06, ease: 'power3.out' })
    .from(bars.map((b) => b.lbl), { autoAlpha: 0, duration: 0.4, stagger: 0.06 }, 0.3);
}
