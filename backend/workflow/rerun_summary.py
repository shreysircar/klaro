"""
Re-run stages 4-7 (aggregation, summary agent, evaluation, rendering) from an existing run's saved
stage 3 output, into a NEW run folder. The source run is never modified. Skips the slow stage 3.

    python -m backend.workflow.rerun_summary data/runs/<run_id> [--run-id NEW_ID]
"""

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from backend.config import MODEL_TAG, preflight_error
from backend.evaluation.evaluate_summary import run_evaluation
from backend.llm.executive_summary.agent import run_executive_summary_agent
from backend.llm.executive_summary.aggregator import aggregate_document
from backend.llm.executive_summary.render_summary import render_summary_files

REUSED = ["input", "extracted", "chunks", "extraction"]  # stage 1-3 outputs
REUSED_STAGES = ["pdf_extraction", "chunking", "chunk_analysis"]


def rerun(src: Path, run_id: str | None = None) -> Path:
    extraction = src / "extraction" / "executive_summary_chunks_v5_3.json"
    if not extraction.is_file():
        raise FileNotFoundError(f"No saved stage 3 output at {extraction}")
    src_meta = json.loads((src / "run_metadata.json").read_text(encoding="utf-8"))

    run_id = run_id or f"{src.name}_resummary_{datetime.now():%Y%m%d_%H%M%S}"
    dst = src.parent / run_id
    dst.mkdir()  # refuse to overwrite an existing run
    for d in REUSED:
        shutil.copytree(src / d, dst / d)
    for d in ["aggregation", "summary", "evaluation"]:
        (dst / d).mkdir()

    start = time.time()
    meta = {
        **src_meta,
        "run_id": run_id,
        "copied_file": str(dst / "input" / Path(src_meta["copied_file"]).name),
        "model": MODEL_TAG,
        "timestamp": datetime.now().isoformat(),
        "rerun_of": src.name,
        "stages": {k: {**src_meta["stages"][k], "reused_from": src.name} for k in REUSED_STAGES},
        "status": "in_progress",
    }
    for k in ("error", "failed_stage"):
        meta.pop(k, None)

    def timed(name: str, fn, **info):
        t = time.time()
        result = fn()
        meta["stages"][name] = {"status": "success", "time_seconds": round(time.time() - t, 2), **info}
        return result

    stage = None
    try:
        aggregated = dst / "aggregation" / "executive_summary_aggregated_v1.json"
        summary = dst / "summary" / "executive_summary.json"
        stage = "aggregation"
        timed(stage, lambda: aggregate_document(dst / "extraction" / extraction.name, aggregated), artifact=str(aggregated))
        stage = "summary_agent"
        timed(stage, lambda: run_executive_summary_agent(aggregated, summary), artifact=str(summary))
        stage = "evaluation"
        ev = timed(stage, lambda: run_evaluation(
            aggregated, summary,
            dst / "evaluation" / "baseline_summary_evaluation.json",
            dst / "evaluation" / "baseline_summary_evaluation.md",
        ))
        meta["stages"][stage].update(
            structural_validity=ev["structural_validity"]["passed"],
            grounding_percentage=ev["grounding"]["grounding_percentage"],
            traceability_percentage=ev["traceability"]["traceability_percentage"],
            coverage_percentage=ev["coverage"]["coverage_percentage"],
        )
        stage = "rendering"
        md, html = timed(stage, lambda: render_summary_files(summary, dst / "summary"))
        meta["stages"][stage].update(markdown_path=str(md), html_path=str(html))
        meta["status"] = "completed"
    except Exception as e:
        meta.update(status="failed", error=str(e) or type(e).__name__, failed_stage=stage)
        raise
    finally:
        # Stage 1-3 time is not re-spent; this is the re-run's own runtime.
        meta["total_runtime_seconds"] = round(time.time() - start, 2)
        (dst / "run_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return dst


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-run stages 4-7 of a saved run into a new run folder.")
    parser.add_argument("run_dir", type=str, help="Existing run folder, e.g. data/runs/<run_id>")
    parser.add_argument("--run-id", type=str, default=None, help="Id for the new run folder")
    args = parser.parse_args()

    preflight = preflight_error()
    if preflight:
        print(f"[CRITICAL ERROR] {preflight}", file=sys.stderr)
        sys.exit(1)
    try:
        out = rerun(Path(args.run_dir), args.run_id)
    except Exception as e:
        print(f"[CRITICAL FAILURE] Re-run failed: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"New run: {out}")
