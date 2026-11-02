import '@fontsource/instrument-serif/400.css';
import '@fontsource/instrument-serif/400-italic.css';
import '@fontsource-variable/inter-tight';
import '@fontsource-variable/jetbrains-mono';
import './style.css';

import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText } from 'gsap/SplitText';
import Lenis from 'lenis';
import { Sequence } from './sequence.js';
import { initDetect } from './detect.js';
import { initLive } from './live.js';
import { initAis, initHud, initTask } from './story.js';

gsap.registerPlugin(ScrollTrigger, SplitText);

// ?film: the page as a film set. No smooth scrolling and no scrub lag, so scripts/film.mjs can step it frame by frame.
const film = new URLSearchParams(location.search).has('film');
const reduced = !film && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const scrub = film ? true : 0.6;
document.documentElement.classList.toggle('rm', reduced);
document.documentElement.classList.toggle('film', film);

// In film mode GSAP's clock only moves when the capture script says so, so every frame is reproducible.
let filmTime = 0;
if (film) gsap.ticker.remove(gsap.updateRoot);

// Smooth scroll, driven by GSAP's ticker so ScrollTrigger and Lenis share one clock.
let lenis = null;
if (!reduced && !film) {
  lenis = new Lenis({ lerp: 0.09, wheelMultiplier: 0.9 });
  lenis.on('scroll', ScrollTrigger.update);
  gsap.ticker.add((t) => lenis.raf(t * 1000));
  gsap.ticker.lagSmoothing(0);
}
document.querySelectorAll('a[href^="#"]').forEach((a) => {
  a.addEventListener('click', (e) => {
    const el = document.querySelector(a.getAttribute('href'));
    if (!el) return;
    e.preventDefault();
    if (lenis) lenis.scrollTo(el, { duration: 1.6 });
    else el.scrollIntoView();
  });
});

// Sequence frames: the manifest says which renders exist and at which widths.
const FALLBACK = { a: 180, b: 150, c2: 150, d: 120 };
async function manifest() {
  let m = {};
  try {
    const r = await fetch('/frames/manifest.json', { cache: 'no-cache' });
    if (r.ok) m = await r.json();
  } catch { /* fall through */ }
  for (const [k, count] of Object.entries(FALLBACK)) m[k] ??= { count, widths: [960] };
  return m;
}

function pickWidth(widths) {
  const need = Math.min(window.innerWidth * Math.min(window.devicePixelRatio || 1, 2), 1920);
  const sorted = [...widths].sort((x, y) => x - y);
  return sorted.find((w) => w >= need * 0.9) || sorted[sorted.length - 1];
}

// A pinned chapter that scrubs a frame sequence, with text beats faded in and out at fixed progress points.
// `frame` maps chapter progress to sequence progress (the buoy camera freezes on its snapshot).
function sequenceChapter(section, seq, { length, extra, frame = (p) => p }) {
  const stage = section.querySelector('.seq-stage');
  const state = { p: 0 };
  const tl = gsap.timeline({
    defaults: { ease: 'none' },
    scrollTrigger: {
      trigger: section,
      start: 'top top',
      end: `+=${length}%`,
      pin: stage,
      scrub,
      invalidateOnRefresh: true,
    },
  });
  tl.to(state, { p: 1, duration: 1, onUpdate: () => seq.seek(frame(state.p)) }, 0);
  section.querySelectorAll('.beat').forEach((beat) => {
    const tIn = parseFloat(beat.dataset.in);
    const tOut = parseFloat(beat.dataset.out);
    tl.fromTo(beat, { autoAlpha: 0, y: 36 }, { autoAlpha: 1, y: 0, duration: 0.05, ease: 'power2.out' }, tIn);
    if (tOut < 1) tl.to(beat, { autoAlpha: 0, y: -36, duration: 0.05, ease: 'power2.in' }, tOut - 0.05);
  });
  extra?.(tl);
  return tl;
}

