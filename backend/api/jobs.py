"""One job at a time (single local model). Each job runs the CLI pipeline as a child process with
--progress-json, so the CLI stays the one code path and cancel is just killing the process."""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from backend.config import DATA_DIR
from backend.translation import translate_summary, translator
from backend.workflow.run_rfp import STAGES, STAGES_WITH_TRANSLATION

RUNS_DIR = DATA_DIR.resolve() / "runs"
UPLOADS_DIR = DATA_DIR.resolve() / "uploads"
REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ("queued", "running")

_jobs: dict[str, dict] = {}
_tjobs: dict[str, dict] = {}  # English -> German summary jobs, by run id; they share the queue and worker with analyses
_TPREFIX = "translate:"
_procs: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()
_queue: queue.Queue[str] = queue.Queue()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _duration(start: str | None, end: str | None) -> float | None:
    if not (start and end):
        return None
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 1)


def _short(filename: str, limit: int = 80) -> str:
    """Windows paths top out at 260 characters and the pipeline names files after the PDF, so cap the stem."""
    p = Path(filename)
    return p.stem[:limit] + p.suffix if len(p.stem) > limit else filename


def _rmtree(path: Path, ignore_errors: bool = False) -> None:
    """rmtree that retries: on Windows a just-killed process, the indexer or antivirus can hold a file for a moment."""
    for attempt in range(6):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 5:
                if ignore_errors:
                    return
                raise
            time.sleep(0.3)


def run_dir(run_id: str) -> Path | None:
    """The run's folder, or None if the id would escape RUNS_DIR."""
    d = (RUNS_DIR / run_id).resolve()
    return d if d.parent == RUNS_DIR and d.name == run_id else None


def submit(filename: str, src: BinaryIO, source_lang: str = "auto") -> dict:
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S_") + uuid4().hex[:6]
    upload = UPLOADS_DIR / run_id / _short(filename)
    upload.parent.mkdir(parents=True)
    with open(upload, "wb") as f:
        shutil.copyfileobj(src, f)
    job = {
        "run_id": run_id, "filename": filename, "status": "queued", "source_lang": source_lang,
        "language": None,  # what the pipeline found: "de" or "en" (set once it reports it)
        "translate_done": 0, "translate_total": 0,  # pages translated so far, German runs only
        "stage": None, "stage_index": 0, "total_stages": len(STAGES),
        "chunks_done": 0, "chunks_total": 0, "error": None,
        "created_at": _now(), "started_at": None, "finished_at": None,
        "pages": None, "chunks": None,
        "stage_seconds": {},  # finished stages only, measured here from event arrival times
        "chunk_avg_s": None,  # average seconds per finished chunk, once 2 are done
    }
    with _lock:
        _jobs[run_id] = job
    _queue.put(run_id)
    return dict(job)


