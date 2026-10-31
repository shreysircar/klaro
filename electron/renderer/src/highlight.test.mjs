// Run: node --test renderer/src   (from electron/)
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildIndex, findQuote, normalizeText } from './highlight.js';

const page = ['Das Angebot muss bis zum ', '12.03.2026 ', 'eingereicht werden.', 'Die Vergabestelle prüft alle Unter-', 'lagen sorgfältig.'];

test('normalises case, spaces, punctuation, ligatures and accents', () => {
  assert.equal(normalizeText('Das Ange-bot, 12.03.2026!'), 'dasangebot12032026');
  assert.equal(normalizeText('ﬁnal oﬀer'), 'finaloffer');
  assert.equal(normalizeText('prüfen'), normalizeText('prüfen')); // composed vs decomposed umlaut
});

test('finds a passage spanning several items and returns exactly those items', () => {
  const r = findQuote(page, 'Das Angebot muss bis zum 12.03.2026 eingereicht werden.');
  assert.deepEqual(r, { indices: [0, 1, 2], partial: false });
});

test('a quote inside one item only highlights that item', () => {
  assert.deepEqual(findQuote(page, 'eingereicht werden').indices, [2]);
});

test('joins a word hyphenated across a line break', () => {
  const r = findQuote(page, 'Die Vergabestelle prüft alle Unterlagen sorgfältig');
  assert.deepEqual(r.indices, [3, 4]);
});

test('returns null when the passage is not on the page', () => {
  assert.equal(findQuote(page, 'Die Lieferung erfolgt frei Haus innerhalb von zehn Tagen'), null);
});

test('refuses quotes that are too short to be unambiguous', () => {
  assert.equal(findQuote(page, 'Das'), null);
  assert.equal(findQuote(page, ''), null);
  assert.equal(findQuote(page, null), null);
});

test('multi-line quote: whole first, else each line, reporting partial', () => {
  const lines = 'Das Angebot muss bis zum 12.03.2026 eingereicht werden.\nDie Vergabestelle prüft alle Unterlagen sorgfältig.';
  assert.equal(findQuote(page, lines).partial, false); // joined text is contiguous on the page
  const r = findQuote(page, 'Das Angebot muss bis zum 12.03.2026 eingereicht werden.\nEtwas ganz anderes steht hier nicht.');
  assert.deepEqual(r, { indices: [0, 1, 2], partial: true });
});

test('index maps every normalised character back to its item', () => {
  const { text, map } = buildIndex(['ab ', 'c-d']);
  assert.equal(text, 'abcd');
  assert.deepEqual(map, [0, 0, 1, 1]);
});
