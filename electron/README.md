# Klaro desktop app

Electron shell for the Klaro pipeline. Electron starts a local Python API (`backend/api`), and the API
runs `backend/workflow/run_rfp.py` as a child process for each PDF. Nothing leaves the machine: the
renderer talks only to `127.0.0.1`, and the API talks only to Ollama on `127.0.0.1:11434`.

```
electron/main.js        main process: spawns the API, waits for /health, opens the window
electron/preload.js     getApiBase(), openFile(), openExternal(), detectLanguage(), checkTranslator(), getSource(), getEvidence()
electron/renderer/      Vite + React UI (Setup, Home, Progress, Results)
electron/scripts/dev.mjs  `npm run dev`: Vite dev server + Electron
backend/api/            FastAPI server, one job at a time
```

## Prerequisites

- **Python 3.11+** (3.12 is tested)
- **Node.js 22.12+** (Electron 44 and Vite 8 need it)
- **Ollama**, from https://ollama.com/download, running in the background

## Setup from a fresh clone

Run each step from the repo root unless it says otherwise.

### macOS

```bash
python3.12 -m venv .venv
```
```bash
.venv/bin/pip install -r requirements.txt
```
```bash
ollama pull qwen3.5:4b
```
```bash
cd electron && npm install
```

### Windows (PowerShell)

```powershell
py -3.12 -m venv .venv
```
```powershell
.venv\Scripts\pip install -r requirements.txt
```
```powershell
ollama pull qwen3.5:4b
```
```powershell
cd electron; npm install
```

The first `npm run dev` downloads the Electron binary (about 100 MB) if `npm install` didn't.

## Run

From `electron/`:

```bash
npm run dev
```

This starts Vite on a free port, then Electron, which starts the Python API on a free port
(printed as `KLARO_PORT=<n>`). Quitting the app stops everything. To attach Chrome DevTools, pass
Electron flags through: `npm run dev -- --remote-debugging-port=9223`.

Without Vite: `npm run build` then `npm start` loads the built renderer from `electron/dist/`.

## Results screen

The summary on the left is the pipeline's own `summary.html`, loaded from the API with `?embed=1`.
The API adds a small script (`backend/api/summary_embed.js`) that makes each page chip clickable, and
the app sends it a stylesheet built from `renderer/src/tokens.css`. The right panel shows the source
PDF drawn with pdf.js (clicking a bullet highlights its passage; German runs also get an English tab), or the
evaluation scores. German RFPs need the OPUS-MT model once: see `docs/german-integration-log.md`. Tests:
`npm test` (highlight matcher) and `python -m unittest backend.evaluation.test_translation`.

Design tokens live only in `renderer/src/tokens.css` (taken from the Google Stitch design exports). Fonts are bundled from
`@fontsource`, so the app works offline.

## API contract

Electron only ever talks to these. Keep them stable.

| Method | Route | Returns |
|---|---|---|
| GET | `/health` | `{backend: ok, ollama: ok/down, model: present/missing, model_tag, version, data_dir}` |
| POST | `/runs` | multipart PDF upload, returns `{run_id, status: queued}` |
| GET | `/runs` | list of runs, newest first: `run_id, filename, status, created_at, duration_s, pages, chunks` |
| GET | `/runs/{id}` | `{status, stage, stage_index, total_stages, chunks_done, chunks_total, error, started_at, finished_at, pages, chunks, stage_seconds, chunk_avg_s}` |
| GET | `/runs/{id}/summary` | the executive summary JSON |
| GET | `/runs/{id}/summary.html` | the rendered HTML; `?embed=1` adds the app's chip script (the file on disk is unchanged) |
| GET | `/runs/{id}/source.pdf` | the run's input PDF, inline |
| GET | `/runs/{id}/evaluation` | the evaluation JSON |
| DELETE | `/runs/{id}` | cancel if running, else remove |

Status values: `queued`, `running`, `done`, `failed`, `cancelled`.
One job runs at a time (single local model). Others wait in a queue.

## Progress contract (`run_rfp.py --progress-json`)

The API runs each job as `python -m backend.workflow.run_rfp <pdf> --output-dir <DATA_DIR>/runs
--run-id <id> --progress-json`. With the flag, stdout carries only JSON lines (human output goes to
stderr):

```
{"event": "stage", "stage": "chunk_analysis", "stage_index": 3, "total_stages": 7}
{"event": "document", "pages": 54}                             # once, after text extraction
{"event": "chunk", "chunks_done": 3, "chunks_total": 11}      # before each chunk, and once at the end
{"event": "done", "run_dir": "..."}
{"event": "error", "stage": "chunk_analysis" | null, "error": "readable message"}
```

Stages in order: `pdf_extraction`, `chunking`, `chunk_analysis`, `aggregation`, `summary_agent`,
`evaluation`, `rendering`. Exit code 0 on success, 1 on failure.

## Where things go

Runs are written to `<KLARO_DATA_DIR>/runs/<run_id>/`, which is `data/runs/` in the repo when
running in dev. Each run folder also holds `pipeline.log` with the pipeline's full output: read it
first when a run fails. Runs made with the CLI in the same data dir show up in the app too.

## Settings

All come from `backend/config.py`, and you can override them with environment variables before
`npm run dev`:

| Env var | Default | |
|---|---|---|
| `KLARO_MODEL` | `qwen3.5:4b` | Ollama model tag |
| `KLARO_OLLAMA_URL` | `http://127.0.0.1:11434` | |
| `KLARO_DATA_DIR` | `./data` | Electron sets it to the OS user-data dir in packaged builds |
| `KLARO_LLM_TIMEOUT` | `300` | seconds per model call. A call that times out counts as a failed chunk |
| `KLARO_PORT` | `0` | API port, where 0 means any free port |

## Checks

```bash
.venv/bin/python -m unittest backend/evaluation/test_workflow.py backend/evaluation/test_render_summary.py backend/evaluation/test_chunk_failures.py
```

## Not done yet

- Packaging: there is no PyInstaller build or electron-builder config yet. `main.js` already branches
  on `app.isPackaged` and expects the backend binary at `resources/klaro-backend/`.
- A 4B model on a laptop takes about 1 minute per model call. A 40-page RFP (about 11 chunks, 2 calls
  each, plus the summary) takes roughly 25 to 40 minutes.
