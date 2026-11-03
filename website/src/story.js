// The mission overlay (clock, network, message log) and the two story chapters that are drawn rather than rendered:
// the AIS traffic picture and the buoy tasking. Everything here is derived from scroll position, so it plays the
// same forwards and backwards.
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, parent) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  parent?.appendChild(n);
  return n;
};
const clamp = (v, a = 0, b = 1) => Math.min(Math.max(v, a), b);
const secs = (t) => t.split(':').reduce((s, v) => s * 60 + +v, 0);
const hms = (s) => [s / 3600, (s / 60) % 60, s % 60].map((v) => String(Math.floor(v)).padStart(2, '0')).join(':');
const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);

// --- Mission overlay ------------------------------------------------------------------------------------------

export function initHud(story) {
  const hud = document.querySelector('.hud');
  const clocks = [...document.querySelectorAll('.clock-t')];
  const log = hud.querySelector('.log');
  const pulse = hud.querySelector('.net-pulse');
  const nodes = Object.fromEntries([...hud.querySelectorAll('[data-node]')].map((g) => [g.dataset.node, g]));
  const links = [...hud.querySelectorAll('[data-link]')].map((p) => ({ p, ends: p.dataset.link.split('-') }));
  const chapters = story.chapters;
  let shownClock = '';
  let shownLog = '';

  function render(i, p) {
    const ch = chapters[i];
    const [t0, t1] = ch.clock.map(secs);
    const clock = hms(t0 + (t1 - t0) * p);
    if (clock !== shownClock) {
      clocks.forEach((c) => { c.textContent = clock; });
      shownClock = clock;
    }

    const lines = chapters.slice(0, i).flatMap((c) => c.log).concat(ch.log.filter((l) => p >= l.at));
    const key = `${lines.length}`;
    if (key !== shownLog) {
      const grew = lines.length > +shownLog;
      log.innerHTML = lines.slice(-5).map((l, k, a) => `<li class="${l.tone === 'a' ? 'a' : ''}${grew && k === a.length - 1 ? ' new' : ''}">`
        + `<time>${l.t}</time><b>${l.src}</b><span>${esc(l.msg)}</span>${l.real ? '<i>real</i>' : ''}</li>`).join('');
      shownLog = key;
    }

    const lit = new Set(ch.lit);
    for (const [id, g] of Object.entries(nodes)) g.classList.toggle('on', lit.has(id));
    const live = (ch.pulses || []).find((q) => p >= q.a && p <= q.b);
    for (const { p: path, ends } of links) {
      path.classList.toggle('on', ends.every((e) => lit.has(e)));
      path.classList.toggle('hot', !!live && ends.includes(live.from) && ends.includes(live.to));
    }
    if (live) {
      const [x0, y0] = story.nodes[live.from];
      const [x1, y1] = story.nodes[live.to];
      const k = gsap.parseEase('power1.inOut')((p - live.a) / (live.b - live.a));
      pulse.setAttribute('cx', x0 + (x1 - x0) * k);
      pulse.setAttribute('cy', y0 + (y1 - y0) * k);
      pulse.classList.add('on');
    } else {
      pulse.classList.remove('on');
    }
  }

  // Called once every chapter's pin exists, so the section boxes below include their pin spacing.
  return function track() {
    const spans = chapters.map((c) => {
      const section = document.querySelector(`[data-story="${c.id}"]`);
      const pinned = !!section.querySelector('.pin-spacer');
      return ScrollTrigger.create({
        trigger: section,
        start: pinned ? 'top top' : 'top 75%',
        end: pinned ? 'bottom bottom' : 'center 35%',
      });
    });
    const update = () => {
      const y = ScrollTrigger.getScrollFunc(window)();
      let i = spans.findLastIndex((s) => y >= s.start);
      if (i < 0) i = 0;
      const s = spans[i];
      render(i, clamp((y - s.start) / Math.max(s.end - s.start, 1)));
      // The panel shows once the title has gone and leaves before the alert copy scrolls under it.
      const first = spans[0];
      const last = spans.at(-1);
      hud.classList.toggle('side-on', y > first.start + (first.end - first.start) * 0.06 && y < last.start + (last.end - last.start) * 0.35);
      hud.classList.toggle('done', y > last.end + 200);
    };
    ScrollTrigger.create({ start: 0, end: 'max', onUpdate: update, onRefresh: update });
    update();
  };
}

