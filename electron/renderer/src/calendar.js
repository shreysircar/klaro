// Calendar export, fully local and pure: dates out of summary bullets -> events -> RFC 5545 text.
// Dates and times are plain strings ('YYYY-MM-DD', 'YYYY-MM-DDTHH:MM'), never Date objects, so no time zone
// can shift them: times are "floating" (15:00 in the RFP is 15:00 in the user's calendar).

const MONTHS = {
  january: 1, januar: 1, jan: 1, janner: 1, 'jänner': 1,
  february: 2, februar: 2, feb: 2,
  march: 3, 'märz': 3, maerz: 3, marz: 3, mar: 3, 'mär': 3, mrz: 3,
  april: 4, apr: 4,
  may: 5, mai: 5,
  june: 6, juni: 6, jun: 6,
  july: 7, juli: 7, jul: 7,
  august: 8, aug: 8,
  september: 9, sept: 9, sep: 9,
  october: 10, oktober: 10, oct: 10, okt: 10,
  november: 11, nov: 11,
  december: 12, dezember: 12, dec: 12, dez: 12,
};
const MON = Object.keys(MONTHS).sort((a, b) => b.length - a.length).join('|');
const NOT_LETTER_BEFORE = '(?<![\\p{L}\\d])';
const NOT_LETTER_AFTER = '(?![\\p{L}])';
const SUFFIX = '(?:st|nd|rd|th)?';
// 'to' style words need spaces around them; a bare hyphen must touch both numbers ("4 - 12 December" is not a range).
const RANGE = '(?:\\s+(?:to|until|till|bis|and|und)\\s+|\\s?[–—]\\s?|-)';

// Order matters only for overlaps: earlier patterns win (the match list is sorted by start, then length).
const DATE_PATTERNS = [
  { kind: 'iso', re: new RegExp('(?<![\\d])(\\d{4})-(\\d{1,2})-(\\d{1,2})(?!\\d)', 'gu') },
  { kind: 'numeric', re: new RegExp('(?<![\\d.\\-/])(\\d{1,2})([./-])(\\d{1,2})\\2(\\d{4}|\\d{2})(?!\\d)', 'gu') },
  // 12 December 2026, 12. Dezember 2026, 12th of Dec, 12 to 15 December 2026
  { kind: 'dmy', re: new RegExp(`${NOT_LETTER_BEFORE}(\\d{1,2})${SUFFIX}\\.?(?:${RANGE}(\\d{1,2})${SUFFIX}\\.?)?\\s*(?:of\\s+)?(${MON})\\.?${NOT_LETTER_AFTER}(?:,?\\s*(20\\d{2})(?!\\d))?`, 'giu') },
  // December 12, 2026 and December 12-15, 2026
  { kind: 'mdy', re: new RegExp(`${NOT_LETTER_BEFORE}(${MON})\\.?\\s+(\\d{1,2})${SUFFIX}(?!\\d)(?:${RANGE}(\\d{1,2})${SUFFIX}(?!\\d))?(?:,?\\s*(20\\d{2})(?!\\d))?`, 'giu') },
  // December 2026: a month with no day
  { kind: 'my', re: new RegExp(`${NOT_LETTER_BEFORE}(${MON})\\.?,?\\s+(20\\d{2})(?!\\d)`, 'giu') },
];

const pad = (n) => String(n).padStart(2, '0');
const key = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;

