import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildIcs, extractEvents, fold, googleUrl, icsFileName, parseBullet } from './calendar.js';

const one = (text) => parseBullet({ text, pages: [3] }, 'important_dates', 'run1');

// [bullet, start, end, allDay, assumed]
const FIXTURES = [
  ['Bid submission deadline: 12 December 2026', '2026-12-12', '2026-12-12', true, null],
  ['Submit by 12 Dec 2026', '2026-12-12', '2026-12-12', true, null],
  ['Deadline December 12, 2026', '2026-12-12', '2026-12-12', true, null],
  ['Deadline: Dec. 12th, 2026', '2026-12-12', '2026-12-12', true, null],
  ['Last date 12th of December 2026', '2026-12-12', '2026-12-12', true, null],
  ['Opening of bids: 12/12/2026', '2026-12-12', '2026-12-12', true, null], // same day and month: not ambiguous
  ['Opening of bids: 12-12-2026', '2026-12-12', '2026-12-12', true, null],
  ['Opening of bids: 12.12.2026', '2026-12-12', '2026-12-12', true, null],
  ['Opening of bids: 2026-12-12', '2026-12-12', '2026-12-12', true, null],
  ['Tender Date: 13.01.2026', '2026-01-13', '2026-01-13', true, null],
  ['Final date for questions: 19.5.2021', '2021-05-19', '2021-05-19', true, null],
  ['Pre-bid meeting on 03/04/2026', '2026-04-03', '2026-04-03', true, 'DD/MM'],
  ['Pre-bid meeting on 5.6.2026', '2026-06-05', '2026-06-05', true, 'DD/MM'],
  ['Meeting on 25/12/2026', '2026-12-25', '2026-12-25', true, null],
  ['Meeting on 12/25/2026', '2026-12-25', '2026-12-25', true, null], // can only be month first
  ['Abgabefrist: 12. Dezember 2026', '2026-12-12', '2026-12-12', true, null],
  ['Angebotsfrist 5. Januar 2027', '2027-01-05', '2027-01-05', true, null],
  ['Termin am 3. Februar 2027', '2027-02-03', '2027-02-03', true, null],
  ['Eröffnung: 1. März 2027', '2027-03-01', '2027-03-01', true, null],
  ['Eröffnung: 1. Maerz 2027', '2027-03-01', '2027-03-01', true, null],
  ['Frist: 8. Mai 2027', '2027-05-08', '2027-05-08', true, null],
  ['Frist: 8. Juni 2027', '2027-06-08', '2027-06-08', true, null],
  ['Frist: 8. Juli 2027', '2027-07-08', '2027-07-08', true, null],
  ['Frist: 8. Oktober 2027', '2027-10-08', '2027-10-08', true, null],
  ['Bindefrist 18. Sept. 2027', '2027-09-18', '2027-09-18', true, null],
  ['Tenders shall be submitted by no later than: 26.5.2021, 12:00', '2021-05-26T12:00', '2021-05-26T13:00', false, null],
  ['Submission 12 December 2026 at 15:00', '2026-12-12T15:00', '2026-12-12T16:00', false, null],
  ['Submission 12 December 2026 at 3:00 PM', '2026-12-12T15:00', '2026-12-12T16:00', false, null],
  ['Submission 12 December 2026 at 3 PM', '2026-12-12T15:00', '2026-12-12T16:00', false, null],
  ['Submission 12 December 2026 at 15:00 hrs', '2026-12-12T15:00', '2026-12-12T16:00', false, null],
  ['Submission 12 December 2026 um 15 Uhr', '2026-12-12T15:00', '2026-12-12T16:00', false, null],
  ['Pre-Bid Meeting Scheduled for at 11.00 AM on 28/01/2026 via Online Link.', '2026-01-28T11:00', '2026-01-28T12:00', false, null],
  ['Submission 12 December 2026 at 12:00 AM', '2026-12-12T00:00', '2026-12-12T01:00', false, null],
  ['Pre-bid meeting 12 December 2026, 10:00 to 12:00', '2026-12-12T10:00', '2026-12-12T12:00', false, null],
  ['Site visit from 12 to 15 December 2026', '2026-12-12', '2026-12-15', true, null],
  ['Site visit 12-15 December 2026', '2026-12-12', '2026-12-15', true, null],
  ['Site visit 12. bis 15. Dezember 2026', '2026-12-12', '2026-12-15', true, null],
  ['Workshop from 28 November 2026 to 2 December 2026', '2026-11-28', '2026-12-02', true, null],
];

