// HTTP client for the local backend. Every failure throws an Error with the backend's message.
let base;

export async function apiBase() {
  base ??= await window.klaro.getApiBase();
  return base;
}

async function request(path, options) {
  const url = (await apiBase()) + path;
  let res;
  try {
    res = await fetch(url, options);
  } catch {
    throw new Error('Cannot reach the Klaro backend. Restart the app.');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.status === 204 ? null : res.json();
}

const id = (runId) => encodeURIComponent(runId);

export const health = () => request('/health');
export const listRuns = () => request('/runs');
export const getRun = (runId) => request(`/runs/${id(runId)}`);
export const getEvaluation = (runId) => request(`/runs/${id(runId)}/evaluation`);
export const deleteRun = (runId) => request(`/runs/${id(runId)}`, { method: 'DELETE' });

export function uploadPdf(name, blob, sourceLang = 'auto') {
  const form = new FormData();
  form.append('file', blob, name);
  form.append('source_lang', sourceLang);
  return request('/runs', { method: 'POST', body: form });
}