function heroIntro() {
  const title = new SplitText('.hero-title', { type: 'lines,words', mask: 'lines' });
  const tl = gsap.timeline({ delay: 0.15 });
  tl.from('.eyebrow span', { y: 20, autoAlpha: 0, stagger: 0.08, duration: 0.8, ease: 'power3.out' })
    .from(title.words, { yPercent: 110, duration: 1.1, stagger: 0.035, ease: 'expo.out' }, 0.1)
    .from('.hero-lede', { y: 24, autoAlpha: 0, duration: 0.9, ease: 'power3.out' }, 0.6)
    .from('.scroll-cue', { autoAlpha: 0, duration: 0.8 }, 1.0)
    .from('.hud-bar', { y: -20, autoAlpha: 0, duration: 0.8, ease: 'power3.out' }, 0.3);
}

function hideLoader() {
  const el = document.querySelector('.loader');
  if (!el || el.classList.contains('done')) return;
  // A CSS fade and a timer, not a tween: background tabs pause requestAnimationFrame.
  el.classList.add('done');
  setTimeout(() => el.remove(), 800);
  if (!reduced) heroIntro();
}

function buoyParts(tl) {
  tl.from('.buoy-head > *', { autoAlpha: 0, y: 40, stagger: 0.02, duration: 0.05 }, 0.01);
  const parts = [...document.querySelectorAll('.parts li')];
  const starts = parts.map((li) => parseFloat(li.dataset.in));
  parts.forEach((li, i) => {
    tl.fromTo(li, { autoAlpha: 0, x: 40 }, { autoAlpha: 1, x: 0, duration: 0.04, ease: 'power2.out' }, starts[i]);
  });
  // Highlight the part most recently called out, in either scroll direction.
  tl.eventCallback('onUpdate', () => {
    const t = tl.time();
    const active = starts.findLastIndex((s0) => t >= s0 + 0.02);
    parts.forEach((li, j) => li.classList.toggle('on', j === active));
  });
  tl.fromTo('.buoy-spec', { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.05 }, 0.86);
}

// The buoy camera: live until the snapshot, then frozen while the picture goes up the link.
const SNAP = 0.55;
function camera(tl) {
  const section = document.querySelector('#pov');
  tl.eventCallback('onUpdate', () => section.classList.toggle('frozen', tl.time() >= SNAP));
  tl.from('#pov .cam', { opacity: 0, duration: 0.04 }, 0)
    .fromTo('#pov .cam-flash', { opacity: 0 }, { opacity: 0.9, duration: 0.008 }, SNAP)
    .to('#pov .cam-flash', { opacity: 0, duration: 0.04 }, SNAP + 0.008)
    .fromTo('#pov .cam-snap', { autoAlpha: 0, y: 20 }, { autoAlpha: 1, y: 0, duration: 0.04 }, SNAP + 0.03)
    .fromTo('#pov .cam-bar i', { scaleX: 0 }, { scaleX: 1, duration: 0.3 }, SNAP + 0.06);
}

// Unpinned chapters after the story: plain entrance reveals.
function reveals() {
  if (reduced) return;
  const up = (targets, trigger, extra = {}) => gsap.from(targets, {
    y: 40, autoAlpha: 0, duration: 0.9, stagger: 0.1, ease: 'power3.out',
    scrollTrigger: { trigger, start: 'top 80%' }, ...extra,
  });
  up('.alert-copy > *', '.alert-grid');
  up('.alert-card', '.alert-grid', { delay: 0.2 });
  up('.alert-rows > div', '.alert-rows', { stagger: 0.12, delay: 0.3, x: -20, y: 0 });
  up('.dash .browser', '.dash');
  up('#cadence .wrap > .kicker, #cadence h2', '#cadence');
  gsap.from('.pass', { scale: 0, autoAlpha: 0, stagger: 0.12, duration: 0.5, ease: 'back.out(2)', scrollTrigger: { trigger: '.lanes', start: 'top 80%' } });
  gsap.from('.watch', { scaleX: 0, transformOrigin: 'left center', duration: 1.6, ease: 'power2.inOut', scrollTrigger: { trigger: '.lanes', start: 'top 80%' } });
  up('.trio article', '.trio');
  up('#real .wrap > .kicker, #real h2', '#real');
  up('.real-col', '.real-grid', { stagger: 0.15 });
  up('#film .wrap > *', '#film');
  up('#live .wrap > .kicker, #live h2, #live .body', '#live');
}