for (const [text, start, end, allDay, assumed] of FIXTURES) {
  test(`parses: ${text}`, () => {
    const { events } = one(text);
    assert.equal(events.length, 1, JSON.stringify(events));
    assert.equal(events[0].start, start);
    assert.equal(events[0].end, end);
    assert.equal(events[0].allDay, allDay);
    assert.equal(events[0].assumed, assumed);
    assert.equal(events[0].page, 3);
  });
}

test('a numeric date with both parts 12 or less and different is marked assumed DD/MM', () => {
  assert.equal(one('Opening 03/04/2026').events[0].assumed, 'DD/MM');
  assert.equal(one('Opening 13/04/2026').events[0].assumed, null);
});

test('a missing year goes to review and is never guessed', () => {
  const r = one('Bid submission: 12 December');
  assert.equal(r.events.length, 0);
  assert.deepEqual(r.review.map((x) => x.reason), ['year missing']);
});

test('month and year only goes to review', () => {
  const r = one('Launch until: mid-October 2021');
  assert.equal(r.events.length, 0);
  assert.equal(r.review[0].reason, 'day missing');
});

test('placeholder and impossible dates go to review', () => {
  assert.equal(one('Service until 00.01.1900 (placeholder date in contract).').review[0].reason, 'invalid date');
  assert.equal(one('Deadline 31.02.2026').review[0].reason, 'invalid date');
  assert.equal(one('Deadline 12.12.26').review[0].reason, 'two-digit year');
});

test('durations and undated bullets produce nothing', () => {
  for (const t of ['Contract duration of 24 months', 'Bids remain valid for 180 days from opening', 'Not specified', 'Warranty is Two Year from installation', 'Reply within 5 hours', 'Clause 4 - 12 applies']) {
    const r = one(t);
    assert.deepEqual([r.events.length, r.review.length], [0, 0], t);
  }
});

test('title is the bullet label, else the sentence without the date', () => {
  assert.equal(one('Bid submission deadline: 12 December 2026').events[0].title, 'Bid submission deadline');
  assert.equal(one('The reduced version must be created by 20.7.2021.').events[0].title, 'The reduced version must be created');
});

test('extractEvents: sorts, drops duplicates, uses other sections only for clear events', () => {
  const summary = {
    important_dates: [
      { text: 'Binding period: 18.6.2021', pages: [5] },
      { text: 'Binding period: 18.6.2021', pages: [5] },
      { text: 'Final date for questions: 19.5.2021', pages: [2] },
      { text: 'Maintenance until the end of August 2021', pages: [5] },
    ],
    commercial_requirements: [
      { text: 'Price bid opening on 30 June 2021', pages: [9] },
      { text: 'Prices fixed since 1 January 2020', pages: [9] },
    ],
  };
  const { events, review } = extractEvents(summary, 'r1');
  assert.deepEqual(events.map((e) => e.start), ['2021-05-19', '2021-06-18', '2021-06-30']);
  assert.equal(review.length, 1);
  assert.equal(events[2].section, 'commercial_requirements');
});

// ---- ICS ----

const NOW = new Date('2026-11-01T10:00:00Z');
const meta = { runId: 'run1', rfpTitle: 'Web Portal, Phase 2', issuer: 'Bundesamt für Sicherheit', lang: 'en' };

test('ics: CRLF everywhere, envelope, DTSTAMP, floating time', () => {
  const ev = one('Bid submission deadline: 12 December 2026 at 15:00').events;
  const ics = buildIcs(ev, meta, NOW);
  assert.ok(ics.startsWith('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:'));
  assert.ok(ics.endsWith('END:VCALENDAR\r\n'));
  assert.equal(ics.replace(/\r\n/g, '').includes('\n'), false);
  assert.match(ics, /DTSTAMP:20261101T100000Z/);
  assert.match(ics, /DTSTART:20261212T150000\r\n/);
  assert.match(ics, /DTEND:20261212T160000\r\n/);
  assert.match(ics, /BEGIN:VALARM[^]*TRIGGER:-P1D[^]*END:VALARM/);
});

