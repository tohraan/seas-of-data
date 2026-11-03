// The closing chapter: a live MapLibre map of all 250 real detections, with a pass picker. Colours follow the real AIS
// check against Global Fishing Watch (scripts/export_live.py): matched, no AIS (a lead), or not checked.
import gsap from 'gsap';

const TEAL = '#3FB8A6';
const AMBER = '#F0A93B';
const SLATE = '#7f8ba0';
const STATUS_COLOR = ['match', ['get', 'status'], 'ais_match', TEAL, 'no_ais', AMBER, SLATE];
const LABEL = { ais_match: 'AIS match', no_ais: 'No AIS · a lead', not_checked: 'AIS not checked' };
const WHY = { no_gfw_target: 'no GFW target within 1 km', not_available: 'GFW has not published this pass' };
const esc = (v) => String(v).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
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
    fetch(import.meta.env.BASE_URL + 'data/detections.geojson').then((r) => r.json()),
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
    noais: document.querySelector('.ms-noais'),
    unchecked: document.querySelector('.ms-unchecked'),
  };
  const shown = { total: 0, matched: 0, noais: 0, unchecked: 0 };
  const setStats = (feats) => {
    const count = (s) => feats.filter((f) => f.properties.status === s).length;
    const next = { total: feats.length, matched: count('ais_match'), noais: count('no_ais'), unchecked: count('not_checked') };
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
      id: 'det-halo', type: 'circle', source: 'det', filter: ['==', ['get', 'status'], 'no_ais'],
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 7, 12, 14], 'circle-color': AMBER, 'circle-opacity': 0.18, 'circle-blur': 0.6 },
    });
    map.addLayer({
      id: 'det', type: 'circle', source: 'det',
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 3, 12, 7],
        'circle-color': 'rgba(0,0,0,0)',
        'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 8, 1.5, 12, 2.5],
        'circle-stroke-color': STATUS_COLOR,
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
        <b class="${p.status === 'ais_match' ? 't' : p.status === 'no_ais' ? 'a' : ''}">${LABEL[p.status]}</b>
        ${p.status === 'ais_match' && p.name && p.name !== 'null' ? `<span>${esc(p.name)}${p.flag && p.flag !== 'null' ? ` · ${esc(p.flag)}` : ''}</span>` : ''}
        ${WHY[p.check] ? `<span>${WHY[p.check]}</span>` : ''}
        <span>${esc(p.id)} · ${Math.round(p.length_m)} m · radar class ${esc(p.radar_class)}</span>
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