// --- Chapter 1: the public AIS picture ------------------------------------------------------------------------

export function initAis(story, sar, { reduced, scrub }) {
  const section = document.querySelector('#ais');
  const svg = section.querySelector('.ais-map');
  const { bounds: [lon0, lat0, lon1, lat1], w: W, h: H } = sar;
  const X = (lon) => ((lon - lon0) / (lon1 - lon0)) * W;
  const Y = (lat) => ((lat1 - lat) / (lat1 - lat0)) * H;

  // Graticule every 0.1 degrees.
  const grid = svg.querySelector('.ais-grid');
  for (let lon = Math.ceil(lon0 * 10) / 10; lon < lon1; lon += 0.1) {
    el('line', { x1: X(lon), x2: X(lon), y1: 0, y2: H }, grid);
    el('text', { x: X(lon) + 8, y: H - 14 }, grid).textContent = `${lon.toFixed(1)}°E`;
  }
  for (let lat = Math.ceil(lat0 * 10) / 10; lat < lat1; lat += 0.1) {
    el('line', { x1: 0, x2: W, y1: Y(lat), y2: Y(lat) }, grid);
    el('text', { x: 14, y: Y(lat) - 8 }, grid).textContent = `${lat.toFixed(1)}°N`;
  }

  // Every ship the radar later matched, reporting normally: a heading, a little drift, a ping ring.
  let seed = 11;
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const shipsG = svg.querySelector('.ais-ships');
  const ships = sar.points.filter((p) => !p.dark).map((p) => {
    const heading = rand() * 360;
    const speed = 10 + rand() * 50;
    const g = el('g', { class: 'ais-ship' }, shipsG);
    const ping = el('circle', { class: 'ais-ping', r: 8 }, g);
    const body = el('path', { class: 'ais-tri', d: 'M0 -14L9 11L0 6L-9 11Z', transform: `rotate(${heading})` }, g);
    return { p, g, ping, body, heading, speed, off: rand() };
  });
  // The tanker: no pings, only its last report, until tracking drops it.
  const t = story.tanker.last_ais;
  const ghost = el('g', { class: 'ais-ship ais-corvane', transform: `translate(${t.x} ${t.y})` }, shipsG);
  el('circle', { class: 'ais-ghost', r: 30 }, ghost);
  el('path', { class: 'ais-tri', d: 'M0 -14L9 11L0 6L-9 11Z', transform: 'rotate(110)' }, ghost);
  const tag = el('text', { class: 'ais-tag', x: 42, y: -8 }, ghost);
  el('tspan', { x: 42 }, tag).textContent = story.tanker.name.toUpperCase();
  el('tspan', { x: 42, dy: 34, class: 'ais-sub' }, tag).textContent = `last report ${t.t.slice(0, 5)}`;
  el('tspan', { x: 42, dy: 34, class: 'ais-lost' }, tag).textContent = 'dropped from tracking';

  const frame = () => {
    // Keep the tanker in frame on phones: a narrower window, centred further west.
    const r = window.innerWidth / window.innerHeight;
    const portrait = r < 1;
    const vh = portrait ? 1100 : 1700 / r;
    const vw = vh * r;
    const cx = portrait ? 820 : 900;
    svg.setAttribute('viewBox', `${cx - vw / 2} ${(portrait ? 560 : 520) - vh / 2} ${vw} ${vh}`);
  };
  frame();
  window.addEventListener('resize', frame);

  const draw = (p) => {
    for (const s of ships) {
      const a = ((s.heading - 90) * Math.PI) / 180;
      s.g.setAttribute('transform', `translate(${s.p.x + Math.cos(a) * s.speed * p} ${s.p.y + Math.sin(a) * s.speed * p})`);
      const ph = (p * 6 + s.off) % 1;
      s.ping.setAttribute('r', 8 + ph * 46);
      s.ping.style.opacity = (1 - ph) * 0.8;
    }
    ghost.classList.toggle('lost', p >= 0.45);
  };

  if (reduced) { draw(0.6); return; }

  const state = { p: 0 };
  gsap.timeline({
    defaults: { ease: 'none' },
    scrollTrigger: { trigger: section, start: 'top top', end: '+=240%', pin: '.ais-stage', scrub, invalidateOnRefresh: true },
  })
    .to(state, { p: 1, duration: 1, onUpdate: () => draw(state.p) }, 0)
    .fromTo('.ais-copy', { autoAlpha: 0, y: 30 }, { autoAlpha: 1, y: 0, duration: 0.08 }, 0.02)
    .to('.ais-copy', { autoAlpha: 0, y: -30, duration: 0.06 }, 0.4)
    .fromTo('.ais-tag .ais-sub', { opacity: 0 }, { opacity: 1, duration: 0.05 }, 0.18)
    .fromTo('.ais-caption', { autoAlpha: 0, y: 24 }, { autoAlpha: 1, y: 0, duration: 0.06 }, 0.56)
    .to('.ais-stage', { opacity: 0, duration: 0.08 }, 0.92);
}

