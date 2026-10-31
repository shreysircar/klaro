// Geometry for laying translated text over the original page. Pure functions (no DOM), tested under node.
import { buildIndex, normalizeText } from './highlight.js';

// Where each translated segment sits on the page: groups of segments that share PDF text items
// (a line often holds the end of one sentence and the start of the next), each with its items.
// strs: the page's text-item strings. segs: [{ id, src, en }] in reading order.
// -> { groups: [{ items: number[], segs: seg[] }], unplaced: seg[] }
export function locateSegments(strs, segs) {
  const { text, map } = buildIndex(strs);
  const claimed = new Set(); // item indices already given to a segment
  const placed = [];
  const unplaced = [];
  let cursor = 0;

  const find = (q, from) => {
    for (let at = text.indexOf(q, from); at !== -1; at = text.indexOf(q, at + 1)) {
      const items = [...new Set(map.slice(at, at + q.length))];
      // Two segments may share an item, but one segment may not take over another's items entirely.
      if (!items.every((i) => claimed.has(i))) return { at, items };
    }
    return null;
  };

  for (const seg of segs) {
    const q = normalizeText(seg.src);
    if (!q) continue;
    let hit = find(q, cursor);
    const sequential = hit !== null;
    if (!hit && q.length >= 8) hit = find(q, 0); // out of order (columns); too short to trust elsewhere
    if (!hit) {
      unplaced.push(seg);
      continue;
    }
    if (sequential) cursor = hit.at + q.length;
    hit.items.forEach((i) => claimed.add(i));
    placed.push({ items: hit.items, seg });
  }

  // Merge segments that share an item into one block.
  const groups = [];
  for (const p of placed) {
    const touching = groups.filter((g) => p.items.some((i) => g.items.has(i)));
    const g = touching[0] ?? { items: new Set(), segs: [] };
    if (!touching.length) groups.push(g);
    for (const other of touching.slice(1)) {
      other.items.forEach((i) => g.items.add(i));
      g.segs.push(...other.segs);
      groups.splice(groups.indexOf(other), 1);
    }
    p.items.forEach((i) => g.items.add(i));
    g.segs.push(p.seg);
  }
  const order = new Map(segs.map((s, i) => [s, i]));
  return {
    groups: groups.map((g) => ({
      items: [...g.items].sort((a, b) => a - b),
      segs: g.segs.sort((a, b) => order.get(a) - order.get(b)),
    })),
    unplaced,
  };
}

// Items (rects with a baseline) -> text lines, top to bottom: items on one baseline become one line.
// rect: { left, width, baseline, h }. -> [{ left, right, baseline, h }]
export function groupLines(rects) {
  const lines = [];
  for (const r of [...rects].sort((a, b) => a.baseline - b.baseline || a.left - b.left)) {
    const line = lines.find((l) => Math.abs(l.baseline - r.baseline) < Math.max(l.h, r.h) * 0.4);
    if (line) {
      line.left = Math.min(line.left, r.left);
      line.right = Math.max(line.right, r.left + r.width);
      line.h = Math.max(line.h, r.h);
    } else {
      lines.push({ left: r.left, right: r.left + r.width, baseline: r.baseline, h: r.h });
    }
  }
  return lines;
}

export const FIT_SCALES = [1, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6];

// Pours words into lines of the given widths, shrinking the font until they fit.
// words: [{ t, seg }]. width(text, scale) -> px. Returns { scale, lines: [[{ t, seg, x, w }]], overflow }.
// If nothing fits, the last line width repeats below the block (overflow: true) rather than dropping text.
export function flow(words, lineWidths, width) {
  for (const [n, scale] of FIT_SCALES.entries()) {
    const last = n === FIT_SCALES.length - 1;
    const lines = [[]];
    let x = 0;
    let fits = true;
    for (const word of words) {
      const w = width(word.t, scale);
      let avail = lineWidths[Math.min(lines.length - 1, lineWidths.length - 1)];
      if (x > 0 && x + width(' ', scale) + w > avail) {
        if (lines.length >= lineWidths.length) {
          fits = false;
          if (!last) break;
        }
        lines.push([]);
        x = 0;
        avail = lineWidths[Math.min(lines.length - 1, lineWidths.length - 1)];
      }
      if (x > 0) x += width(' ', scale);
      lines.at(-1).push({ ...word, x, w });
      x += w;
    }
    if (fits || last) return { scale, lines, overflow: !fits };
  }
  return { scale: 1, lines: [], overflow: false };
}
