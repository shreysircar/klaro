import { useEffect, useState } from 'react';
import { deleteRun, health, listRuns, uploadPdf } from './api.js';
import { formatDate, formatDuration } from './format.js';
import { Doc, Lock, Trash, Upload } from './icons.jsx';
import TopBar from './TopBar.jsx';

const REFRESH_MS = 3000;
const STATUS_LABEL = { done: 'Done', running: 'Running', queued: 'Queued', failed: 'Failed', cancelled: 'Cancelled' };

// Newest finished run of each file that has been analyzed more than once. Runs arrive newest first.
function latestIds(runs) {
  const count = {};
  for (const r of runs) count[r.filename] = (count[r.filename] ?? 0) + 1;
  const seen = new Set();
  const ids = new Set();
  for (const r of runs) {
    if (r.status !== 'done' || seen.has(r.filename)) continue;
    if (count[r.filename] > 1) ids.add(r.run_id);
    seen.add(r.filename);
  }
  return ids;
}

function Status({ status }) {
  return (
    <span className={`status ${status}`}>
      {status === 'running' ? <span className="spinner" /> : <span className="dot" />}
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

// Only values the app actually has: Ollama reachability, the model tag, the data folder.
function StatusLine({ h }) {
  if (!h) return null;
  return (
    <footer className="statusline">
      <span className={h.ollama === 'ok' ? 'ok' : 'bad'}>
        <span className="dot" /> Ollama {h.ollama === 'ok' ? 'connected' : 'not reachable'}
      </span>
      <span>Model <b>{h.model_tag}</b></span>
      <span className="statusline-path" title={h.data_dir}>Data <b>{h.data_dir}</b></span>
    </footer>
  );
}

export default function Home({ onOpen }) {
  const [runs, setRuns] = useState(null);
  const [h, setHealth] = useState(null);
  const [listError, setListError] = useState(null);
  const [uploadError, setUploadError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      listRuns()
        .then((r) => alive && (setRuns(r), setListError(null)))
        .catch((e) => alive && setListError(e.message));
    load();
    health().then((x) => alive && setHealth(x), (e) => alive && setListError(e.message));
    const t = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  async function start(name, blob) {
    if (!name.toLowerCase().endsWith('.pdf')) {
      setUploadError(`${name} is not a PDF.`);
      return;
    }
    setBusy(true);
    setUploadError(null);
    try {
      const { run_id } = await uploadPdf(name, blob);
      onOpen({ run_id, status: 'queued' });
    } catch (e) {
      setUploadError(e.message);
      setBusy(false);
    }
  }

  async function choose() {
    const file = await window.klaro.openFile();
    if (file) start(file.name, new Blob([file.data], { type: 'application/pdf' }));
  }

  function drop(e) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) start(file.name, file);
  }

  async function remove(run) {
    const verb = run.status === 'running' || run.status === 'queued' ? 'Cancel' : 'Delete';
    if (!window.confirm(`${verb} the analysis of ${run.filename}?`)) return;
    try {
      await deleteRun(run.run_id);
      setRuns((rs) => rs.filter((r) => r.run_id !== run.run_id));
    } catch (e) {
      setListError(e.message);
    }
  }

  const latest = runs ? latestIds(runs) : new Set();

  return (
    <div className="screen">
      <TopBar>
        <span className="privacy"><Lock /> Everything stays on this computer.</span>
      </TopBar>

      <main className="home">
        <section
          className={`dropzone${dragging ? ' dragging' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={drop}
        >
          <span className="dropzone-icon"><Upload /></span>
          {busy ? (
            <p className="muted"><span className="spinner" /> Uploading…</p>
          ) : (
            <>
              <h1 className="drop-title">Drop an RFP here</h1>
              <p className="caption">Text-based PDF. Scanned PDFs are not supported.</p>
              <button className="primary" onClick={choose}>Choose PDF</button>
            </>
          )}
          {uploadError && <p className="error-box">{uploadError}</p>}
        </section>

        <section className="runs-section">
          <div className="section-head">
            <h2 className="section-title">Past analyses</h2>
            {runs && <span className="mono-label">[{runs.length} {runs.length === 1 ? 'run' : 'runs'}]</span>}
          </div>
          {listError && <p className="error-box">{listError}</p>}
          {runs?.length === 0 && <p className="muted">No analyses yet.</p>}
          {runs?.length > 0 && (
            <table className="runs">
              <thead>
                <tr>
                  <th>File name</th>
                  <th>Pages · chunks</th>
                  <th>Date</th>
                  <th>Duration</th>
                  <th className="right">Status</th>
                  <th aria-label="Remove" />
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.run_id} onClick={() => onOpen(run)} tabIndex={0}
                    onKeyDown={(e) => e.key === 'Enter' && onOpen(run)}>
                    <td>
                      <span className="file">
                        <Doc />
                        <span className="file-name">{run.filename}</span>
                        {latest.has(run.run_id) && <span className="tag">Latest</span>}
                      </span>
                    </td>
                    <td className="mono">
                      {run.pages != null ? `${run.pages} pp · ${run.chunks ?? '–'} ${run.chunks === 1 ? 'chunk' : 'chunks'}` : '–'}
                    </td>
                    <td className="mono">{formatDate(run.created_at)}</td>
                    <td className="mono">{formatDuration(run.duration_s) || '–'}</td>
                    <td className="right"><Status status={run.status} /></td>
                    <td className="right">
                      <button className="icon-button remove" title="Cancel or delete" aria-label={`Remove ${run.filename}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          remove(run);
                        }}>
                        <Trash />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </main>

      <StatusLine h={h} />
    </div>
  );
}
