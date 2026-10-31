"""HTTP API the Electron shell talks to. Routes and shapes are the API contract in electron/README.md."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from backend import config
from backend.api import jobs

# Injected into summary.html only when the app embeds it (?embed=1): clickable page chips + app styling.
EMBED_SCRIPT = (Path(__file__).parent / "summary_embed.js").read_text(encoding="utf-8")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    jobs.start()
    yield
    jobs.shutdown()


app = FastAPI(title="Klaro", version=config.VERSION, lifespan=lifespan)
# ponytail: dev renderer is served by Vite on localhost; a packaged file:// renderer needs its origin added here.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    reachable, pulled = config.ollama_status()
    return {
        "backend": "ok",
        "ollama": "ok" if reachable else "down",
        "model": "present" if pulled else "missing",
        "model_tag": config.MODEL_TAG,
        "version": config.VERSION,
        "data_dir": str(config.DATA_DIR.resolve()),
    }


@app.post("/runs", status_code=202)
def create_run(file: UploadFile, source_lang: str = Form("auto")) -> dict:
    if source_lang not in ("auto", "en", "de"):
        raise HTTPException(400, "source_lang must be auto, en or de.")
    name = Path(file.filename or "").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")
    if file.file.read(5) != b"%PDF-":
        raise HTTPException(400, f"{name} is not a valid PDF file.")
    file.file.seek(0)
    job = jobs.submit(name, file.file, source_lang)
    return {"run_id": job["run_id"], "status": job["status"]}


@app.get("/runs")
def list_runs() -> list[dict]:
    return [
        {k: r[k] for k in ("run_id", "filename", "status", "created_at", "duration_s", "pages", "chunks")}
        for r in jobs.list_runs()
    ]


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = jobs.get(run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    return run


def _artifact(run_id: str, rel: str, media_type: str) -> FileResponse:
    d = jobs.run_dir(run_id)
    path = d / rel if d else None
    if path is None or not path.is_file():
        raise HTTPException(404, f"{rel} not found for this run.")
    return FileResponse(path, media_type=media_type)


@app.get("/runs/{run_id}/summary")
def get_summary(run_id: str) -> FileResponse:
    return _artifact(run_id, "summary/executive_summary.json", "application/json")


@app.get("/runs/{run_id}/summary.html", response_model=None)
def get_summary_html(run_id: str, embed: bool = False) -> FileResponse | HTMLResponse:
    page = _artifact(run_id, "summary/executive_summary.html", "text/html")
    if not embed:
        return page
    html = Path(page.path).read_text(encoding="utf-8")
    return HTMLResponse(html.replace("</body>", f"<script>{EMBED_SCRIPT}</script>\n</body>", 1))


@app.get("/runs/{run_id}/source.pdf")
def get_source_pdf(run_id: str) -> FileResponse:
    d = jobs.run_dir(run_id)
    pdfs = sorted((d / "input").glob("*.pdf")) if d else []
    if not pdfs:
        raise HTTPException(404, "Source PDF not found for this run.")
    return FileResponse(pdfs[0], media_type="application/pdf")  # no filename: served inline, not as a download


@app.get("/runs/{run_id}/evaluation")
def get_evaluation(run_id: str) -> FileResponse:
    return _artifact(run_id, "evaluation/baseline_summary_evaluation.json", "application/json")


@app.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: str) -> Response:
    try:
        removed = jobs.cancel_or_remove(run_id)
    except OSError as e:  # Windows: a file of the run is still open somewhere
        raise HTTPException(409, f"Could not delete the run's files ({e}). Close anything using them and try again.")
    if not removed:
        raise HTTPException(404, "Run not found.")
    return Response(status_code=204)
