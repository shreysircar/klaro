// Shown in place of the summary when the German version has not been made yet (or is being made).
const mins = (s) => (s < 90 ? `about ${Math.max(10, Math.round(s / 10) * 10)} seconds` : `about ${Math.round(s / 60)} minutes`);

export default function GermanPanel({ status, error, onStart, onCancel }) {
  if (!status) return <div className="german-panel"><p className="caption"><span className="spinner" /> Loading…</p></div>;
  const running = status.status === 'queued' || status.status === 'running';
  const pct = status.total ? Math.round((100 * status.done) / status.total) : 0;
  return (
    <div className="german-panel">
      <h2 className="german-title">German version</h2>
      {status.model === 'missing' ? (
        <div className="error-box">
          <strong>The English to German translation model is not installed.</strong>
          <pre>{status.model_fix}</pre>
        </div>
      ) : running ? (
        <>
          <p>{status.status === 'queued' ? 'Waiting for the running job to finish…' : `Translating ${status.done} of ${status.total} passages…`}</p>
          <div className="bar"><div className="bar-fill" style={{ width: `${pct}%` }} /></div>
          <p className="caption">Runs on this computer. Closing this screen does not stop it.</p>
          <button className="secondary" onClick={onCancel}>Cancel</button>
        </>
      ) : (
        <>
          <p>
            Translate this summary into German on this computer. The English version stays the reference; page numbers and
            the cited passages stay the same.
          </p>
          {status.estimate_s != null && (
            <p className="caption">{status.segments} passages, {mins(status.estimate_s)}. The result is saved with this analysis.</p>
          )}
          {status.busy && <p className="caption">Another analysis or translation is running. Wait until it finishes.</p>}
          {status.status === 'failed' && <p className="error-box">{status.error}</p>}
          {status.status === 'cancelled' && <p className="caption">Cancelled.</p>}
          {error && <p className="error-box">{error}</p>}
          <button className="primary" onClick={onStart} disabled={status.busy}>Create German version</button>
        </>
      )}
    </div>
  );
}
