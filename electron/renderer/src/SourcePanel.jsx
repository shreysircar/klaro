import { useEffect, useMemo, useRef, useState } from 'react';
import * as pdfjs from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { findQuote } from './highlight.js';
import { drawTranslated } from './translatePage.js';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl; // bundled by Vite: no CDN, no network

const NOT_LOCATED = 'Exact passage not located on this page';

// The passages a bullet was built from, per page: [{ page, segment_ids, quote_en, quote_src }].
// Runs made before `passages` existed carry one passage in the item's own fields.
function passagesOf(item) {
  if (!item) return [];
  if (item.passages) return item.passages;
  return item.quote_en || item.quote_src
    ? [{ page: item.page, segment_ids: item.segment_ids ?? [], quote_en: item.quote_en, quote_src: item.quote_src }]
    : [];
}

// One PDF page, drawn only while it is near the viewport. Highlights its passages once drawn.
function PdfPage({ doc, num, size, width, quotes, expectNote, onLocated, segs, marked }) {
  const boxRef = useRef(null);
  const canvasRef = useRef(null);
  const [near, setNear] = useState(false);
  const [marks, setMarks] = useState({ rects: [], note: null });
  const scale = width / size.w;
  const quoteKey = quotes.join('\u0000') + (segs ? `|${[...marked].join(',')}` : '');

  useEffect(() => {
    const io = new IntersectionObserver(([e]) => setNear(e.isIntersecting), { rootMargin: '800px 0px' });
    io.observe(boxRef.current);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!near || !width) {
      if (canvas) canvas.width = 0; // free the bitmap of pages far from view
      return undefined;
    }
    let alive = true;
    let render;
    (async () => {
      const pg = await doc.getPage(num);
      const dpr = window.devicePixelRatio || 1;
      if (segs) {
        // Translated view: the original page with its text replaced in place by the English.
        const { marks, unplaced } = await drawTranslated(canvas, pg, scale, dpr, segs, marked, (t) => { render = t; });
        if (!alive) return;
        setMarks({ rects: marks, note: unplaced ? `${unplaced} ${unplaced === 1 ? 'passage' : 'passages'} on this page could not be placed and stay in German.` : null });
        if (marks.length) onLocated(num, Math.min(...marks.map((r) => r.top)));
        return;
      }
      const viewport = pg.getViewport({ scale });
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      render = pg.render({
        canvasContext: canvas.getContext('2d'), viewport, transform: dpr === 1 ? null : [dpr, 0, 0, dpr, 0, 0],
      });
      await render.promise;

      let rects = [];
      let note = null;
      if (quotes.length || expectNote) {
        const items = (await pg.getTextContent()).items.filter((i) => 'str' in i);
        const hits = quotes.map((q) => findQuote(items.map((i) => i.str), q));
        const indices = [...new Set(hits.flatMap((h) => h?.indices ?? []))];
        if (!indices.length) note = NOT_LOCATED;
        else if (hits.some((h) => !h || h.partial)) note = 'Part of the passage could not be located on this page.';
        rects = indices.map((i) => {
          const t = pdfjs.Util.transform(viewport.transform, items[i].transform);
          const h = Math.hypot(t[2], t[3]);
          return { left: t[4], top: t[5] - h, width: items[i].width * scale, height: h };
        });
      }
      if (!alive) return;
      setMarks({ rects, note });
      if (rects.length) onLocated(num, Math.min(...rects.map((r) => r.top)));
    })().catch((e) => {
      if (alive && e?.name !== 'RenderingCancelledException') console.error(e);
    });
    return () => {
      alive = false;
      render?.cancel();
    };
  }, [doc, num, near, width, scale, quoteKey, expectNote, segs]);

  return (
    <div ref={boxRef} className="pdf-page" data-page={num} style={{ width, height: size.h * scale }}>
      <canvas ref={canvasRef} style={{ width, height: size.h * scale }} />
      {marks.rects.map((r, i) => <div key={i} className="hl" style={r} />)}
      {marks.note && <p className="page-note">{marks.note}</p>}
    </div>
  );
}

// Loads a PDF's bytes and page sizes. `load` returns the bytes; nothing happens while `enabled` is false.
function usePdf(load, enabled, key) {
  const [pdf, setPdf] = useState({ doc: null, sizes: [], error: null });
  useEffect(() => {
    if (!enabled) return undefined;
    let task;
    let alive = true;
    load()
      .then((bytes) => {
        task = pdfjs.getDocument({ data: bytes, isEvalSupported: false });
        return task.promise;
      })
      .then(async (doc) => {
        const sizes = await Promise.all(Array.from({ length: doc.numPages }, async (_, i) => {
          const v = (await doc.getPage(i + 1)).getViewport({ scale: 1 });
          return { w: v.width, h: v.height };
        }));
        if (alive) setPdf({ doc, sizes, error: null });
      })
      .catch((e) => alive && setPdf({ doc: null, sizes: [], error: e.message }));
    return () => {
      alive = false;
      task?.destroy();
    };
  }, [key, enabled]);
  return pdf;
}

