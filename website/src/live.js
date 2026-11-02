// The closing chapter: a live MapLibre map of all 250 real detections, with a pass picker.
import gsap from 'gsap';

const TEAL = '#3FB8A6';
const AMBER = '#F0A93B';
const STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

export function initLive({ reduced }) {
  // The map library is large; load it only when the map is near the screen.
  const mapEl = document.querySelector('#map');
  const io = new IntersectionObserver((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    io.disconnect();
    initMap(mapEl, reduced);
  }, { rootMargin: '600px 0px' });
  io.observe(mapEl);
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
