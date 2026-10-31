import { useEffect, useState } from 'react';
import { deleteRun, getRun } from './api.js';
import { formatClock } from './format.js';
import { ArrowLeft, Check, Close } from './icons.jsx';
import TopBar from './TopBar.jsx';

const POLL_MS = 1000;
const STAGES = [
  ['pdf_extraction', 'Extracting text'],
  ['chunking', 'Splitting into sections'],
  ['chunk_analysis', 'Analyzing sections'],
  ['aggregation', 'Merging facts'],
  ['summary_agent', 'Writing the summary'],
  ['evaluation', 'Scoring the summary'],
  ['rendering', 'Rendering the report'],
];

const TRANSLATION = ['translation', 'Translating to English'];
// German runs report 8 stages; the translation step sits right after extraction.
const stagesFor = (run) => (run?.total_stages === STAGES.length + 1 ? [STAGES[0], TRANSLATION, ...STAGES.slice(1)] : STAGES);

function stageState(run, index) {
  const n = index + 1;
  if (run.status === 'done' || n < run.stage_index) return 'done';
  if (n > run.stage_index) return 'pending';
  if (run.status === 'failed') return 'failed';
  if (run.status === 'cancelled') return 'pending';
  return 'active';
}

// Remaining time for the chunk step only, from the measured average per finished chunk.
function remaining(run) {
  if (run.chunk_avg_s == null || run.chunks_done < 2) return null;
  const s = run.chunk_avg_s * (run.chunks_total - run.chunks_done);
  return s < 60 ? 'Less than a minute left in this step' : `About ${Math.round(s / 60)} min left in this step`;
}

function ActiveCard({ run, label, stageKey }) {
  const chunks = stageKey === 'chunk_analysis' && run.chunks_total > 0;
  const translating = stageKey === 'translation' && run.translate_total > 0;
  const pct = chunks ? Math.round((run.chunks_done / run.chunks_total) * 100)
    : translating ? Math.round((run.translate_done / run.translate_total) * 100) : null;
  const eta = chunks ? remaining(run) : null;
  return (
    <li className="step active">
      <div className="active-card">
        <div className="active-head">
          <span className="active-label"><span className="spinner" /> {label}</span>
          {chunks && <span className="mono">Chunk {Math.min(run.chunks_done + 1, run.chunks_total)} of {run.chunks_total}</span>}
          {translating && <span className="mono">Page {Math.min(run.translate_done + 1, run.translate_total)} of {run.translate_total}</span>}
        </div>
        {(chunks || translating) && (
          <>
            <div className="bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <div className="bar-fill" style={{ width: `${pct}%` }} />
            </div>
            <div className="active-foot">
              <span className="caption">{eta ?? ''}</span>
              <span className="mono">{pct}% completed</span>
            </div>
          </>
        )}
        {stageKey === 'translation' && <p className="caption">Translated on this computer. Nothing is sent anywhere.</p>}
        {stageKey === 'summary_agent' && <p className="caption">One long model call. This step can take a few minutes.</p>}
      </div>
    </li>
  );
}

export default function Progress({ runId, onDone, onBack }) {
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);
  const [cancelling, setCancelling] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    let alive = true;
    let timer;
    const poll = async () => {
      try {
        const r = await getRun(runId);
        if (!alive) return;
        setRun(r);
        setError(null);
        setNow(Date.now());
        if (r.status === 'done') return onDone();
        if (r.status === 'failed' || r.status === 'cancelled') return;
      } catch (e) {
        if (!alive) return;
        setError(e.message);
      }
      timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [runId, onDone]);

  async function cancel() {
    setCancelling(true);
    try {
      await deleteRun(runId);
      onBack();
    } catch (e) {
      setError(e.message);
      setCancelling(false);
    }
  }

  const active = run && (run.status === 'queued' || run.status === 'running');
  const elapsed = run?.started_at && active ? (now - new Date(run.started_at).getTime()) / 1000 : run?.duration_s;
  const facts = [run?.pages != null && `${run.pages} pages`, run?.chunks != null && `${run.chunks} sections`].filter(Boolean);

  return (
    <div className="screen">
      <TopBar />
      <div className="subbar">
        <button className="icon-button" onClick={onBack} aria-label="Back"><ArrowLeft /></button>
        <span className="subbar-title">{run?.filename ?? 'Loading…'}</span>
        {elapsed != null && <span className="subbar-meta mono"><span className="dot live" /> Elapsed {formatClock(elapsed)}</span>}
      </div>

      <main className="progress">
        <h1 className="headline">{run?.status === 'failed' ? 'Analysis failed' : 'Analyzing document locally'}</h1>
        {facts.length > 0 && <p className="mono muted">{facts.join(' · ')}</p>}
        {error && <p className="error-box">{error}</p>}
        {run?.status === 'queued' && <p className="caption"><span className="spinner" /> Waiting for the current analysis to finish…</p>}

        {run && (
          <ol className="steps">
            {stagesFor(run).map(([key, label], i) => {
              const state = stageState(run, i);
              if (state === 'active') return <ActiveCard key={key} run={run} label={label} stageKey={key} />;
              const secs = run.stage_seconds?.[key];
              return (
                <li key={key} className={`step ${state}`}>
                  <span className="step-marker" aria-hidden="true">
                    {state === 'done' ? <Check /> : state === 'failed' ? '!' : i + 1}
                  </span>
                  <span className="step-label">{label}</span>
                  <span className="mono muted">{state === 'done' && secs != null ? `${secs}s` : '—'}</span>
                </li>
              );
            })}
          </ol>
        )}

        {run?.status === 'failed' && (
          <div className="error-box">
            <strong>The analysis failed.</strong>
            <pre>{run.error}</pre>
          </div>
        )}
        {run?.status === 'cancelled' && <p className="muted">This analysis was cancelled.</p>}

        <div className="progress-foot">
          {active ? (
            <button className="text-danger" onClick={cancel} disabled={cancelling}>
              <Close /> {cancelling ? 'Cancelling…' : 'Cancel analysis'}
            </button>
          ) : <span />}
          <span className="mono muted">ID: {runId}</span>
        </div>
      </main>
    </div>
  );
}
