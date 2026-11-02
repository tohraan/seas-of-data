// Chapter 3: the real 2 Nov Sentinel-1 pass. It opens on the orbit render's last frame (same ground, same framing),
// cross-fades into radar, walks the pipeline (sea mask, CFAR hits, merged and geocoded ships, AIS match), then
// closes in on one dark lead, d0190, the ship the rest of the story follows.
import gsap from 'gsap';

const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, parent) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  parent?.appendChild(n);
  return n;
};

export async function initDetect({ reduced, scrub, focusId }) {
  const data = await fetch('/data/sar_points.json').then((r) => r.json());
  const section = document.querySelector('.detect');
  const sar = section.querySelector('.sar');
  const svg = section.querySelector('.sar-svg');
  svg.setAttribute('viewBox', `0 0 ${data.w} ${data.h}`);
  section.querySelector('.sar-n').textContent = data.points.length;

  // Port boxes, dashed, named inside their top-left corner.
  const ports = el('g', { class: 'ports-g' }, svg);
  for (const [name, poly] of Object.entries(data.ports)) {
    const g = el('g', { class: 'port' }, ports);
    el('polygon', { points: poly.map((p) => p.join(',')).join(' ') }, g);
    const x = Math.max(Math.min(...poly.map((p) => p[0])), 0) + 18;
    const y = Math.max(Math.min(...poly.map((p) => p[1])), 0) + 44;
    el('text', { x, y }, g).textContent = name.toUpperCase();
  }

  // One group per ship: CFAR cross, ring, label. Sorted west to east so the CFAR sweep reads left to right.
  const pts = [...data.points].sort((a, b) => a.x - b.x);
  const coordIds = new Set([...pts].filter((p) => !p.dark).sort((a, b) => b.conf - a.conf).slice(0, 3).map((p) => p.id));
  const ships = pts.map((p) => {
    const g = el('g', { class: `ship${p.dark ? ' dark' : ''}`, transform: `translate(${p.x} ${p.y})` }, svg);
    const cross = el('path', { class: 'cross', d: 'M-22 0H-8M8 0H22M0 -22V-8M0 8V22' }, g);
    const ring = el('circle', { class: 'ring', r: 26 }, g);
    let label = null;
    if (coordIds.has(p.id) || p.dark) {
      label = el('text', { class: `tag${p.dark ? ' tag--dark' : ''}`, x: 40, y: 10 }, g);
      label.textContent = p.dark ? `DARK · ${Math.round(p.len)} m` : `${p.lat.toFixed(3)}°N ${p.lon.toFixed(3)}°E`;
    }
    return { p, g, cross, ring, label };
  });
  const focus = ships.find((s) => s.p.id === focusId);
  focus.g.classList.add('focus');
  const coordLabels = ships.filter((s) => s.label && !s.p.dark).map((s) => s.label);
  const darkLabels = ships.filter((s) => s.label && s.p.dark).map((s) => s.label);

  // The radar sits in a box sized like the orbit canvas's cover fit, so the first frame lines up with the render.
  const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length / data.w;
  const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length / data.h;
  const box = { w: 0, h: 0, left: 0, top: 0 };
  const layout = () => {
    const W = window.innerWidth;
    const H = window.innerHeight;
    const s = Math.max(W / data.w, H / data.h);
    Object.assign(box, { w: data.w * s, h: data.h * s, left: (W - data.w * s) / 2, top: (H - data.h * s) / 2 });
    Object.assign(sar.style, { width: `${box.w}px`, height: `${box.h}px`, left: `${box.left}px`, top: `${box.top}px` });
  };
  layout();
  window.addEventListener('resize', layout);
  sar.style.transformOrigin = `${(cx * 100).toFixed(2)}% ${(cy * 100).toFixed(2)}%`;
  // Pan so the ships' centre lands left of the panel (desktop) or above the sheet (phone).
  const wide = () => window.innerWidth > 760;
  const panX = () => window.innerWidth * (wide() ? 0.36 : 0.5) - (box.left + cx * box.w);
  const panY = () => window.innerHeight * (wide() ? 0.46 : 0.3) - (box.top + cy * box.h);
  // Close-up on the lead: put it left of the card (desktop) or above it (phone).
  const ZOOM = 3.2;
  const zoomX = () => window.innerWidth * (wide() ? 0.44 : 0.5)
    - (box.left + cx * box.w + (focus.p.x / data.w - cx) * box.w * ZOOM);
  const zoomY = () => window.innerHeight * (wide() ? 0.5 : 0.3)
    - (box.top + cy * box.h + (focus.p.y / data.h - cy) * box.h * ZOOM);

  const steps = [...section.querySelectorAll('.steps li')];
  const STEP_AT = [0.14, 0.26, 0.38, 0.52, 0.66];
  const setStep = (k) => steps.forEach((li, i) => {
    li.classList.toggle('on', i === k);
    li.classList.toggle('done', i < k);
  });

  if (reduced) {
    setStep(4);
    section.classList.add('matched', 'focused');
    return;
  }

  const setLive = (self) => section.classList.toggle('live', self.scroll() >= self.start - 1);
  const tl = gsap.timeline({
    defaults: { ease: 'none' },
    scrollTrigger: {
      trigger: section,
      start: 'top top',
      end: '+=460%',
      pin: '.detect-stage',
      scrub,
      invalidateOnRefresh: true,
      // The stage overlaps the orbit chapter's last screen; it only shows once its pin has taken over.
      onToggle: setLive,
      onRefresh: setLive,
    },
    onUpdate() {
      const t = tl.time();
      setStep(STEP_AT.findLastIndex((a) => t >= a));
      section.classList.toggle('matched', t >= STEP_AT[4] + 0.02);
      section.classList.toggle('focused', t >= 0.76);
    },
  });

  // Render -> radar.
  tl.fromTo('.detect-handoff', { opacity: 1 }, { opacity: 0, duration: 0.07, ease: 'power1.inOut' }, 0.02)
    .fromTo('.detect-intro', { autoAlpha: 0, y: 24 }, { autoAlpha: 1, y: 0, duration: 0.03 }, 0.03)
    .to('.detect-intro', { autoAlpha: 0, y: -24, duration: 0.03 }, 0.11)
    // Panel in, push in towards the ships.
    .fromTo('.detect-panel', { autoAlpha: 0, x: () => (wide() ? 60 : 0), y: () => (wide() ? 0 : 60) },
      { autoAlpha: 1, x: 0, y: 0, duration: 0.04, ease: 'power2.out' }, 0.12)
    .fromTo(sar, { scale: 1, x: 0, y: 0 }, { scale: 1.55, x: panX, y: panY, duration: 0.3, ease: 'power1.inOut' }, 0.12)
    // Sea mask: flood the sea, then let it settle back.
    .fromTo('.sar-sea', { opacity: 0 }, { opacity: 0.6, duration: 0.04 }, STEP_AT[1])
    .to('.sar-sea', { opacity: 0.16, duration: 0.04 }, STEP_AT[2] - 0.02)
    .fromTo('.ports-g', { opacity: 0 }, { opacity: 1, duration: 0.04 }, STEP_AT[1] + 0.03);

  // CFAR: a cross on every bright point, swept west to east.
  ships.forEach((s, i) => {
    tl.fromTo(s.cross, { opacity: 0, scale: 2.4, transformOrigin: '50% 50%' }, { opacity: 1, scale: 1, duration: 0.012 },
      STEP_AT[2] + 0.005 + (i / ships.length) * 0.08);
  });
  // Merge and geocode: crosses become rings, a few coordinates show.
  tl.to(ships.map((s) => s.cross), { opacity: 0, duration: 0.03 }, STEP_AT[3] + 0.02)
    .fromTo(ships.map((s) => s.ring), { attr: { r: 0 }, opacity: 0 },
      { attr: { r: 26 }, opacity: 1, duration: 0.04, stagger: 0.0008 }, STEP_AT[3] + 0.02)
    .fromTo(coordLabels, { opacity: 0 }, { opacity: 1, duration: 0.03 }, STEP_AT[3] + 0.05)
    .to(coordLabels, { opacity: 0, duration: 0.03 }, STEP_AT[4])
    // AIS match: the .matched class recolours rings teal or amber; dark tags slide in.
    .fromTo(darkLabels, { opacity: 0, x: -8 }, { opacity: 1, x: 0, duration: 0.03, stagger: 0.004 }, STEP_AT[4] + 0.04)
    // The lead: everything else steps back, the camera closes in, its card comes up.
    .to('.detect-panel', { autoAlpha: 0, duration: 0.04 }, 0.74)
    .to(darkLabels, { opacity: 0, duration: 0.03 }, 0.74)
    .to(sar, { scale: ZOOM, x: zoomX, y: zoomY, duration: 0.12, ease: 'power2.inOut' }, 0.75)
    .fromTo('.lead-card', { autoAlpha: 0, x: () => (wide() ? 60 : 0), y: () => (wide() ? 0 : 60) },
      { autoAlpha: 1, x: 0, y: 0, duration: 0.05, ease: 'power2.out' }, 0.86)
    .to({}, { duration: 0.06 }, 0.94);
}