// --- Chapter 4: tasking the buoy ------------------------------------------------------------------------------

export function initTask(story, { reduced, scrub }) {
  const section = document.querySelector('#task');
  const code = section.querySelector('.task-json code');
  const t = story.task;
  const text = `{\n${Object.entries(t).map(([k, v]) => `  "${k}": ${JSON.stringify(v).replace(/,/g, ', ')}`).join(',\n')}\n}`;
  const range = section.querySelector('.task-range');
  range.setAttribute('pathLength', '100');
  // Lead and buoy left of the task panel on wide screens, centred on phones.
  const map = section.querySelector('.task-map');
  const frame = () => map.setAttribute('viewBox', window.innerWidth > 760 ? '663 310 480 270' : '735 283 240 270');
  frame();
  window.addEventListener('resize', frame);

  const type = (k) => {
    const n = Math.round(text.length * k);
    code.innerHTML = `${esc(text.slice(0, n))}<i class="caret${k >= 1 ? ' off' : ''}"></i>`;
  };

  if (reduced) { type(1); range.style.strokeDashoffset = 0; return; }

  const state = { p: 0 };
  gsap.timeline({
    defaults: { ease: 'none' },
    scrollTrigger: { trigger: section, start: 'top top', end: '+=200%', pin: '.task-stage', scrub, invalidateOnRefresh: true },
  })
    .fromTo('.task-copy > *', { autoAlpha: 0, y: 30 }, { autoAlpha: 1, y: 0, duration: 0.08, stagger: 0.03 }, 0)
    .fromTo('.task-map', { autoAlpha: 0, scale: 0.96 }, { autoAlpha: 1, scale: 1, duration: 0.1 }, 0.04)
    .fromTo(range, { strokeDashoffset: 100 }, { strokeDashoffset: 0, duration: 0.14 }, 0.14)
    .fromTo('.task-dist', { opacity: 0 }, { opacity: 1, duration: 0.05 }, 0.26)
    .fromTo('.task-json', { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.04 }, 0.3)
    .to(state, { p: 1, duration: 0.3, onUpdate: () => type(state.p) }, 0.32)
    .to('.task-buoy', { scale: 1.6, transformOrigin: '50% 50%', duration: 0.05, yoyo: true, repeat: 1 }, 0.84)
    .to({}, { duration: 0.06 }, 0.94);
  type(0);
}
