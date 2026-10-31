# German integration log

Branch `yasharth/german-integration` (cut from `yasharth/electron-app`), with `origin/feature/klaro-german-translation`
merged **uncommitted**. Resume from here in a fresh session. Nothing in this task is committed.

## Phase 0: merge
- Base commit of the merge: `de8fe37`. Shrey's branch has one commit, `ff8c206 translation module`.
- One conflict, `.gitignore`: kept both sides (`data/golden/pdfs/` and `models/`). Not yet `git add`ed.
- Before branching, the project files (`.gitignore`, `docs/`, `scripts/`, `report/`) were committed on `yasharth/electron-app`.
  `data/golden/` and the stray .docx/.jpeg/.zip files are untracked and untouched.

## Phase 1: what Shrey's work was
| Item | Finding |
|---|---|
| Engine | OPUS-MT (`transformers` Marian), `local_files_only=True`, so no network at translation time |
| Direction | English to German only, `models/opus-mt-en-de`, applied to the finished summary JSON field by field |
| `backend/translation/translator.py`, `__init__.py` | empty |
| Tests | none; his render change broke `test_render_summary` (it imported `SECTION_TITLES`) |
| Problems | stage 7 ran the German translation unconditionally (needs torch + model, adds output files); `render_summary` English output differed from before (issuing organization dropped from the Markdown, title text, whitespace) |
| Dependencies | `transformers`, `torch` (+ `sentencepiece` for the Marian tokenizer); none in `requirements.txt` |

## Phase 2: backend
- Direction is now a parameter: `translate_summary.load_translation_model(src, tgt)`, `translate_text(..., src, tgt)`,
  `model_dir(src, tgt)`. Defaults stay `en`, `de`. `transformers` is imported inside the loader, so English runs never need it.
- `config.MODELS_DIR` (`KLARO_MODELS_DIR`, default `<repo>/models`).
- `backend/translation/`: `detect.py` (stopword ratio, CLI prints `{"language","confidence"}`, `unknown` on short or other-language text),
  `segments.py` (sentence/heading segmenter, number-preservation check), `translator.py` (`check()`, batch translate, segment-hash cache
  in `<data dir>/translation_cache/de-en.json`, `--check` CLI), `evidence.py` (Phase 3).
- `run_rfp.py`: `--source-lang auto|en|de` (default `en`), `--german-summary` (Shrey's English-to-German summary, now opt-in).
  `translation` stage after extraction for German runs; events `language`, `translate`; missing model raises with the fix command.
  English pages replace the extracted text in `extracted/<stem>.json`, so chunking, analysis and the page-labelled prompts see English.
- API: `POST /runs` takes optional form field `source_lang` (default `auto`); jobs report `language`, `translate_done`, `translate_total`.
- Verified with a harness that stubs only the three Ollama stages (Ollama was not running): default and `--source-lang en` produce
  identical file trees; `auto` on English adds only `evidence.json` and `source.pdf`; German runs get the 8-stage sequence.
  Missing model gives `{"event":"error","stage":"translation",...}` and exit 1.
- The German fixtures in `backend/evaluation/test_translation.py` are test fixtures (generated PDFs), not demo documents.

## Phase 3: evidence lineage
The pipeline carries **no** link from a summary bullet to its source text: pass A/B facts hold only `{text, page}`, the aggregator merges
facts by normalised text and unions their pages, and the summary agent rewrites them. There is no verbatim quote. A real link would need
a prompt change plus a schema field through four of Nikunj's files, so it was not made. Instead `evidence.json` is built after the summary:
for each bullet, windows of 1-3 consecutive segments on its cited pages are scored by word overlap (5-letter prefixes), and the best
window at or above 0.6 is taken; below that `quote_*` is null. `match_score` is recorded. Ids are `<section>-<index>` in rendered order.
Extra keys beyond the requested schema: top-level `flagged_segments`.
Limit: the match is a best guess of where a paraphrased bullet came from, which is why the threshold is conservative.

## Phase 4/5: Electron
- Preload: `detectLanguage(pathOrFile)`, `checkTranslator()`, `getSource(runId)`, `getEvidence(runId)`. Main confines the last two to
  `<data dir>/runs/<runId>/` and runs the Python helpers with `execFile` (dev only; the packaged build has no helper entry points yet).
- The `<webview>` and its main-process lockdown were removed; `SourcePanel.jsx` draws the PDF with pdf.js (worker bundled via Vite,
  CSP gained `worker-src 'self'` and `font-src 'self' data:`). `highlight.js` is pure and tested with `npm test`.
- Summary iframe: bullets and chips post `klaro:cite {id, page, chip}`; the renderer checks source, origin, id and page range.
- Home: language chip, Auto/German/English selector, translator check with the fix command. Progress: "Translating to English" with a page
  counter. Results: German banner, Original/English tabs. Old runs without `evidence.json` open and jump to the page.

## Files touched in others' code
Shrey: `backend/llm/executive_summary/translate_summary.py` (direction, lazy import, config path),
`backend/llm/executive_summary/render_summary.py` (restored English-identical output, `SECTION_TITLES` alias),
`backend/llm/executive_summary/locales/en.json` (`html_title`), `backend/translation/translator.py` (was empty).
Nikunj's pipeline: `backend/workflow/run_rfp.py` only (flags, translation stage, evidence call; Shrey's stage-7 change moved behind `--german-summary`).

