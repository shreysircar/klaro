import test from 'node:test';
import assert from 'node:assert/strict';
import { flow, groupLines, locateSegments } from './layout.js';

const seg = (id, src, en = 'x') => ({ id, src, en });

test('segments sharing a text item form one block; others stay apart', () => {
  const strs = ['Das Angebot muss kommen. Danach', 'folgt die Prüfung der Unterlagen.', 'Ganz anderer Absatz hier unten.'];
  const segs = [seg('a', 'Das Angebot muss kommen.'), seg('b', 'Danach folgt die Prüfung der Unterlagen.'), seg('c', 'Ganz anderer Absatz hier unten.')];
  const { groups, unplaced } = locateSegments(strs, segs);
  assert.deepEqual(groups.map((g) => [g.items, g.segs.map((s) => s.id)]), [[[0, 1], ['a', 'b']], [[2], ['c']]]);
  assert.equal(unplaced.length, 0);
});

test('a segment that is not on the page is reported, not guessed', () => {
  const { groups, unplaced } = locateSegments(['Hallo Welt wie geht es dir heute'], [seg('a', 'Etwas völlig anderes steht hier')]);
  assert.equal(groups.length, 0);
  assert.deepEqual(unplaced.map((s) => s.id), ['a']);
});

test('the same sentence twice maps to two different places', () => {
  const strs = ['Siehe Anlage A beachten.', 'Dazwischen steht anderer Text.', 'Siehe Anlage A beachten.'];
  const { groups } = locateSegments(strs, [seg('a', 'Siehe Anlage A beachten.'), seg('b', 'Siehe Anlage A beachten.')]);
  assert.deepEqual(groups.map((g) => g.items), [[0], [2]]);
});

test('items on one baseline become one line', () => {
  const lines = groupLines([
    { left: 50, width: 40, baseline: 100, h: 10 }, { left: 10, width: 30, baseline: 101, h: 10 }, { left: 10, width: 80, baseline: 120, h: 10 },
  ]);
  assert.deepEqual(lines.map((l) => [l.left, l.right, l.baseline]), [[10, 90, 100], [10, 90, 120]]);
});

const w = (t, s) => t.length * 10 * s;

test('flow wraps words into the given line widths', () => {
  const words = 'aaaa bbbb cccc dddd'.split(' ').map((t) => ({ t, seg: 's' }));
  const r = flow(words, [90, 90], w);
  assert.equal(r.scale, 1);
  assert.deepEqual(r.lines.map((l) => l.map((x) => x.t)), [['aaaa', 'bbbb'], ['cccc', 'dddd']]);
});

test('flow shrinks the font before overflowing, and overflows rather than dropping words', () => {
  const words = 'aaaa bbbb cccc dddd'.split(' ').map((t) => ({ t, seg: 's' }));
  const shrunk = flow(words, [75, 75], w);
  assert.ok(shrunk.scale < 1 && !shrunk.overflow);
  const over = flow(words, [30], w);
  assert.ok(over.overflow);
  assert.equal(over.lines.flat().length, 4);
});