// The run's original PDF, all pages in one scroll, with the clicked bullet's passages highlighted.
// item: the bullet's evidence.json entry or null. focus: { page, key } asks the panel to scroll there.
// lang: 'de' | 'en' | null (null: old run without evidence.json).
export default function SourcePanel({ runId, filename, focus, item, lang }) {
  const scrollRef = useRef(null);
  const [error, setError] = useState(null);
  const [width, setWidth] = useState(0);
  const [tab, setTab] = useState('original');
  const [current, setCurrent] = useState(1);
  const [saved, setSaved] = useState(null);
  const german = lang === 'de';
  const english = tab === 'english';

  const original = usePdf(() => window.klaro.getSource(runId), true, runId);
  const { doc, sizes, error: loadError } = original;
  const [segments, setSegments] = useState(null); // translation segments, by page, for the English view
  const [exporting, setExporting] = useState(null); // pages drawn so far while preparing the download
  useEffect(() => {
    if (!german) return;
    window.klaro.getTranslation(runId).then(
      (all) => {
        const by = new Map();
        for (const seg of all ?? []) by.set(seg.page, [...(by.get(seg.page) ?? []), seg]);
        setSegments(by);
      },
      (e) => setError(e.message),
    );
  }, [runId, german]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(() => setWidth(Math.max(0, el.clientWidth - 16)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [tab, doc]);

  const passages = useMemo(() => passagesOf(item), [item]);
  const quoteField = lang === 'en' ? 'quote_en' : 'quote_src';
  const quotesFor = (page) => passages.filter((p) => p.page === page && p[quoteField]).map((p) => p[quoteField]);
  const marked = useMemo(() => new Set(passages.flatMap((p) => p.segment_ids ?? [])), [passages]);
  const targetPage = (page) => page;

  const pageEl = (page) => scrollRef.current?.querySelector(`[data-page="${page}"]`);
  const scrollToPage = (page, offset = 0) => {
    const el = pageEl(page);
    if (el) scrollRef.current.scrollTo({ top: el.offsetTop + offset - 8, behavior: 'smooth' });
  };
  const turn = (delta) => scrollToPage(current + delta);

  // A bullet or chip was clicked: go to its page (then to its first highlight, once located).
  const goneTo = useRef(null);
  useEffect(() => {
    if (!focus || !doc) return;
    goneTo.current = focus.key;
    requestAnimationFrame(() => scrollToPage(targetPage(focus.page)));
  }, [focus?.key, doc, tab]);

  const onLocated = (page, top) => {
    const target = targetPage(focus?.page);
    if (goneTo.current !== focus?.key || page < target || page > target) return;
    goneTo.current = null; // once per click
    scrollToPage(page, Math.max(0, top - 80));
  };

  const onScroll = () => {
    const el = scrollRef.current;
    let cur = 1;
    for (const p of el.querySelectorAll('[data-page]')) if (p.offsetTop <= el.scrollTop + el.clientHeight * 0.3) cur = Number(p.dataset.page);
    setCurrent(cur);
  };

  // Draws every page with the English in place and saves the result as a PDF of page images.
  const download = async () => {
    try {
      const pages = [];
      for (let n = 1; n <= doc.numPages; n++) {
        setExporting(n);
        const canvas = document.createElement('canvas');
        const pg = await doc.getPage(n);
        await drawTranslated(canvas, pg, 1.6, 1, segments.get(n) ?? [], new Set());
        const blob = await new Promise((done) => canvas.toBlob(done, 'image/jpeg', 0.88));
        pages.push({ jpeg: new Uint8Array(await blob.arrayBuffer()), w: sizes[n - 1].w, h: sizes[n - 1].h });
      }
      const stem = (filename ?? 'translation').replace(/\.pdf$/i, '');
      setSaved(await window.klaro.saveEnglishPdf(`${stem}_english.pdf`, pages));
    } catch (e) {
      setError(e.message);
    } finally {
      setExporting(null);
    }
  };

  const total = sizes.length || null;
  const expectNote = (page) => Boolean(!english && item && !passages.length && item.page === page);
  return (
    <div className="source-panel">
      <div className="source-bar">
        {german && (
          <div className="segmented" role="tablist">
            <button role="tab" aria-selected={!english} onClick={() => setTab('original')}>Original</button>
            <button role="tab" aria-selected={english} onClick={() => setTab('english')}>English</button>
          </div>
        )}
        {english && (
          <button className="secondary" onClick={download} disabled={exporting != null || !segments} title="Save the English version as a PDF">
            {exporting ? `Preparing ${exporting} / ${total}…` : 'Download'}
          </button>
        )}
        <span className="page-nav">
          <button className="icon-button" aria-label="Previous page" disabled={current <= 1} onClick={() => turn(-1)}>‹</button>
          <span className="mono muted">p. {current}{total ? ` / ${total}` : ''}</span>
          <button className="icon-button" aria-label="Next page" disabled={total != null && current >= total} onClick={() => turn(1)}>›</button>
        </span>
      </div>

      {(error || loadError) && <p className="error-box">{error ?? loadError}</p>}
      {english && <p className="passage-note">Machine translation placed over the original layout. Figures and tables are the original's.{saved && ` Saved to ${saved}.`}</p>}

      <div className="pdf-scroll" ref={scrollRef} onScroll={onScroll}>
        {doc && width > 0 && (!english || segments) && sizes.map((size, i) => (
          <PdfPage key={`${tab}-${i + 1}`} doc={doc} num={i + 1} size={size} width={width} quotes={quotesFor(i + 1)}
            expectNote={expectNote(i + 1)} onLocated={onLocated} segs={english ? segments?.get(i + 1) ?? [] : undefined} marked={marked} />
        ))}
      </div>
    </div>
  );
}
