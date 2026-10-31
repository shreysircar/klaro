// Draws one PDF page with its German text replaced in place by the English translation: figures, tables,
// logos and layout come from the original page; each block of text is painted over with the page's own
// background colour and the English is poured into the same lines. Text it cannot place stays German.
import * as pdfjs from 'pdfjs-dist';
import { flow, groupLines, locateSegments } from './layout.js';

const FONT = 'Helvetica, Arial, sans-serif';
const luminance = ([r, g, b]) => 0.299 * r + 0.587 * g + 0.114 * b;

// Brightest of the four inner corners of a rect: the background, even when text touches the edges.
function backgroundAt(ctx, dpr, rect) {
  const xs = [rect.left + 1, rect.right - 2];
  const ys = [rect.top + 1, rect.bottom - 2];
  let best = [255, 255, 255];
  let bestL = -1;
  for (const x of xs) for (const y of ys) {
    const px = ctx.getImageData(Math.max(0, Math.round(x * dpr)), Math.max(0, Math.round(y * dpr)), 1, 1).data;
    if (luminance(px) > bestL) [best, bestL] = [[px[0], px[1], px[2]], luminance(px)];
  }
  return best;
}

function isBold(pg, fontName) {
  try {
    const f = pg.commonObjs.get(fontName);
    return Boolean(f?.bold) || /bold|black|heavy|semibold/i.test(f?.name ?? '');
  } catch {
    return false; // font object not loaded: draw regular
  }
}

// canvas gets the page at `scale` x `dpr`. segs: this page's translation segments [{ id, src, en }].
// marked: Set of segment ids to highlight. track(task) receives the render task so the caller can cancel it.
// -> { marks: [{ left, top, width, height }] in CSS px, unplaced: number }
export async function drawTranslated(canvas, pg, scale, dpr, segs, marked, track = () => {}) {
  const viewport = pg.getViewport({ scale });
  canvas.width = Math.floor(viewport.width * dpr);
  canvas.height = Math.floor(viewport.height * dpr);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const task = pg.render({ canvasContext: ctx, viewport, transform: dpr === 1 ? null : [dpr, 0, 0, dpr, 0, 0] });
  track(task);
  await task.promise;

  const items = (await pg.getTextContent()).items.filter((i) => 'str' in i);
  const rects = items.map((it) => {
    const t = pdfjs.Util.transform(viewport.transform, it.transform);
    const h = Math.hypot(t[2], t[3]);
    return { left: t[4], baseline: t[5], width: it.width * scale, h, rotated: Math.abs(t[1]) > 0.2 * Math.abs(t[0]) + 0.01, bold: isBold(pg, it.fontName) };
  });
  const { groups, unplaced } = locateSegments(items.map((i) => i.str), segs);

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const blocks = groups.map((g) => {
    const mine = g.items.map((i) => rects[i]).filter((r) => !r.rotated && r.h > 0);
    const lines = groupLines(mine).map((l) => ({
      ...l, top: l.baseline - l.h * 0.95, bottom: l.baseline + l.h * 0.3,
    }));
    return { g, lines, h: Math.max(...mine.map((r) => r.h), 0), bold: mine.some((r) => r.bold) };
  }).filter((b) => b.lines.length);

  // 1. Paint every block's old text out (all blocks first, so a shared line is not painted over twice).
  for (const b of blocks) {
    for (const l of b.lines) {
      l.bg = backgroundAt(ctx, dpr, l);
      ctx.fillStyle = `rgb(${l.bg.join(',')})`;
      ctx.fillRect(l.left - 1, l.top, l.right - l.left + 2, l.bottom - l.top);
    }
  }

  // 2. Pour the English in.
  const marks = [];
  for (const b of blocks) {
    const words = b.g.segs.flatMap((s) => s.en.split(/\s+/).filter(Boolean).map((t) => ({ t, seg: s.id })));
    const font = (size) => `${b.bold ? 'bold ' : ''}${size}px ${FONT}`;
    ctx.font = font(b.h);
    const measure = (t, s) => ctx.measureText(t).width * s;
    const { scale: fit, lines } = flow(words, b.lines.map((l) => l.right - l.left), measure);
    const size = b.h * fit;
    ctx.font = font(size);
    ctx.fillStyle = luminance(b.lines[0].bg) > 128 ? '#000' : '#fff';
    ctx.textBaseline = 'alphabetic';
    const step = b.h * 1.2;
    lines.forEach((row, n) => {
      const l = b.lines[Math.min(n, b.lines.length - 1)];
      const baseline = l.baseline + Math.max(0, n - (b.lines.length - 1)) * step;
      for (const w of row) {
        ctx.fillText(w.t, l.left + w.x, baseline);
        if (marked.has(w.seg)) {
          const m = marks.at(-1);
          const r = { left: l.left + w.x - 1, top: baseline - size, width: w.w + 2, height: size * 1.25 };
          // extend the previous mark when this word follows it on the same line
          if (m && Math.abs(m.top - r.top) < 1 && r.left - (m.left + m.width) < size * 0.6) m.width = r.left + r.width - m.left;
          else marks.push(r);
        }
      }
    });
  }
  return { marks, unplaced: unplaced.length };
}
