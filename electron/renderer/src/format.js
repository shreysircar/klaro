const time = (d) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });

// "Today, 14:22" / "Yesterday, 17:05" / "22 Feb, 10:14"
export function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(iso).setHours(0, 0, 0, 0)) / 86400000);
  if (days === 0) return `Today, ${time(d)}`;
  if (days === 1) return `Yesterday, ${time(d)}`;
  return `${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}, ${time(d)}`;
}

// "25m 19s" / "42s"
export function formatDuration(seconds) {
  if (seconds == null) return '';
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  return m ? `${m}m ${String(s % 60).padStart(2, '0')}s` : `${s}s`;
}

// "01:18" / "1:02:05"
export function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const pad = (n) => String(n).padStart(2, '0');
  const h = Math.floor(s / 3600);
  return h ? `${h}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}` : `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
}
