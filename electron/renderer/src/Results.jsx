import { useEffect, useMemo, useRef, useState } from 'react';
import { apiBase, cancelTranslation, getEvaluation, getRun, getSummary, getTranslationStatus, startTranslation } from './api.js';
import CalendarDialog from './CalendarDialog.jsx';
import GermanPanel from './GermanPanel.jsx';
import { extractEvents } from './calendar.js';
import { formatDate } from './format.js';
import { frameCss } from './frameStyle.js';
import { ArrowLeft } from './icons.jsx';
import SourcePanel from './SourcePanel.jsx';
import TopBar from './TopBar.jsx';

function Meter({ label, value, invert = false }) {
  const good = invert ? value <= 10 : value >= 80; // invert: lower is better (duplication)
  return (
    <div className="meter">
      <div className="meter-row">
        <span>{label}</span>
        <span className="mono">{value.toFixed(1)}%</span>
      </div>
      <div className="bar"><div className={good ? 'bar-fill' : 'bar-fill weak'} style={{ width: `${Math.min(value, 100)}%` }} /></div>
    </div>
  );
}

function Quality({ ev, error }) {
  if (error) return <p className="error-box">{error}</p>;
  if (!ev) return <p className="caption"><span className="spinner" /> Loading…</p>;
  return (
    <div className="quality">
      <h3 className="block-title">Structure</h3>
      <p className={ev.structural_validity.passed ? 'ok' : 'bad'}>
        {ev.structural_validity.passed ? 'All 9 sections valid' : 'Summary structure has problems'}
      </p>
      <h3 className="block-title">Scores</h3>
      <Meter label="Grounding" value={ev.grounding.grounding_percentage} />
      <Meter label="Traceability" value={ev.traceability.traceability_percentage} />
      <Meter label="Coverage" value={ev.coverage.coverage_percentage} />
      <Meter label="Duplication" value={ev.duplication.duplication_percentage} invert />
      <h3 className="block-title">Counts</h3>
      <dl className="facts">
        <dt>Unsupported claims</dt>
        <dd className="mono">{ev.hallucination.unsupported_claims_count}</dd>
        <dt>High-importance omissions</dt>
        <dd className="mono">{ev.information_loss.high_importance_omissions_count}</dd>
        <dt>Summary length</dt>
        <dd className="mono">{ev.conciseness.summary_total_words} words</dd>
        <dt>Shorter than the facts by</dt>
        <dd className="mono">{ev.conciseness.compression_percentage}%</dd>
      </dl>
      <p className="caption">
        Scores are word-overlap checks against the extracted facts, not a guarantee of accuracy. Verify against the
        cited pages.
      </p>
    </div>
  );
}