test('ics: all-day DTEND is exclusive, including across a month end', () => {
  const single = buildIcs(one('Opening: 12 December 2026').events, meta, NOW);
  assert.match(single, /DTSTART;VALUE=DATE:20261212\r\nDTEND;VALUE=DATE:20261213\r\n/);
  const range = buildIcs(one('Site visit 30 to 31 December 2026').events, meta, NOW);
  assert.match(range, /DTSTART;VALUE=DATE:20261230\r\nDTEND;VALUE=DATE:20270101\r\n/);
});

test('ics: no alarm unless the label calls for one', () => {
  assert.equal(buildIcs(one('Kick-off meeting: 12 December 2026').events, meta, NOW).includes('VALARM'), false);
});

test('ics: escapes commas, semicolons, backslashes and newlines', () => {
  const ev = [{ ...one('Deadline: 12 December 2026').events[0], title: 'A, B; C \\ D', sourceText: 'line1\nline2' }];
  const ics = buildIcs(ev, { ...meta, rfpTitle: 'T, U' }, NOW);
  assert.match(ics, /SUMMARY:A\\, B\\; C \\\\ D\r\n/);
  assert.match(ics, /T\\, U\\n/);
  assert.match(ics, /line1\\nline2/);
});

test('ics: lines fold at 75 octets without splitting umlauts, and unfold to the original', () => {
  const long = 'Prüfung der Größe für Käufer und Übergabe '.repeat(8);
  const folded = fold(`SUMMARY:${long}`);
  const lines = folded.split('\r\n');
  assert.ok(lines.length > 2);
  for (const l of lines) assert.ok(new TextEncoder().encode(l).length <= 75, l);
  for (const l of lines.slice(1)) assert.ok(l.startsWith(' '));
  const bytes = new TextEncoder().encode(folded);
  assert.equal(new TextDecoder('utf-8', { fatal: true }).decode(bytes), folded); // valid UTF-8
  assert.equal(folded.replace(/\r\n /g, ''), `SUMMARY:${long}`);
  assert.equal(fold('SHORT'), 'SHORT');
});

test('ics: UID is stable across builds and differs per event and per run', () => {
  const ev = one('Deadline: 12 December 2026').events;
  const uid = (s) => /UID:(\S+)\r\n/.exec(s)[1];
  const a = uid(buildIcs(ev, meta, NOW));
  assert.equal(a, uid(buildIcs(ev, meta, new Date('2027-01-01T00:00:00Z'))));
  assert.notEqual(a, uid(buildIcs(ev, { ...meta, runId: 'other' }, NOW)));
  assert.notEqual(a, uid(buildIcs(one('Deadline: 13 December 2026').events, meta, NOW)));
});

test('ics: German labels in the German view', () => {
  const ics = buildIcs(one('Abgabefrist: 12. Dezember 2026').events, { ...meta, lang: 'de' }, NOW).replace(/\r\n /g, '');
  assert.match(ics, /Seite 3 des Original-PDFs/);
  assert.match(ics, /SUMMARY:Abgabefrist/);
  assert.match(ics, /TRIGGER:-P1D/);
});

test('google url: allowed host, dates, and exclusive all-day end', () => {
  const u = new URL(googleUrl(one('Deadline: 12 December 2026').events[0], meta));
  assert.equal(u.origin, 'https://calendar.google.com');
  assert.equal(u.searchParams.get('dates'), '20261212/20261213');
  const t = new URL(googleUrl(one('Deadline: 12 December 2026 at 15:00').events[0], meta));
  assert.equal(t.searchParams.get('dates'), '20261212T150000/20261212T160000');
});

test('file name comes from the title and is safe', () => {
  assert.equal(icsFileName('Prüfung Größe für Käufer.pdf'), 'Prüfung Größe für Käufer.ics');
  assert.equal(icsFileName('a/b:c*d?.pdf'), 'a b c d.ics');
  assert.equal(icsFileName(''), 'rfp.ics');
});
