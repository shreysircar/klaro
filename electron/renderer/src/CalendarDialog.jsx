import { useEffect, useMemo, useState } from 'react';
import { buildIcs, googleUrl, icsFileName } from './calendar.js';

const TEXT = {
  en: {
    title: 'Add to calendar', none: 'No dated events were found in this summary.', review: 'Needs review (not exported)',
    assumed: 'assumed DD/MM', download: (n) => `Download .ics (${n})`, close: 'Close', google: 'Google Calendar',
    note: 'Google Calendar opens in your browser and sends this title and date to Google.',
    all: (n) => `Add all to Google Calendar (${n})`,
    importHint: (p) => `Saved to ${p}. In Google Calendar choose Select file from your computer and pick this file.`,
    saved: (p) => `Saved to ${p}`, why: { 'year missing': 'year missing', 'day missing': 'day missing', 'invalid date': 'not a valid date', 'two-digit year': 'two-digit year' },
  },
  de: {
    title: 'Zum Kalender hinzufügen', none: 'In dieser Zusammenfassung wurden keine Termine mit Datum gefunden.', review: 'Zu prüfen (nicht exportiert)',
    assumed: 'angenommen TT/MM', download: (n) => `.ics herunterladen (${n})`, close: 'Schließen', google: 'Google Kalender',
    note: 'Google Kalender öffnet sich im Browser und sendet diesen Titel und das Datum an Google.',
    all: (n) => `Alle in Google Kalender (${n})`,
    importHint: (p) => `Gespeichert unter ${p}. In Google Kalender „Datei auf dem Computer auswählen“ wählen und diese Datei öffnen.`,
    saved: (p) => `Gespeichert unter ${p}`, why: { 'year missing': 'Jahr fehlt', 'day missing': 'Tag fehlt', 'invalid date': 'kein gültiges Datum', 'two-digit year': 'zweistelliges Jahr' },
  },
};

const day = (ymd, lang) => {
  const [y, m, d] = ymd.slice(0, 10).split('-').map(Number);
  return new Intl.DateTimeFormat(lang, { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(y, m - 1, d));
};

// Allday ends are inclusive here, as in the event model.
function when(e, lang) {
  const a = day(e.start, lang);
  if (e.allDay) return e.end === e.start ? a : `${a} – ${day(e.end, lang)}`;
  const t = e.start.slice(11);
  return e.end.slice(11) > t ? `${a}, ${t}–${e.end.slice(11)}` : `${a}, ${t}`;
}

export default function CalendarDialog({ events, review, meta, onPage, onClose }) {
  const T = TEXT[meta.lang] ?? TEXT.en;
  const [picked, setPicked] = useState(() => new Set(events.map((e) => e.id)));
  const [msg, setMsg] = useState(null);
  const chosen = useMemo(() => events.filter((e) => picked.has(e.id)), [events, picked]);

  useEffect(() => {
    const onKey = (ev) => ev.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const toggle = (id) => setPicked((s) => { const n = new Set(s); if (!n.delete(id)) n.add(id); return n; });
  const run = async (fn) => {
    try { setMsg(await fn()); } catch (err) { setMsg({ error: err.message }); }
  };
  const download = () => run(async () => {
    const path = await window.klaro.saveIcs(icsFileName(meta.rfpTitle), buildIcs(chosen, meta));
    return path ? { ok: T.saved(path) } : null;
  });

  // Google's add-event link takes one event; its import page takes the whole .ics file at once.
  const addAll = () => run(async () => {
    const path = await window.klaro.saveIcs(icsFileName(meta.rfpTitle), buildIcs(chosen, meta));
    if (!path) return null;
    await window.klaro.openCalendarLink('https://calendar.google.com/calendar/r/settings/export');
    return { ok: T.importHint(path) };
  });

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={T.title}>
        <h2 className="dialog-title">{T.title}</h2>
        <div className="dialog-body">
          {events.length === 0 && <p className="caption">{T.none}</p>}
          <ul className="cal-list">
            {events.map((e) => (
              <li key={e.id} className="cal-row">
                <input type="checkbox" checked={picked.has(e.id)} onChange={() => toggle(e.id)} aria-label={e.title} />
                <div className="cal-main">
                  <div className="cal-title">{e.title}</div>
                  <div className="mono muted">
                    {when(e, meta.lang)}
                    {e.assumed && <span className="cal-assumed"> · {T.assumed}</span>}
                  </div>
                </div>
                {e.page && <button className="chip-btn" onClick={() => onPage(e.page)}>p. {e.page}</button>}
                <button className="secondary small" onClick={() => run(async () => { await window.klaro.openCalendarLink(googleUrl(e, meta)); return null; })}>{T.google}</button>
              </li>
            ))}
          </ul>
          {review.length > 0 && (
            <>
              <h3 className="block-title">{T.review}</h3>
              <ul className="cal-list">
                {review.map((r, i) => (
                  <li key={i} className="cal-row review">
                    <div className="cal-main">
                      <div className="cal-title">{r.title}</div>
                      <div className="mono muted">{T.why[r.reason] ?? r.reason}</div>
                    </div>
                    {r.page && <button className="chip-btn" onClick={() => onPage(r.page)}>p. {r.page}</button>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {msg?.ok && <p className="caption">{msg.ok}</p>}
          {msg?.error && <p className="error-box">{msg.error}</p>}
        </div>
        <div className="dialog-foot">
          <span className="caption">{T.note}</span>
          <span className="spacer" />
          <button className="secondary" onClick={onClose}>{T.close}</button>
          <button className="secondary" onClick={addAll} disabled={chosen.length === 0}>{T.all(chosen.length)}</button>
          <button className="primary" onClick={download} disabled={chosen.length === 0}>{T.download(chosen.length)}</button>
        </div>
      </div>
    </div>
  );
}