function valid(y, m, d) {
  if (y < 2000 || y > 2100) return false;
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

export function addDays(ymd, n) {
  const [y, m, d] = ymd.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return key(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
}

const month = (s) => MONTHS[s.toLowerCase().replace(/\.$/, '')];

// -> { start, end, assumed?, problem? } for one regex match; start/end are 'YYYY-MM-DD' (end inclusive).
function readDate(kind, m) {
  if (kind === 'iso') {
    const [y, mo, d] = [+m[1], +m[2], +m[3]];
    return valid(y, mo, d) ? { start: key(y, mo, d), end: key(y, mo, d) } : { problem: 'invalid date' };
  }
  if (kind === 'numeric') {
    let [a, sep, b, y] = [+m[1], m[2], +m[3], m[4]];
    if (y.length === 2) return { problem: 'two-digit year' };
    y = +y;
    let day = a;
    let mo = b;
    let assumed = null;
    if (a <= 12 && b > 12 && sep === '/') [day, mo] = [b, a]; // 12/25/2026 can only be month first
    else if (a <= 12 && b <= 12 && a !== b) assumed = 'DD/MM';
    return valid(y, mo, day) ? { start: key(y, mo, day), end: key(y, mo, day), assumed } : { problem: 'invalid date' };
  }
  if (kind === 'my') return { problem: 'day missing' };
  const [d1, d2, mon, yr] = kind === 'dmy' ? [m[1], m[2], m[3], m[4]] : [m[2], m[3], m[1], m[4]];
  if (!yr) return { problem: 'year missing' };
  const mo = month(mon);
  const [y, a, b] = [+yr, +d1, d2 ? +d2 : +d1];
  return valid(y, mo, a) && valid(y, mo, b) && b >= a ? { start: key(y, mo, a), end: key(y, mo, b) } : { problem: 'invalid date' };
}

function findDates(text) {
  const found = [];
  for (const { kind, re } of DATE_PATTERNS) {
    for (const m of text.matchAll(re)) found.push({ ...readDate(kind, m), from: m.index, to: m.index + m[0].length });
  }
  found.sort((x, y) => x.from - y.from || y.to - x.to);
  const out = [];
  for (const f of found) if (!out.length || f.from >= out[out.length - 1].to) out.push(f);
  return out;
}

// Times in the text with the date spans blanked out. -> [{ at, hm: 'HH:MM', from, to }]
const TIME = /(?<![\d.:/-])(\d{1,2})(?:([:.])(\d{2}))?\s*(a\.?m\.?|p\.?m\.?|hrs?\.?|hours|uhr|h)?(?![\p{L}\d])/giu;
function findTimes(text) {
  const out = [];
  for (const m of text.matchAll(TIME)) {
    let h = +m[1];
    const min = m[3] === undefined ? 0 : +m[3];
    const suf = (m[4] || '').toLowerCase().replace(/\./g, '');
    const ok = suf === 'am' || suf === 'pm' ? h >= 1 && h <= 12
      : suf === 'uhr' ? true
      : suf ? m[3] !== undefined
      : m[2] === ':' && m[3] !== undefined;
    if (!ok || h > 23 || min > 59) continue;
    if (suf === 'pm' && h < 12) h += 12;
    if (suf === 'am' && h === 12) h = 0;
    out.push({ hm: `${pad(h)}:${pad(min)}`, from: m.index, to: m.index + m[0].length });
  }
  return out;
}

// Words that mark a bullet outside the timeline as an event, not just a rule that happens to hold a date.
const EVENT_WORD = /\b(deadline|submission|submit|due|meeting|opening|closing|last date|clarification|pre-bid|bid|tender|award|kick-?off|start|launch|frist|abgabe|einreichung|angebot|termin|er[öo]ffnung|ablauf|bindefrist|stichtag)\b/i;
const ALARM_WORD = /submission|submit|deadline|due|last date|abgabe|frist|einreichung/i;
const TIMELINE = 'important_dates';
const OTHER_SECTIONS = ['commercial_requirements', 'important_conditions'];

const trimEdges = (s) => s.replace(/^[\s,;:.\-–—([]+|[\s,;:.\-–—)\]]+$/g, '');
const TRAILING_LINK = /\b(?:on|at|by|until|till|before|from|to|for|no later than|am|um|bis|vom|ab|den|the|of|scheduled|dated?)\s*$/i;

function titleOf(text, spans) {
  const colon = text.indexOf(':');
  if (colon > 3 && colon <= 70 && !/\d/.test(text.slice(0, colon))) return trimEdges(text.slice(0, colon));
  // Text before the first date reads best ("Pre-Bid Meeting Scheduled for at"); a date at the start leaves the rest.
  const first = Math.min(...spans.map((s) => s.from));
  let t = trimEdges(text.slice(0, first));
  if (t.split(/\s+/).length < 2) {
    t = text;
    for (const s of [...spans].sort((a, b) => b.from - a.from)) t = t.slice(0, s.from) + ' ' + t.slice(s.to);
    t = trimEdges(t.replace(/\s+/g, ' '));
  }
  while (TRAILING_LINK.test(t)) t = trimEdges(t.replace(TRAILING_LINK, ''));
  if (t.length > 90) t = t.slice(0, 90).replace(/\s+\S*$/, '') + '…';
  return t || trimEdges(text).slice(0, 90);
}

// Two cheap 32-bit hashes -> 16 hex chars. Stable across runs and platforms; not cryptographic.
export function hash(str) {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < str.length; i++) {
    const c = str.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 2654435761);
    h2 = Math.imul(h2 ^ c, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (h2 >>> 0).toString(16).padStart(8, '0') + (h1 >>> 0).toString(16).padStart(8, '0');
}

const RANGE_BETWEEN = /^\s*(?:to|until|till|bis|-|–|—)\s*$/i;

// One bullet -> { events, review }. `item` is { text, pages }.
export function parseBullet(item, section, runId = '') {
  const text = String(item?.text ?? '');
  const page = Array.isArray(item?.pages) ? item.pages.find(Number.isInteger) ?? null : Number.isInteger(item?.page) ? item.page : null;
  const dates = findDates(text);
  const good = dates.filter((d) => d.start);
  const review = dates.filter((d) => d.problem).map((d) => ({
    title: titleOf(text, [d]), reason: d.problem, page, section, sourceText: text,
  }));
  if (!good.length) return { events: [], review };

  // "12 December to 15 December 2026": two dates joined only by a range word are one multi-day event.
  const groups = [];
  for (let i = 0; i < good.length; i++) {
    const a = good[i];
    const b = good[i + 1];
    if (b && RANGE_BETWEEN.test(text.slice(a.to, b.from)) && b.start >= a.start) {
      groups.push({ ...a, end: b.end, to: b.to, assumed: a.assumed || b.assumed });
      i++;
    } else {
      groups.push(a);
    }
  }

  const blank = text.replace(/[^]/g, (c, i) => (dates.some((d) => i >= d.from && i < d.to) ? ' ' : c));
  const times = findTimes(blank);
  const title = titleOf(text, [...dates, ...times]);
  const mid = (o) => (o.from + o.to) / 2;
  const owner = (t) => groups.reduce((b, g) => (Math.abs(mid(t) - mid(g)) < Math.abs(mid(t) - mid(b)) ? g : b));
  const events = groups.map((g) => {
    const near = times.filter((t) => owner(t) === g).sort((x, y) => x.from - y.from);
    const multiDay = g.end !== g.start;
    const t0 = !multiDay && near[0];
    const t1 = t0 && near[1] && near[1].from > t0.to && RANGE_BETWEEN.test(text.slice(t0.to, near[1].from)) ? near[1] : null;
    const base = { title, page, section, assumed: g.assumed ?? null, sourceText: text };
    const id = `ev-${hash(`${runId}|${text}|${g.start}`)}`;
    if (!t0) return { id, ...base, start: g.start, end: g.end, allDay: true };
    const start = `${g.start}T${t0.hm}`;
    return { id, ...base, start, end: `${g.start}T${t1 ? t1.hm : plusHour(t0.hm)}`, allDay: false };
  });
  return { events, review };
}

function plusHour(hm) {
  const h = +hm.slice(0, 2) + 1;
  return h > 23 ? '23:59' : `${pad(h)}${hm.slice(2)}`;
}

// The whole summary JSON -> { events (sorted, de-duplicated), review }.
export function extractEvents(summary, runId = '') {
  const events = [];
  const review = [];
  const seen = new Set();
  for (const section of [TIMELINE, ...OTHER_SECTIONS]) {
    for (const item of Array.isArray(summary?.[section]) ? summary[section] : []) {
      const text = typeof item === 'string' ? item : item?.text;
      if (!text || /^not specified/i.test(text.trim())) continue;
      const r = parseBullet(typeof item === 'string' ? { text } : item, section, runId);
      // Outside the timeline a bullet must clearly describe an event, and a half-date there is just noise.
      if (section !== TIMELINE && !EVENT_WORD.test(text)) continue;
      for (const e of r.events) if (!seen.has(e.id)) { seen.add(e.id); events.push(e); }
      if (section === TIMELINE) review.push(...r.review);
    }
  }
  events.sort((a, b) => a.start.localeCompare(b.start));
  return { events, review };
}

// ---- RFC 5545 ----

const esc = (s) => String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r\n|\r|\n/g, '\\n');
const enc = new TextEncoder();

// Lines are at most 75 octets (the continuation's leading space included) and never split a character.
export function fold(line) {
  if (enc.encode(line).length <= 75) return line;
  const out = [];
  let cur = '';
  let bytes = 0;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (bytes + n > 75) {
      out.push(cur);
      cur = ' ';
      bytes = 1;
    }
    cur += ch;
    bytes += n;
  }
  out.push(cur);
  return out.join('\r\n');
}

