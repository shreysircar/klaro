import { useCallback, useEffect, useState } from 'react';
import { health } from './api.js';
import { Mark } from './icons.jsx';

export default function Setup({ onReady }) {
  const [state, setState] = useState(null); // null while checking
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  const check = useCallback(async () => {
    setState(null);
    setError(null);
    try {
      const h = await health();
      if (h.ollama === 'ok' && h.model === 'present') onReady();
      else setState(h);
    } catch (e) {
      setError(e.message);
    }
  }, [onReady]);

  useEffect(() => {
    check();
  }, [check]);

  const pull = state && `ollama pull ${state.model_tag}`;
  const copy = async () => {
    await navigator.clipboard.writeText(pull);
    setCopied(true);
  };

  return (
    <main className="setup">
      <div className="setup-card">
        <div className="brand">
          <Mark size={28} />
          <span className="brand-name">Klaro</span>
        </div>
        {!state && !error && <p className="caption"><span className="spinner" /> Checking the local model…</p>}
        {error && <p className="error-box">{error}</p>}

        {state?.ollama === 'down' && (
          <>
            <h1 className="headline">Ollama is not running</h1>
            <p>Klaro runs the model on this computer through Ollama. Install it, open the Ollama app, then retry.</p>
            <button className="link" onClick={() => window.klaro.openExternal('https://ollama.com/download')}>
              Download Ollama
            </button>
          </>
        )}

        {state?.ollama === 'ok' && state.model === 'missing' && (
          <>
            <h1 className="headline">The model is not installed</h1>
            <p>Run this in a terminal (a one-time download of a few GB), then retry:</p>
            <div className="command">
              <code>{pull}</code>
              <button className="secondary" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
            </div>
          </>
        )}

        {(state || error) && <button className="primary" onClick={check}>Retry</button>}
      </div>
    </main>
  );
}