## Setup needed once (German runs)
```
.venv/bin/pip install transformers torch sentencepiece        # approval pending, not yet in requirements.txt
.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('Helsinki-NLP/opus-mt-de-en', local_dir='models/opus-mt-de-en')"
```
The model must end up in `models/opus-mt-de-en/` (or `$KLARO_MODELS_DIR/opus-mt-de-en`); at run time nothing is downloaded.

## Known limits
- Not run with the real model or the real Electron window yet (no model downloaded; Ollama was down). Windows untested.
- Highlights cover whole PDF text items (a line or span), not exact characters. Two-column layouts can break the quote match, which then
  shows "Exact passage not located on this page".
- Number check is a heuristic: times like 14:00 vs 2 p.m., and two-digit years, can be flagged falsely. Nothing is auto-fixed.
- The translation cache stores source and translated text under the data dir, outside the run folder; deleting a run does not clear it.
- pdf.js standard-font data is not bundled; PDFs with unembedded base fonts fall back to system fonts.
- Language `unknown` with an `auto` run fails with a readable message (choose the language manually).

## Setup and Windows hardening (one-command start)

### What changed
- `requirements.txt`: pinned `transformers`, `torch` (CPU wheel), `sentencepiece`, `huggingface_hub`, `safetensors`, `tokenizers`, `numpy`
  (two pins, by Python version: numpy 2.5 has no 3.11 wheels). Wheel availability was checked with `pip install --dry-run --platform`
  for win_amd64 and macosx_14_0_arm64 on Python 3.11 to 3.14; a clean venv installs and imports on Mac.
- Root `package.json`: `postinstall` (installs `electron/`), `setup`, `predev` (runs setup), `dev`, `test`.
- `electron/scripts/`: `setup.mjs` (5 idempotent steps, all spawns are argument arrays with `shell: false`), `env.mjs` (venv paths, UTF-8 env),
  `test.mjs` (node tests, then the Python test modules; `backend/` has no `__init__.py` so unittest discovery cannot walk it).
- `backend/translation/fetch_model.py`: the one-time model download (only the 7 files the PyTorch model needs, about 301 MB, not the TF/Rust copies).
- `backend/config.py` stays the source of truth: setup asks Python for MODELS_DIR, Ollama URL and model tag.
- Hardening: `.gitattributes` (LF), UTF-8 `encoding=` on the last three file writes (tests), stdout/stderr reconfigured to UTF-8 in `run_rfp.py`,
  `PYTHONIOENCODING` for every child, `_rmtree` with retries and a 409 instead of a 500 when a file is locked (`jobs.py`, `app.py`),
  upload file names capped at 80 characters of stem (Windows 260-character paths; the list shows the capped name for runs read back from disk),
  `<userData>/logs/backend.log` written by Electron (previous launch kept as `backend.previous.log`), `torch` DLL failure on Windows turned into a
  readable message in `translator.check()`.
- Docs: README quick start, `docs/windows-test-checklist.md`, CLAUDE.md (network exception, UTF-8 rule, setup flow, dependencies).

### Verified on this Mac (from a clean copy)
Copy of the repo (tracked plus untracked non-ignored files, no `.venv`, `models`, `node_modules`) into a folder named `Übung Ä klaro` (umlauts and a space):
`npm install` 2 s; `npm run setup` 93 s in total (find Python and create venv 1 s, pip 18 s with a warm pip cache, model download 74 s, Ollama check
instant); a second `npm run dev` run of setup took 1 s. `npm run dev` started Electron, the API printed its port, and a German fixture PDF named
`Prüfung Größe für Käufer.pdf` uploaded through the API ran as an 8-stage `auto` run to `done` with real Ollama: language `de`, translation,
`evidence.json`, `source.pdf`, umlaut name intact in `/runs`. Cancelling a second run mid-analysis returned 204, removed the run folder, and left no
`run_rfp` process. 28 Python tests and 14 node tests pass. The throwaway copy was deleted.

### Unverified on Windows (needs a human; see `docs/windows-test-checklist.md`)
- Everything: nothing was run on Windows. The items below are the specific risks reasoned from code.
- `py -3.x` launcher detection and the venv path `.venv\Scripts\python.exe` in `setup.mjs` and `main.js`.
- `pip install` of torch on Windows (about 200 MB wheel; needs the Visual C++ Redistributable, which the app reports if missing).
- `taskkill /pid <pid> /T /F` killing uvicorn and the pipeline child on cancel and quit (no orphan `python.exe`).
- `_rmtree` retries being enough for antivirus/indexer locks; 260-character path limit with a long user-name folder.
- Chromium `printToPDF` of the English download, `showSaveDialog`, and `webUtils.getPathForFile` for dropped files with non-ASCII paths.
- Electron's `loadFile` of the temp export folder when the Windows temp path contains non-ASCII characters.
- LF line endings after checkout (`.gitattributes` only takes effect for files git re-checks-out: run `git add --renormalize .` once).
- Console window flashing: child processes use `windowsHide`, but the Python pipeline spawned by uvicorn is launched by `subprocess.Popen` without `CREATE_NO_WINDOW`; it inherits the hidden parent console, which is believed fine.