def _kill(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        # A venv's python.exe on Windows is a launcher that runs the real interpreter as a child.
        subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.kill()


def _log_tail(log: Path, lines: int = 8) -> str:
    try:
        return "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError as e:
        return f"(could not read {log}: {e})"


def _run(job: dict) -> None:
    run_id = job["run_id"]
    out_dir = RUNS_DIR / run_id
    log = out_dir / "pipeline.log"
    cmd = [
        # ponytail: dev-only child command; a PyInstaller build needs its own pipeline entry point here.
        sys.executable, "-m", "backend.workflow.run_rfp", str(UPLOADS_DIR / run_id / _short(job["filename"])),
        "--output-dir", str(RUNS_DIR), "--run-id", run_id, "--progress-json",
        "--source-lang", job["source_lang"],
    ]
    with _lock:  # under the lock so a cancel can't slip in between the status check and Popen
        if job["status"] != "queued":
            return
        job.update(status="running", started_at=_now())
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(log, "w", encoding="utf-8") as log_f:
            proc = subprocess.Popen(
                cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=log_f, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
            )
        _procs[run_id] = proc

    error = None
    stage_t0 = chunk_t0 = None

    def close_stage(now: float) -> None:
        if job["stage"] and stage_t0 is not None:
            job["stage_seconds"][job["stage"]] = round(now - stage_t0, 1)

    for line in proc.stdout:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue  # stray non-contract output; the full log is in pipeline.log
        now = time.monotonic()
        with _lock:
            if ev["event"] == "stage":
                close_stage(now)
                stage_t0 = now
                job.update(stage=ev["stage"], stage_index=ev["stage_index"], total_stages=ev["total_stages"])
            elif ev["event"] == "chunk":
                done = ev["chunks_done"]
                if done == 0:
                    chunk_t0 = now
                elif done >= 2 and chunk_t0 is not None:
                    job["chunk_avg_s"] = round((now - chunk_t0) / done, 1)
                job.update(chunks_done=done, chunks_total=ev["chunks_total"], chunks=ev["chunks_total"])
            elif ev["event"] == "language":
                job["language"] = ev["detected"]
            elif ev["event"] == "translate":
                job.update(translate_done=ev["done"], translate_total=ev["total"])
            elif ev["event"] == "document":
                job["pages"] = ev["pages"]
            elif ev["event"] == "error":
                error = ev["error"]
    code = proc.wait()
    if code == 0:
        with _lock:
            close_stage(time.monotonic())

    with _lock:
        _procs.pop(run_id, None)
        job["finished_at"] = _now()
        if job["status"] == "cancelled":
            _rmtree(out_dir, ignore_errors=True)
        elif code == 0:
            job["status"] = "done"
        else:
            job.update(status="failed", error=error or f"Pipeline exited with code {code}.\n{_log_tail(log)}")


def _worker() -> None:
    while True:
        item = _queue.get()
        if item.startswith(_TPREFIX):
            job = _tjobs[item[len(_TPREFIX):]]
            try:
                _run_translation(job)
            except Exception as e:
                with _lock:
                    job.update(status="failed", error=f"Could not run the translation: {e}", finished_at=_now())
            continue
        run_id = item
        job = _jobs[run_id]
        try:
            _run(job)
        except Exception as e:  # never let one job kill the worker thread
            with _lock:
                job.update(status="failed", error=f"Could not run the pipeline: {e}", finished_at=_now())
        _rmtree(UPLOADS_DIR / run_id, ignore_errors=True)  # the pipeline keeps its own copy in input/
        if job["status"] == "done":
            _auto_translate(run_id)


def start() -> None:
    threading.Thread(target=_worker, daemon=True, name="klaro-worker").start()


def shutdown() -> None:
    with _lock:
        for proc in _procs.values():
            _kill(proc)


def _from_disk(d: Path) -> dict | None:
    meta_file = d / "run_metadata.json"
    if not meta_file.is_file():
        return None  # interrupted or still-running run with no metadata yet
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        meta = {"status": "failed", "error": f"Unreadable run_metadata.json: {e}"}
    done = meta.get("status") == "completed"
    stage = meta.get("failed_stage")
    stages = meta.get("stages", {})
    order = STAGES_WITH_TRANSLATION if meta.get("source_language") == "de" else STAGES
    return {
        "run_id": d.name, "filename": Path(meta.get("source_file", d.name)).name,
        "status": "done" if done else "failed",
        "stage": stage, "stage_index": len(order) if done else (order.index(stage) + 1 if stage in order else 0),
        "total_stages": len(order), "language": meta.get("source_language"),
        "translate_done": 0, "translate_total": 0, "chunks_done": 0, "chunks_total": 0,
        "error": meta.get("error"), "created_at": meta.get("timestamp"),
        "started_at": meta.get("timestamp"), "finished_at": None,
        "duration_s": meta.get("total_runtime_seconds"),
        "pages": stages.get("pdf_extraction", {}).get("pages"),
        "chunks": stages.get("chunking", {}).get("chunks"),
        "stage_seconds": {k: v.get("time_seconds") for k, v in stages.items() if k in order},
        "chunk_avg_s": None,
    }


def get(run_id: str) -> dict | None:
    with _lock:
        if run_id in _jobs:
            job = dict(_jobs[run_id])
            job["duration_s"] = _duration(job["started_at"], job["finished_at"])
            return job
    d = run_dir(run_id)
    return _from_disk(d) if d else None


def list_runs() -> list[dict]:
    runs = {d.name: r for d in RUNS_DIR.glob("*") if d.is_dir() and (r := _from_disk(d))}
    with _lock:
        ids = list(_jobs)
    runs.update({i: get(i) for i in ids})
    return sorted(runs.values(), key=lambda r: r["created_at"] or "", reverse=True)


def cancel_or_remove(run_id: str) -> bool:
    """Cancel a queued/running job, else delete a finished run. False if the run doesn't exist."""
    with _lock:
        _cancel_translation_locked(run_id)  # a run being deleted must not keep a child writing into its folder
        job = _jobs.get(run_id)
        if job and job["status"] in ACTIVE:
            job.update(status="cancelled", finished_at=_now())
            if run_id in _procs:
                _kill(_procs[run_id])
            return True
        _jobs.pop(run_id, None)
    d = run_dir(run_id)
    if not (d and d.is_dir()):
        return job is not None
    _rmtree(d)
    return True


# ---- English -> German summary (one job at a time, in the same queue as the analyses) ----

class Busy(Exception):
    """Another job holds the single local model; the message says what to do."""


def _cancel_translation_locked(run_id: str) -> bool:
    job = _tjobs.get(run_id)
    if not job or job["status"] not in ACTIVE:
        return False
    job.update(status="cancelled", finished_at=_now())
    proc = _procs.get(_TPREFIX + run_id)
    if proc:
        _kill(proc)
    return True


def cancel_translation(run_id: str) -> bool:
    with _lock:
        return _cancel_translation_locked(run_id)


def start_translation(run_id: str) -> dict:
    """Queue the German version of a finished run's summary. Raises FileNotFoundError, Busy or RuntimeError."""
    d = run_dir(run_id)
    if not (d and (d / "summary" / translate_summary.SUMMARY).is_file()):
        raise FileNotFoundError("This run has no finished summary to translate.")
    if not translator.installed("en", "de"):
        raise RuntimeError(translator.check("en", "de") or "The English to German model is not installed.")
    with _lock:
        job = _tjobs.get(run_id)
        if job and job["status"] in ACTIVE:
            return dict(job)
        if any(j["status"] in ACTIVE for j in _jobs.values()) or any(j["status"] in ACTIVE for j in _tjobs.values()):
            raise Busy("An analysis or translation is still running. The German version can be made when it finishes.")
        job = {"run_id": run_id, "status": "queued", "done": 0, "total": 0, "error": None, "started_at": None, "finished_at": None}
        _tjobs[run_id] = job
    _queue.put(_TPREFIX + run_id)
    return dict(job)


def _run_translation(job: dict) -> None:
    run_id = job["run_id"]
    d = RUNS_DIR / run_id
    log = d / "translate_de.log"
    cmd = [sys.executable, "-m", "backend.translation.translate_summary", str(d), "--target", "de", "--progress-json"]
    with _lock:
        if job["status"] != "queued":
            return
        job.update(status="running", started_at=_now())
        with open(log, "w", encoding="utf-8") as log_f:
            proc = subprocess.Popen(
                cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=log_f, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
            )
        _procs[_TPREFIX + run_id] = proc
    error = None
    for line in proc.stdout:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        with _lock:
            if ev["event"] == "translate":
                job.update(done=ev["done"], total=ev["total"])
            elif ev["event"] == "error":
                error = ev["error"]
    code = proc.wait()
    with _lock:
        _procs.pop(_TPREFIX + run_id, None)
        job["finished_at"] = _now()
        if job["status"] == "cancelled":
            _rmtree(d / "summary" / ".staging_de", ignore_errors=True)
        elif code == 0:
            job["status"] = "done"
        else:
            job.update(status="failed", error=error or f"The translation exited with code {code}.\n{_log_tail(log)}")


def translation_status(run_id: str) -> dict | None:
    """None if the run does not exist."""
    d = run_dir(run_id)
    if not (d and d.is_dir()):
        return None
    summary = d / "summary"
    available = (summary / "executive_summary_de.json").is_file()
    with _lock:
        job = dict(_tjobs.get(run_id) or {})
        busy = any(j["status"] in ACTIVE for j in _jobs.values()) or any(j["status"] in ACTIVE for j in _tjobs.values())
    status = job.get("status") or ("done" if available else "none")
    if available and status in ("none", "cancelled", "failed"):
        status = "done"
    meta = {}
    if available:
        try:
            meta = json.loads((summary / "executive_summary_de.meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
    segments = None
    estimate = None
    source = summary / translate_summary.SUMMARY
    if not available and source.is_file():
        try:
            segments = translate_summary.count_segments(json.loads(source.read_text(encoding="utf-8-sig")))
            estimate = round(segments * translate_summary.DEFAULT_SECONDS_PER_SEGMENT)
        except (OSError, json.JSONDecodeError):
            pass
    installed = translator.installed("en", "de")
    return {
        "status": status, "available": available, "done": job.get("done", 0), "total": job.get("total", 0),
        "error": job.get("error"), "flagged_bullets": meta.get("flagged_bullets"), "segments": segments,
        "flag_ids": [f["id"] for f in meta.get("flags", [])],
        "estimate_s": estimate, "busy": busy and status not in ACTIVE,
        "model": "present" if installed else "missing",
        "model_fix": None if installed else translator.check("en", "de"),
    }


def _auto_translate(run_id: str) -> None:
    """Queue the German version as soon as an analysis finishes. Never fails the run: if it cannot start (model
    missing, another analysis waiting), the German tab says why and offers the button."""
    try:
        start_translation(run_id)
    except (Busy, RuntimeError, FileNotFoundError) as e:
        print(f"[klaro] German version not started automatically for {run_id}: {e}", file=sys.stderr)