// Scroll range of each chapter, for the film script's pacing table.
function marks() {
  const out = {};
  document.querySelectorAll('main > section').forEach((s) => {
    const r = s.getBoundingClientRect();
    out[s.id] = [r.top + scrollY, r.bottom + scrollY - innerHeight];
  });
  return out;
}

async function main() {
  const [m, story, sar] = await Promise.all([
    manifest(),
    fetch('/data/story.json').then((r) => r.json()),
    fetch('/data/sar_points.json').then((r) => r.json()),
  ]);
  const sections = { a: '#top', b: '#orbit', c2: '#buoy', d: '#pov' };
  const seqs = {};
  for (const [name, sel] of Object.entries(sections)) {
    const section = document.querySelector(sel);
    seqs[name] = new Sequence(section.querySelector('.seq-canvas'), { name, count: m[name].count, width: pickWidth(m[name].widths) });
  }
  document.querySelector('.detect-handoff').src = seqs.b.url(seqs.b.count - 1);
  document.querySelector('.alert-snap').src = seqs.d.url(seqs.d.count - 1);

  // Show the page as soon as the hero's first frame is ready (or after 4 s, whatever happens first).
  const first = seqs.a.load();
  const bar = document.querySelector('.loader-bar i');
  gsap.to(bar, { scaleX: 0.7, duration: 2.5, ease: 'power2.out' });
  Promise.race([first, new Promise((r) => setTimeout(r, film ? 60000 : 4000))]).then(() => {
    gsap.to(bar, { scaleX: 1, duration: 0.3 });
    setTimeout(hideLoader, 300);
  });
  first.then(() => { seqs.b.load(); seqs.c2.load(); seqs.d.load(); });

  const track = initHud(story);
  if (reduced) {
    seqs.a.seek(0); seqs.b.seek(1); seqs.c2.seek(0.4); seqs.d.seek(1);
    initAis(story, sar, { reduced });
    await initDetect({ reduced, focusId: story.target.id });
    initTask(story, { reduced });
    initLive({ reduced });
    track();
    return;
  }

  // Pins are created in page order: ScrollTrigger lays each one out after the ones above it.
  sequenceChapter(document.querySelector('#top'), seqs.a, {
    length: 420,
    extra: (tl) => {
      tl.to('.hero-copy', { autoAlpha: 0, y: -60, duration: 0.12, ease: 'power2.in' }, 0.04)
        .to('.scroll-cue', { autoAlpha: 0, duration: 0.05 }, 0.02)
        .to('#top .seq-shade--hero', { opacity: 0.35, duration: 0.15 }, 0.04)
        .to('#top .seq-fade', { opacity: 1, duration: 0.08 }, 0.92);
    },
  });
  initAis(story, sar, { reduced, scrub });
  sequenceChapter(document.querySelector('#orbit'), seqs.b, {
    length: 380,
    extra: (tl) => { tl.from('#orbit .seq-canvas', { opacity: 0, duration: 0.04 }, 0); },
  });
  await initDetect({ reduced, scrub, focusId: story.target.id });
  initTask(story, { reduced, scrub });
  sequenceChapter(document.querySelector('#buoy'), seqs.c2, { length: 380, extra: buoyParts });
  sequenceChapter(document.querySelector('#pov'), seqs.d, { length: 320, extra: camera, frame: (p) => Math.min(p / SNAP, 1) });
  reveals();
  initLive({ reduced });
  track();
  ScrollTrigger.refresh();

  if (film) {
    // Runs after the then() above that starts the other sequences, so every `done` exists by now.
    const all = first.then(() => Promise.all(Object.values(seqs).map((s) => s.done)));
    window.__film = {
      ready: all.then(() => document.fonts.ready).then(() => true),
      marks,
      max: () => ScrollTrigger.maxScroll(window),
      // Scroll to y, then advance time-based tweens (title, reveals) by dt seconds.
      seek(y, dt = 1 / 30) {
        window.scrollTo(0, y);
        ScrollTrigger.update();
        filmTime += dt;
        gsap.updateRoot(filmTime);
      },
    };
  }
}

main();
