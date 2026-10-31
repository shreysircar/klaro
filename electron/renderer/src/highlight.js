// Finds a quoted passage in a PDF page's text items. Pure functions, no DOM or pdf.js, so node can test them.
// Both sides are normalised the same way (case, ligatures, accents, spaces, punctuation, line-break
// hyphens), the quote is searched in the page's joined text, and a map takes each match back to its items.

const LIGATURES = { 'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬃ': 'ffi', 'ﬄ': 'ffl', 'ﬅ': 'st', 'ﬆ': 'st' };
export const MIN_QUOTE_CHARS = 12; // shorter quotes are too ambiguous to highlight

// -> the characters of `str` that count for matching (letters and digits only, lowercase, accents dropped)
function normalizedChars(str) {
  const folded = str.replace(/[ﬀ-ﬆ]/g, (c) => LIGATURES[c]).normalize('NFKD').toLowerCase();
  return Array.from(folded).filter((c) => /[\p{L}\p{N}]/u.test(c));
}

export function normalizeText(str) {
  return normalizedChars(str).join('');
}

// items: the page's text strings in order. -> { text, map } where map[i] is the item index of text[i].
export function buildIndex(items) {
  let text = '';
  const map = [];
  items.forEach((raw, i) => {
    let s = raw;
    // "Verwal-" + "tung": the hyphen belongs to the line break, not to the word.
    if (/[\p{L}]-\s*$/u.test(s) && /^\s*\p{Ll}/u.test(items[i + 1] ?? '')) s = s.replace(/-\s*$/, '');
    for (const c of normalizedChars(s)) {
      text += c;
      for (let k = 0; k < c.length; k++) map.push(i);
    }
  });
  return { text, map };
}

// quote: passage text, lines separated by "\n" (one per segment). Returns null when nothing is found,
// else { indices: sorted item indices to highlight, partial: true if some lines were not found }.
export function findQuote(items, quote) {
  if (!quote) return null;
  const { text, map } = buildIndex(items);
  const whole = normalizeText(quote);
  if (whole.length < MIN_QUOTE_CHARS) return null;

  const at = text.indexOf(whole);
  if (at !== -1) return { indices: unique(map.slice(at, at + whole.length)), partial: false };

  // The lines may come in a different order or be split differently by the PDF: find each on its own.
  const found = [];
  let missing = 0;
  for (const line of quote.split('\n').map(normalizeText).filter(Boolean)) {
    const i = line.length >= MIN_QUOTE_CHARS ? text.indexOf(line) : -1;
    if (i === -1) missing += 1;
    else found.push(...map.slice(i, i + line.length));
  }
  return found.length ? { indices: unique(found), partial: missing > 0 } : null;
}

function unique(list) {
  return [...new Set(list)].sort((a, b) => a - b);
}
