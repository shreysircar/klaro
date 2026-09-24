import { useEffect, useRef, useState } from 'react';
import { apiBase, getEvaluation, getRun } from './api.js';
import { formatDate } from './format.js';
import { frameCss } from './frameStyle.js';
import { ArrowLeft } from './icons.jsx';
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
  const [page, setPage] = useState(1);

  useEffect(() => {
    apiBase().then(setBase);
    getRun(runId).then(setRun, (e) => setError(e.message));
    getEvaluation(runId).then(setEv, (e) => setEvError(e.message));
  }, [runId]);

  // Messages from the summary iframe: accept only our frame, from the API origin, with valid pages.
  useEffect(() => {
    if (!base || !run) return undefined;
    const origin = new URL(base).origin;
    const onMessage = (e) => {
      if (e.source !== frameRef.current?.contentWindow || e.origin !== origin) return;
      if (e.data?.type === 'klaro:ready') {
        e.source.postMessage({ type: 'klaro:style', css: frameCss }, origin);
      } else if (e.data?.type === 'klaro:page') {
        const p = e.data.page;
        if (Number.isInteger(p) && p >= 1 && (run.pages == null || p <= run.pages)) {
          setPage(p);
          setTab('source');
        }
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [base, run]);

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
        <span className="mono muted">{meta.join(' · ')}</span>
      </div>
      {error && <p className="error-box">{error}</p>}

      <main className="results">
        <div className="reader">
          {base && run && (
            <iframe ref={frameRef} title="Executive summary" className="summary-frame"
              src={`${base}/runs/${id}/summary.html?embed=1`} sandbox="allow-scripts allow-same-origin" />
          )}
        </div>

        <aside className="inspector">
          <div className="inspector-bar">
            <div className="segmented" role="tablist">
              <button role="tab" aria-selected={tab === 'source'} onClick={() => setTab('source')}>Source</button>
              <button role="tab" aria-selected={tab === 'quality'} onClick={() => setTab('quality')}>Quality</button>
            </div>
            {tab === 'source' && <span className="mono muted">Opened at p. {page}</span>}
          </div>
          <div className="inspector-body">
            {tab === 'source' && base && (
              // Chromium's PDF viewer; plugins are enabled for this webview only (see main.js). It ignores
              // hash-only changes, so ?p= makes each jump a real load that honours #page.
              <webview className="pdf" src={`${base}/runs/${id}/source.pdf?p=${page}#page=${page}&navpanes=0`} plugins="true" />
            )}
            {tab === 'quality' && <Quality ev={ev} error={evError} />}
          </div>
        </aside>
      </main>
    </div>
  );
}
