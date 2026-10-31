# Windows test checklist (about 15 minutes)

For a teammate on Windows 10/11 x64. Nobody has run Klaro on Windows yet, so every failure here is useful. Use PowerShell.
Have ready: an English RFP PDF, a German RFP PDF, and a copy of one PDF renamed `Prüfung Größe für Käufer.pdf`.

## Before you start
- Python 3.11, 3.12 or 3.13 (python.org, tick "Add python.exe to PATH"), Node.js 22.12+, [Ollama](https://ollama.com/download).
- [Microsoft Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe) (PyTorch needs it).
- `ollama pull qwen3.5:4b`

## Steps
Tick each box. Where it fails, screenshot the window **and** copy the terminal text.

1. [ ] **Clean checkout.** `git clone <repo>` into a folder with a short path (for example `C:\klaro`), then
   `git switch yasharth/german-integration`. Check `git status` is clean (no CRLF noise).
2. [ ] **Install.** `npm install` finishes without errors.
3. [ ] **Setup + start.** `npm run dev`. Expect lines `[setup 1/5]` to `[setup 5/5]` (first time: several minutes for pip, then a
   ~310 MB model download), then the app window. Note how long each step took.
4. [ ] **Home screen** shows "Ollama connected" and the model name in the bottom line.
5. [ ] **English PDF.** Choose the English PDF. Chip says "English detected". Start. Progress goes through 7 steps; the summary opens.
6. [ ] **German PDF.** Choose the German PDF. Chip says "German detected". Start. Progress shows 8 steps including
   "Translating to English" with a page counter. The summary opens with the banner "Translated from German...".
7. [ ] **Click a bullet.** The right panel jumps to the page and highlights the passage. Click the **English** tab: the page shows
   English text over the original layout, with the same passage highlighted. Scroll through the whole PDF. Click **Download**
   and open the saved PDF.
8. [ ] **Umlaut file name.** Run `Prüfung Größe für Käufer.pdf`. The name displays correctly in the list and the title; the run completes.
9. [ ] **Cancel mid-run.** Start any PDF, wait until "Analyzing sections", click Cancel. Then open Task Manager (Details tab):
   there must be **no** `python.exe` left from `...\klaro\.venv\`. The run disappears from the list.
10. [ ] **Delete a finished run** from the list (trash icon). It disappears; no error appears.
11. [ ] **Missing model.** Close the app. Rename the folder `models\opus-mt-de-en` to `opus-mt-de-en.off`, start with
    `$env:KLARO_SKIP_SETUP=1; npm run dev`, choose the German PDF. The Start button must be replaced by a message that says how to
    fix it (`npm run setup`). Rename the folder back.
12. [ ] **Quit.** Close the window. Task Manager shows no leftover `python.exe` or `electron.exe` from Klaro.
13. [ ] **Non-ASCII user folder** (only if your Windows user name has an accent or space): everything above still works.

## What to send me
- Screenshot of any failure, the terminal output of `npm run dev`, and `%APPDATA%\klaro\logs\backend.log`.
- For a failed run: `data\runs\<run id>\pipeline.log` (the id is shown at the bottom right of the progress screen).
- The timing of setup steps 3 and 4, and `python --version`, `node --version`.
