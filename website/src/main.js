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

gsap.registerPlugin(ScrollTrigger, SplitText);

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
document.documentElement.classList.toggle('rm', reduced);

// Smooth scroll, driven by GSAP's ticker so ScrollTrigger and Lenis share one clock.
let lenis = null;
if (!reduced) {
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
async function manifest() {
  try {
    const r = await fetch('/frames/manifest.json', { cache: 'no-cache' });
    if (r.ok) return r.json();
  } catch { /* fall through */ }
  return { widths: [960], a: { count: 180 }, b: { count: 150 }, c: { count: 180 } };
}

function pickWidth(widths) {
  const need = Math.min(window.innerWidth * Math.min(window.devicePixelRatio || 1, 2), 1920);
  const sorted = [...widths].sort((x, y) => x - y);
  return sorted.find((w) => w >= need * 0.9) || sorted[sorted.length - 1];
}

// A pinned chapter that scrubs a frame sequence, with text beats faded in and out at fixed progress points.
function sequenceChapter(section, seq, { length, extra }) {
  const stage = section.querySelector('.seq-stage');
  const state = { p: 0 };
  const tl = gsap.timeline({
    defaults: { ease: 'none' },
    scrollTrigger: {
      trigger: section,
      start: 'top top',
      end: `+=${length}%`,
      pin: stage,
      scrub: 0.6,
      invalidateOnRefresh: true,
    },
  });
  tl.to(state, { p: 1, duration: 1, onUpdate: () => seq.seek(state.p) }, 0);
  section.querySelectorAll('.beat').forEach((beat) => {
    const tIn = parseFloat(beat.dataset.in);
    const tOut = parseFloat(beat.dataset.out);
    tl.fromTo(beat, { autoAlpha: 0, y: 36 }, { autoAlpha: 1, y: 0, duration: 0.05, ease: 'power2.out' }, tIn);
    beat.querySelectorAll('[data-count]').forEach((el) => countTo(tl, el, tIn + 0.01, 0.08));
    if (tOut < 1) tl.to(beat, { autoAlpha: 0, y: -36, duration: 0.05, ease: 'power2.in' }, tOut - 0.05);
  });
  extra?.(tl);
  return tl;
}

function countTo(tl, el, at, duration) {
  const end = parseFloat(el.dataset.count);
  const o = { v: 0 };
  tl.to(o, { v: end, duration, ease: 'power1.out', onUpdate: () => { el.textContent = Math.round(o.v).toLocaleString('en'); } }, at);
}

function heroIntro() {
  const title = new SplitText('.hero-title', { type: 'lines,words', mask: 'lines' });
  const tl = gsap.timeline({ delay: 0.15 });
  tl.from('.eyebrow span', { y: 20, autoAlpha: 0, stagger: 0.08, duration: 0.8, ease: 'power3.out' })
    .from(title.words, { yPercent: 110, duration: 1.1, stagger: 0.035, ease: 'expo.out' }, 0.1)
    .from('.hero-lede', { y: 24, autoAlpha: 0, duration: 0.9, ease: 'power3.out' }, 0.6)
    .from('.scroll-cue', { autoAlpha: 0, duration: 0.8 }, 1.0)
    .from('.nav', { y: -20, autoAlpha: 0, duration: 0.8, ease: 'power3.out' }, 0.3);
}

function hideLoader() {
  const el = document.querySelector('.loader');
  if (!el || el.classList.contains('done')) return;
  // A CSS fade and a timer, not a tween: background tabs pause requestAnimationFrame.
  el.classList.add('done');
  setTimeout(() => el.remove(), 800);
  if (!reduced) heroIntro();
}

function problem() {
  const box = document.querySelector('.dots');
  for (let i = 0; i < 100; i++) box.appendChild(document.createElement('i'));
  const dots = [...box.children];
  // 74 of 100 go dark, in a scattered order (seeded so it is the same on every load).
  let s = 7;
  const rand = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  const order = dots.map((d, i) => [rand(), i]).sort((a, b) => a[0] - b[0]).map(([, i]) => dots[i]).slice(0, 74);
  if (reduced) { order.forEach((d) => d.classList.add('off')); return; }
  const n = { v: 0 };
  let shown = 0;
  const tl = gsap.timeline({
    scrollTrigger: { trigger: '.problem', start: 'top 70%', end: 'center 45%', scrub: 0.8 },
  });
  tl.from('.problem-copy > *', { y: 40, autoAlpha: 0, stagger: 0.08, duration: 0.3 }, 0)
    .to(n, {
      v: order.length, duration: 0.75, ease: 'none',
      onUpdate: () => {
        const k = Math.round(n.v);
        if (k === shown) return;
        order.forEach((d, i) => d.classList.toggle('off', i < k));
        shown = k;
      },
    }, 0.15);
  gsap.from('.pain-card', {
    y: 50, autoAlpha: 0, stagger: 0.12, duration: 0.9, ease: 'power3.out',
    scrollTrigger: { trigger: '.pain', start: 'top 80%' },
  });
}

function solution() {
  if (reduced) return;
  const tl = gsap.timeline({ scrollTrigger: { trigger: '.venn-wrap', start: 'top 75%', end: 'center 50%', scrub: 0.8 } });
  tl.fromTo('.venn-radar', { attr: { cx: 190 } }, { attr: { cx: 300 }, duration: 1 }, 0)
    .fromTo('.venn-ais', { attr: { cx: 610 } }, { attr: { cx: 500 }, duration: 1 }, 0)
    .from('.venn-label', { autoAlpha: 0, y: 12, stagger: 0.15, duration: 0.4 }, 0.6)
    .from('.rules article', { autoAlpha: 0, y: 30, stagger: 0.12, duration: 0.5 }, 0.3);
  gsap.from('.solution-title, .solution .kicker', {
    y: 50, autoAlpha: 0, duration: 1, stagger: 0.1, ease: 'power3.out',
    scrollTrigger: { trigger: '.solution', start: 'top 75%' },
  });
  const loop = gsap.timeline({ scrollTrigger: { trigger: '.loop', start: 'top 75%', end: 'bottom 70%', scrub: 0.8 } });
  document.querySelector('.loop-line path').setAttribute('pathLength', '1000');
  loop.fromTo('.loop-line path', { strokeDashoffset: 1000 }, { strokeDashoffset: 0, duration: 1 }, 0)
    .from('.loop-steps li', { autoAlpha: 0, y: 40, stagger: 0.2, duration: 0.4 }, 0);
}

function reveals() {
  if (reduced) return;
  gsap.utils.toArray('.chapter .wrap > .kicker, .chapter .wrap > h2, .chapter .wrap > .body').forEach((el) => {
    if (el.closest('.solution') || el.closest('.problem')) return;
    gsap.from(el, { y: 40, autoAlpha: 0, duration: 1, ease: 'power3.out', scrollTrigger: { trigger: el, start: 'top 85%' } });
  });
  const batch = (sel, opts = {}) => ScrollTrigger.batch(sel, {
    start: 'top 85%',
    onEnter: (els) => gsap.fromTo(els, { y: 50, autoAlpha: 0 }, { y: 0, autoAlpha: 1, stagger: 0.1, duration: 0.9, ease: 'power3.out', overwrite: true }),
    ...opts,
  });
  gsap.set('.who-card, .outcomes article, .stack-col, .caveat article, .limits > div', { autoAlpha: 0 });
  batch('.who-card');
  batch('.outcomes article');
  batch('.stack-col');
  batch('.caveat article');
  batch('.limits > div');
  // Outcome counters.
  document.querySelectorAll('.outcomes [data-count]').forEach((el) => {
    const end = +el.dataset.count;
    const o = { v: 0 };
    ScrollTrigger.create({
      trigger: el, start: 'top 85%', once: true,
      onEnter: () => gsap.to(o, { v: end, duration: 1.6, ease: 'power2.out', onUpdate: () => { el.textContent = Math.round(o.v); } }),
    });
  });
  // Detector metric bars.
  const metrics = gsap.timeline({ scrollTrigger: { trigger: '.metrics', start: 'top 75%' } });
  document.querySelectorAll('.metric').forEach((m, i) => {
    const v = +m.dataset.v;
    const val = m.querySelector('.metric-val');
    const o = { v: 0 };
    metrics.fromTo(m.querySelector('.metric-bar i'), { scaleX: 0 }, { scaleX: v, duration: 1.4, ease: 'expo.out' }, i * 0.15)
      .to(o, { v, duration: 1.4, ease: 'expo.out', onUpdate: () => { val.textContent = o.v.toFixed(2); } }, i * 0.15);
  });
  metrics.from('.split span', { scaleX: 0, transformOrigin: 'left center', stagger: 0.1, duration: 0.8, ease: 'power3.out' }, 0.4);
  gsap.from('.model-grid > div:first-child > *', {
    y: 40, autoAlpha: 0, stagger: 0.1, duration: 1, ease: 'power3.out', scrollTrigger: { trigger: '.model', start: 'top 75%' },
  });
}

function nav() {
  const bar = document.querySelector('.nav-progress span');
  gsap.to(bar, { scaleX: 1, ease: 'none', scrollTrigger: { start: 0, end: 'max', scrub: true } });
  const links = [...document.querySelectorAll('.nav-links a')];
  links.forEach((a) => {
    const target = document.querySelector(a.getAttribute('href'));
    ScrollTrigger.create({
      trigger: target, start: 'top 50%', end: 'bottom 50%',
      onToggle: (self) => a.classList.toggle('on', self.isActive),
    });
  });
  // Dark nav over the light-less hero is fine; add a backdrop once the page moves.
  ScrollTrigger.create({ start: 60, end: 'max', onToggle: (self) => document.querySelector('.nav').classList.toggle('solid', self.isActive) });
}

async function main() {
  const m = await manifest();
  const width = pickWidth(m.widths);
  const sections = { a: '#top', b: '#orbit', c: '#buoy' };
  const seqs = {};
  for (const [name, sel] of Object.entries(sections)) {
    const section = document.querySelector(sel);
    seqs[name] = new Sequence(section.querySelector('.seq-canvas'), { name, count: m[name].count, width });
  }
  document.querySelector('.detect-handoff').src = `/frames/b/${width}/b_${String(m.b.count).padStart(4, '0')}.webp`;

  // Show the page as soon as the hero's first frame is ready (or after 4 s, whatever happens first).
  const first = seqs.a.load();
  const bar = document.querySelector('.loader-bar i');
  gsap.to(bar, { scaleX: 0.7, duration: 2.5, ease: 'power2.out' });
  Promise.race([first, new Promise((r) => setTimeout(r, 4000))]).then(() => {
    gsap.to(bar, { scaleX: 1, duration: 0.3 });
    setTimeout(hideLoader, 300);
  });
  first.then(() => { seqs.b.load(); seqs.c.load(); });

  if (reduced) {
    seqs.a.seek(0); seqs.b.seek(1); seqs.c.seek(0.4);
    problem(); await initDetect({ reduced }); initLive({ reduced });
    return;
  }

  sequenceChapter(document.querySelector('#top'), seqs.a, {
    length: 420,
    extra: (tl) => {
      tl.to('.hero-copy', { autoAlpha: 0, y: -60, duration: 0.12, ease: 'power2.in' }, 0.04)
        .to('.scroll-cue', { autoAlpha: 0, duration: 0.05 }, 0.02)
        .to('#top .seq-shade--hero', { opacity: 0.35, duration: 0.15 }, 0.04)
        .to('#top .seq-fade', { opacity: 1, duration: 0.1 }, 0.9);
    },
  });
  problem();
  sequenceChapter(document.querySelector('#orbit'), seqs.b, {
    length: 380,
    extra: (tl) => {
      tl.from('#orbit .seq-canvas', { opacity: 0, duration: 0.04 }, 0);
    },
  });
  // Awaited so its pin is created after the orbit pin and before the ones below it (ScrollTrigger needs page order).
  await initDetect({ reduced });
  solution();
  initLive({ reduced });
  sequenceChapter(document.querySelector('#buoy'), seqs.c, {
    length: 400,
    extra: (tl) => {
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
        parts.forEach((li, j) => li.classList.toggle('on', j === active && t < 0.8));
      });
      tl.fromTo('.buoy-flow span', { autoAlpha: 0, y: 20 }, { autoAlpha: 1, y: 0, stagger: 0.02, duration: 0.04 }, 0.8);
      tl.fromTo('.buoy-spec', { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.05 }, 0.86);
    },
  });
  reveals();
  nav();
  ScrollTrigger.refresh();
}

main();
