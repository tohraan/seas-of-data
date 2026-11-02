// Canvas image-sequence scrubber for the Blender renders.
// Frames load coarse-to-fine (every 16th, then 8th, 4th, 2nd, all) so a fast scroll always has a nearby frame
// to show, and the canvas only ever draws frames that have finished decoding.

const pad = (n) => String(n).padStart(4, '0');

export class Sequence {
  constructor(canvas, { name, count, width }) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.name = name;
    this.count = count;
    this.width = width;
    this.frames = new Array(count).fill(null);
    this.current = -1;
    this.wanted = 0;
    // Size from the canvas's own box: it may have no layout yet when this runs, and pins can change it later.
    new ResizeObserver(() => this.resize()).observe(canvas);
  }

  url(i) {
    return `/frames/${this.name}/${this.width}/${this.name}_${pad(i + 1)}.webp`;
  }

  // Resolves once the first frame is on screen; the rest keep streaming in.
  load() {
    // Frame 0 is loaded separately below; the last frame goes early because the next chapter hands off from it.
    const order = [this.count - 1];
    const seen = new Set([0, this.count - 1]);
    for (const step of [16, 8, 4, 2, 1]) {
      for (let i = 0; i < this.count; i += step) {
        if (!seen.has(i)) { seen.add(i); order.push(i); }
      }
    }
    let next = 0;
    const worker = async () => {
      while (next < order.length) {
        const i = order[next++];
        const img = new Image();
        img.decoding = 'async';
        img.src = this.url(i);
        try {
          await img.decode();
          this.frames[i] = img;
          // Redraw if this frame is closer to the wanted one than what is showing.
          if (Math.abs(i - this.wanted) < Math.abs(this.current - this.wanted) || this.current < 0) this.draw(this.wanted);
        } catch { /* missing frame: neighbours cover it */ }
      }
    };
    const first = (async () => {
      const img = new Image();
      img.src = this.url(0);
      await img.decode().catch(() => {});
      this.frames[0] = img.naturalWidth ? img : null;
      this.draw(0);
    })();
    first.then(() => Promise.all([worker(), worker(), worker(), worker()]));
    return first;
  }

  resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const { clientWidth: w, clientHeight: h } = this.canvas;
    if (!w || !h) return;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    const i = this.current;
    this.current = -1;
    if (i >= 0) this.draw(i);
  }

  nearest(i) {
    if (this.frames[i]) return i;
    for (let d = 1; d < this.count; d++) {
      if (this.frames[i - d]) return i - d;
      if (this.frames[i + d]) return i + d;
    }
    return -1;
  }

  // progress in [0, 1]
  seek(progress) {
    this.draw(Math.round(Math.min(Math.max(progress, 0), 1) * (this.count - 1)));
  }

  draw(i) {
    this.wanted = i;
    const j = this.nearest(i);
    if (j < 0 || j === this.current) return;
    this.current = j;
    const img = this.frames[j];
    const { width: cw, height: ch } = this.canvas;
    // Cover fit, anchored to the centre.
    const s = Math.max(cw / img.naturalWidth, ch / img.naturalHeight);
    const w = img.naturalWidth * s;
    const h = img.naturalHeight * s;
    this.ctx.drawImage(img, (cw - w) / 2, (ch - h) / 2, w, h);
  }
}