const compact = (s) => s.replace(/[-:]/g, '');
const stamp = (d) => d.toISOString().replace(/[-:]|\.\d{3}/g, '');

const LABELS = {
  en: { issuer: 'Issuer', section: 'Section', page: (n) => `Page ${n} of the original PDF`, source: 'Source text',
    sections: { important_dates: 'Important dates', commercial_requirements: 'Commercial requirements', important_conditions: 'Important conditions' } },
  de: { issuer: 'Herausgeber', section: 'Abschnitt', page: (n) => `Seite ${n} des Original-PDFs`, source: 'Quelltext',
    sections: { important_dates: 'Wichtige Termine', commercial_requirements: 'Kommerzielle Anforderungen', important_conditions: 'Wichtige Bedingungen' } },
};

// meta: { runId, rfpTitle, issuer?, lang? ('en' | 'de') }. `now` is injectable for tests.
export function buildIcs(events, meta, now = new Date()) {
  const L = LABELS[meta.lang] ?? LABELS.en;
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Klaro//RFP Analyzer//EN', 'CALSCALE:GREGORIAN'];
  for (const e of events) {
    const desc = [
      meta.rfpTitle,
      meta.issuer && `${L.issuer}: ${meta.issuer}`,
      `${L.section}: ${L.sections[e.section] ?? e.section}`,
      e.page && L.page(e.page),
      `${L.source}: ${e.sourceText}`,
    ].filter(Boolean).join('\n');
    lines.push('BEGIN:VEVENT', `UID:${hash(`${meta.runId}|${e.sourceText}|${e.start}`)}@klaro.local`, `DTSTAMP:${stamp(now)}`);
    if (e.allDay) {
      lines.push(`DTSTART;VALUE=DATE:${compact(e.start)}`, `DTEND;VALUE=DATE:${compact(addDays(e.end, 1))}`); // DTEND is exclusive
    } else {
      lines.push(`DTSTART:${compact(e.start)}00`, `DTEND:${compact(e.end)}00`);
    }
    lines.push(`SUMMARY:${esc(e.title)}`, `DESCRIPTION:${esc(desc)}`);
    if (ALARM_WORD.test(e.title)) lines.push('BEGIN:VALARM', 'ACTION:DISPLAY', `DESCRIPTION:${esc(e.title)}`, 'TRIGGER:-P1D', 'END:VALARM');
    lines.push('END:VEVENT');
  }
  lines.push('END:VCALENDAR');
  return lines.map(fold).join('\r\n') + '\r\n';
}

// https://calendar.google.com/calendar/render?action=TEMPLATE... for one event. Opened only on a click.
export function googleUrl(e, meta) {
  const L = LABELS[meta.lang] ?? LABELS.en;
  const dates = e.allDay ? `${compact(e.start)}/${compact(addDays(e.end, 1))}` : `${compact(e.start)}00/${compact(e.end)}00`;
  const details = [meta.rfpTitle, e.page && L.page(e.page)].filter(Boolean).join('\n');
  return `https://calendar.google.com/calendar/render?${new URLSearchParams({ action: 'TEMPLATE', text: e.title, dates, details })}`;
}

// A safe default file name from the RFP title (also re-sanitised in the main process).
export function icsFileName(title) {
  const base = String(title || 'rfp').replace(/\.pdf$/i, '').replace(/[\\/:*?"<>|\u0000-\u001f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80);
  return `${base || 'rfp'}.ics`;
}