export default function Results({ runId, onBack }) {
  const frameRef = useRef(null);
  const [base, setBase] = useState(null);
  const [run, setRun] = useState(null);
  const [ev, setEv] = useState(null);
  const [error, setError] = useState(null);
  const [evError, setEvError] = useState(null);
  const [tab, setTab] = useState('source');
  const [focus, setFocus] = useState(null); // { page, key }: where the source panel should scroll to
  const [evidence, setEvidence] = useState(null); // evidence.json, or null for runs made before it existed
  const [selected, setSelected] = useState(null); // the clicked bullet's evidence item
  const [lang, setLang] = useState('en'); // language of the summary shown
  const [summary, setSummary] = useState(null); // its JSON, for the calendar export
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [tstatus, setTstatus] = useState(null); // the German version: { status, available, done, total, ... }
  const [tError, setTError] = useState(null);
  const [segments, setSegments] = useState(null); // translation/segments.json of German-source runs
  const [dismissed, setDismissed] = useState({}); // banners the user closed

  useEffect(() => {
    apiBase().then(setBase);
    getRun(runId).then(setRun, (e) => setError(e.message));
    getEvaluation(runId).then(setEv, (e) => setEvError(e.message));
    window.klaro.getEvidence(runId).then(setEvidence, () => setEvidence(null));
    window.klaro.getTranslation(runId).then(setSegments, () => setSegments(null));
  }, [runId]);

  useEffect(() => {
    setSummary(null);
    getSummary(runId, lang).then(setSummary, () => setSummary(null));
  }, [runId, lang]);

  // The German version's state: read once, and polled every second while it is being made.
  const active = tstatus?.status === 'queued' || tstatus?.status === 'running';
  useEffect(() => {
    let alive = true;
    const load = () => getTranslationStatus(runId).then((t) => alive && setTstatus(t), (e) => alive && setTError(e.message));
    load();
    if (!active) return () => { alive = false; };
    const t = setInterval(load, 1000);
    return () => { alive = false; clearInterval(t); };
  }, [runId, active]);

  const germanReady = tstatus?.available === true;
  const showLang = (next) => { setLang(next); setSummary(null); };
  const create = () => { setTError(null); startTranslation(runId).then(() => getTranslationStatus(runId)).then(setTstatus, (e) => setTError(e.message)); };
  const cancel = () => cancelTranslation(runId).then(() => getTranslationStatus(runId)).then(setTstatus, (e) => setTError(e.message));

  // Bullets to mark light red. English view of a German run: built on a segment whose numbers did not survive
  // translation. German view: the bullets the number check flagged.
  const flagIds = useMemo(() => {
    if (lang === 'de') return tstatus?.flag_ids ?? [];
    const bad = new Set((segments ?? []).filter((s) => s.flags.length).map((s) => s.id));
    return (evidence?.items ?? []).filter((i) => i.segment_ids?.some((id) => bad.has(id))).map((i) => i.id);
  }, [lang, tstatus, segments, evidence]);
  const flagRef = useRef(flagIds);
  flagRef.current = flagIds;
  const sendFlags = () => base && frameRef.current?.contentWindow?.postMessage({ type: 'klaro:flags', ids: flagRef.current }, new URL(base).origin);
  useEffect(() => { sendFlags(); }, [flagIds, base]); // eslint-disable-line react-hooks/exhaustive-deps

  const calendar = useMemo(() => (calendarOpen && summary ? extractEvents(summary, runId) : null), [calendarOpen, summary, runId]);

  const openPage = (p) => {
    if (Number.isInteger(p) && p >= 1 && (run?.pages == null || p <= run.pages)) {
      setSelected(null);
      setFocus((f) => ({ page: p, key: (f?.key ?? 0) + 1 }));
      setTab('source');
    }
  };

  // Messages from the summary iframe: accept only our frame, from the API origin, with valid pages.
  useEffect(() => {
    if (!base || !run) return undefined;
    const origin = new URL(base).origin;
    const onMessage = (e) => {
      if (e.source !== frameRef.current?.contentWindow || e.origin !== origin) return;
      if (e.data?.type === 'klaro:calendar') {
        setCalendarOpen(true);
      } else if (e.data?.type === 'klaro:ready') {
        e.source.postMessage({ type: 'klaro:style', css: frameCss }, origin);
        sendFlags();
      } else if (e.data?.type === 'klaro:cite') {
        const { id, page: p, chip } = e.data;
        const item = typeof id === 'string' ? evidence?.items.find((i) => i.id === id) ?? null : null;
        const target = chip || !item?.page ? p : item.page; // a bullet opens the page its passage was found on
        if (Number.isInteger(target) && target >= 1 && (run.pages == null || target <= run.pages)) {
          setSelected(item);
          setFocus((f) => ({ page: target, key: (f?.key ?? 0) + 1 }));
          setTab('source');
        }
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [base, run, evidence]);

  const id = encodeURIComponent(runId);
  const meta = [
    run?.pages != null && `${run.pages} pp`,
    run?.chunks != null && `${run.chunks} chunks`,
    run?.created_at && `Analyzed ${formatDate(run.created_at).replace(/^(Today|Yesterday)/, (m) => m.toLowerCase())}`,
  ].filter(Boolean);

  return (
    <div className="screen">
      <TopBar />
      <div className="subbar">
        <button className="icon-button" onClick={onBack} aria-label="Back"><ArrowLeft /></button>
        <span className="subbar-title">{run?.filename ?? ''}</span>
        <div className="segmented" role="tablist" aria-label="Summary language">
          <button role="tab" aria-selected={lang === 'en'} onClick={() => showLang('en')}>English</button>
          <button role="tab" aria-selected={lang === 'de'} onClick={() => showLang('de')}>Deutsch</button>
        </div>
        <span className="mono muted">{meta.join(' · ')}</span>
        <button className="secondary small" style={{ marginLeft: 'auto' }} disabled={!summary} onClick={() => setCalendarOpen(true)}>
          {lang === 'de' ? 'Alle Termine zum Kalender' : 'Add all dates to calendar'}
        </button>
      </div>
      {error && <p className="error-box">{error}</p>}
      {evidence?.source_lang === 'de' && lang === 'en' && !dismissed.en && (
        <p className={`notice${evidence.flagged_segments ? ' warn' : ''}`}>
          <span>
            Translated from German. English text is machine translation. Page numbers refer to the original PDF.
            {' '}{evidence.flagged_segments} {evidence.flagged_segments === 1 ? 'passage' : 'passages'} flagged for number mismatches
            {flagIds.length > 0 && ' (marked in red)'}.
          </span>
          <button className="notice-close" aria-label="Dismiss" onClick={() => setDismissed((d) => ({ ...d, en: true }))}>×</button>
        </p>
      )}
      {lang === 'de' && germanReady && !dismissed.de && (
        <p className={`notice${tstatus.flagged_bullets ? ' warn' : ''}`} lang="de">
          <span>
            Maschinelle Übersetzung. Die englische Fassung ist maßgeblich.
            {' '}{tstatus.flagged_bullets ?? 0} {tstatus.flagged_bullets === 1 ? 'Punkt' : 'Punkte'} mit abweichenden Zahlen oder Beträgen markiert.
          </span>
          <button className="notice-close" aria-label="Schließen" onClick={() => setDismissed((d) => ({ ...d, de: true }))}>×</button>
        </p>
      )}

      <main className="results">
        <div className="reader">
          {lang === 'de' && !germanReady && <GermanPanel status={tstatus} error={tError} onStart={create} onCancel={cancel} />}
          {base && run && (lang === 'en' || germanReady) && (
            <iframe key={lang} ref={frameRef} title="Executive summary" className="summary-frame"
              src={`${base}/runs/${id}/summary.html?embed=1${lang === 'de' ? '&lang=de' : ''}`} sandbox="allow-scripts allow-same-origin" />
          )}
        </div>

        <aside className="inspector">
          <div className="inspector-bar">
            <div className="segmented" role="tablist">
              <button role="tab" aria-selected={tab === 'source'} onClick={() => setTab('source')}>Source</button>
              <button role="tab" aria-selected={tab === 'quality'} onClick={() => setTab('quality')}>Quality</button>
            </div>
          </div>
          <div className="inspector-body">
            {tab === 'source' && run && (
              <SourcePanel runId={runId} filename={run.filename} focus={focus} item={selected} lang={evidence?.source_lang ?? null} />
            )}
            {tab === 'quality' && <Quality ev={ev} error={evError} />}
          </div>
        </aside>
      </main>
      {calendar && (
        <CalendarDialog events={calendar.events} review={calendar.review} onClose={() => setCalendarOpen(false)}
          onPage={(p) => { setCalendarOpen(false); openPage(p); }}
          meta={{ runId, lang, rfpTitle: (run?.filename ?? '').replace(/\.pdf$/i, ''), issuer: summary?.issuing_organization || null }} />
      )}
    </div>
  );
}
