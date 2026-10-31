"""
Klaro — Reproducible Baseline RFP Workflow v1

End-to-end orchestration CLI for running the baseline Executive Summary pipeline on any RFP PDF.
Pipeline Flow:
RFP PDF -> PDF Extraction -> Chunking -> Two-Pass Chunk Analysis -> Aggregator -> Executive Summary Agent -> Evaluation -> Markdown/HTML Renderer
"""

import argparse
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from backend.config import DATA_DIR, MODEL_TAG, preflight_error

# Import existing pipeline components
from backend.documents.pdf_extractor import extract_pdf_pages
from backend.documents.chunker import create_chunks
from backend.llm.executive_summary.chunk_analyzer import process_chunks_file
from backend.llm.executive_summary.aggregator import aggregate_document
from backend.llm.executive_summary.agent import run_executive_summary_agent
from backend.evaluation.evaluate_summary import run_evaluation
from backend.llm.executive_summary.render_summary import render_summary_files
from backend.translation.detect import detect_pages

STAGES = ["pdf_extraction", "chunking", "chunk_analysis", "aggregation", "summary_agent", "evaluation", "rendering"]
# German runs get a translation stage right after extraction.
STAGES_WITH_TRANSLATION = STAGES[:1] + ["translation"] + STAGES[1:]

# Set by --progress-json: one JSON object per line on this stream (see the progress contract in electron/README.md).
_progress_stream = None
_current_stage: str | None = None
_stages = STAGES


def emit(event: str, **fields) -> None:
    if _progress_stream is not None:
        _progress_stream.write(json.dumps({"event": event, **fields}) + "\n")
        _progress_stream.flush()


def emit_stage(stage: str) -> None:
    global _current_stage
    _current_stage = stage
    emit("stage", stage=stage, stage_index=_stages.index(stage) + 1, total_stages=len(_stages))


def calculate_file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def _translate(run_dir: Path, pages: list[dict], metadata: dict):
    """German pages -> English pages (stage `translation`). Returns (segments, pages_en)."""
    from backend.translation.translator import check, translate_pages

    emit_stage("translation")
    st_start = time.time()
    error = check("de", "en")
    if error:
        raise RuntimeError(error)  # never analyse German text with the English prompts
    segments, pages_en = translate_pages(
        pages, "de", "en", on_page=lambda done, total: emit("translate", done=done, total=total)
    )
    out = run_dir / "translation"
    out.mkdir(exist_ok=True)
    (out / "segments.json").write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "pages_en.json").write_text(json.dumps(pages_en, ensure_ascii=False, indent=2), encoding="utf-8")
    flagged = sum(bool(s["flags"]) for s in segments)
    metadata["stages"]["translation"] = {
        "status": "success", "time_seconds": round(time.time() - st_start, 2),
        "segments": len(segments), "flagged_segments": flagged, "artifact": str(out / "segments.json"),
    }
    print(f"Translated {len(segments)} segments de->en; {flagged} flagged for number mismatches.")
    return segments, pages_en


def run_pipeline(
    pdf_path: Path, output_dir: Path | None = None, run_id: str | None = None,
    source_lang: str = "en", german_summary: bool = False,
) -> int:
    global _stages
    start_time = time.time()
    _stages = STAGES_WITH_TRANSLATION if source_lang == "de" else STAGES

    if not pdf_path.exists():
        print(f"[CRITICAL ERROR] Input RFP file not found: {pdf_path}", file=sys.stderr)
        emit("error", stage=None, error=f"Input RFP file not found: {pdf_path}")
        return 1

    if pdf_path.suffix.lower() != ".pdf":
        print(f"[CRITICAL ERROR] Input file is not a PDF: {pdf_path}", file=sys.stderr)
        emit("error", stage=None, error=f"Input file is not a PDF: {pdf_path}")
        return 1

    # 1. Setup Run Directories
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    if run_id is None:
        run_id = f"run_{pdf_path.stem}_{timestamp_str}"

    if output_dir is None:
        run_dir = DATA_DIR / "runs" / run_id
    else:
        run_dir = output_dir / run_id

    dir_input = run_dir / "input"
    dir_extracted = run_dir / "extracted"
    dir_chunks = run_dir / "chunks"
    dir_extraction = run_dir / "extraction"
    dir_aggregation = run_dir / "aggregation"
    dir_summary = run_dir / "summary"
    dir_evaluation = run_dir / "evaluation"

    for d in [dir_input, dir_extracted, dir_chunks, dir_extraction, dir_aggregation, dir_summary, dir_evaluation]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy source PDF to input directory
    copied_pdf = dir_input / pdf_path.name
    shutil.copy2(pdf_path, copied_pdf)

    file_hash = calculate_file_hash(pdf_path)

    metadata = {
        "run_id": run_id,
        "source_file": str(pdf_path.resolve()),
        "copied_file": str(copied_pdf),
        "sha256_hash": file_hash,
        "model": MODEL_TAG,
        "inference_mode": "local_ollama",
        "think": False,
        "extraction_version": "v5.3",
        "timestamp": datetime.now().isoformat(),
        "stages": {},
        "status": "in_progress",
    }

    print("=" * 80)
    print(f"KLARO BASELINE RFP WORKFLOW RUN: {run_id}")
    print(f"Input PDF:  {pdf_path}")
    print(f"Run Output: {run_dir}")
    print("=" * 80)

    try:
        # STAGE 1: PDF Extraction
        print("\n--- STAGE 1: PDF Text Extraction ---")
        emit_stage("pdf_extraction")
        st1_start = time.time()
        pages = extract_pdf_pages(str(copied_pdf))
        extracted_file = dir_extracted / f"{pdf_path.stem}.json"
        with open(extracted_file, "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False, indent=2)

        st1_time = round(time.time() - st1_start, 2)
        total_chars = sum(len(p["text"]) for p in pages)
        total_words = sum(len(p["text"].split()) for p in pages)
        metadata["stages"]["pdf_extraction"] = {
            "status": "success",
            "time_seconds": st1_time,
            "pages": len(pages),
            "words": total_words,
            "characters": total_chars,
            "artifact": str(extracted_file),
        }
        print(f"Extracted {len(pages)} pages ({total_words:,} words) in {st1_time}s -> {extracted_file}")
        emit("document", pages=len(pages))

        # Language: only runs started with --source-lang auto|de look at it; the default (en) is unchanged.
        segments = None
        translating = source_lang != "en"  # auto or de: the run keeps source.pdf, language and evidence files
        if source_lang == "auto":
            detected = detect_pages(pages)["language"]
            if detected == "unknown" and total_words > 0:
                raise ValueError("Could not tell whether this RFP is German or English. Choose the language manually.")
            source_lang = "de" if detected == "de" else "en"
        if translating:
            emit("language", detected=source_lang)
            shutil.copy2(pdf_path, run_dir / "source.pdf")
            metadata["source_language"] = source_lang
        if source_lang == "de":
            _stages = STAGES_WITH_TRANSLATION
            segments, pages = _translate(run_dir, pages, metadata)
            with open(extracted_file, "w", encoding="utf-8") as f:  # stage 3 reads page text from here
                json.dump(pages, f, ensure_ascii=False, indent=2)

        # STAGE 2: Chunking
        print("\n--- STAGE 2: Document Chunking ---")
        emit_stage("chunking")
        st2_start = time.time()
        chunks = create_chunks(pages)
        chunks_file = dir_chunks / f"{pdf_path.stem}.json"
        with open(chunks_file, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

        st2_time = round(time.time() - st2_start, 2)
        metadata["stages"]["chunking"] = {
            "status": "success",
            "time_seconds": st2_time,
            "chunks": len(chunks),
            "artifact": str(chunks_file),
        }
        print(f"Created {len(chunks)} chunks in {st2_time}s -> {chunks_file}")
        if not chunks:
            raise ValueError("No text could be extracted from this PDF. Scanned or image-only PDFs are not supported.")

        # STAGE 3: Two-Pass Chunk Analysis (Pass A + Pass B)
        print("\n--- STAGE 3: Qwen3.5-4B Two-Pass Chunk Analysis ---")
        emit_stage("chunk_analysis")
        st3_start = time.time()
        chunk_analysis_file = dir_extraction / "executive_summary_chunks_v5_3.json"

        doc_analysis = process_chunks_file(
            chunks_file,
            chunk_analysis_file,
            extracted_file_path=extracted_file,
            on_chunk=lambda done, total: emit("chunk", chunks_done=done, chunks_total=total),
        )

        st3_time = round(time.time() - st3_start, 2)
        metadata["stages"]["chunk_analysis"] = {
            "status": "success",
            "time_seconds": st3_time,
            "chunks_analyzed": doc_analysis.total_chunks,
            "artifact": str(chunk_analysis_file),
        }

        # STAGE 4: Aggregation
        print("\n--- STAGE 4: Document Fact Aggregation ---")
        emit_stage("aggregation")
        st4_start = time.time()
        aggregated_file = dir_aggregation / "executive_summary_aggregated_v1.json"
        aggregated_facts = aggregate_document(chunk_analysis_file, aggregated_file, extracted_file)

        st4_time = round(time.time() - st4_start, 2)
        metadata["stages"]["aggregation"] = {
            "status": "success",
            "time_seconds": st4_time,
            "artifact": str(aggregated_file),
        }

        # STAGE 5: Executive Summary Agent
        print("\n--- STAGE 5: Executive Summary Agent ---")
        emit_stage("summary_agent")
        st5_start = time.time()
        summary_json_file = dir_summary / "executive_summary.json"
        summary_output = run_executive_summary_agent(aggregated_file, summary_json_file)

        st5_time = round(time.time() - st5_start, 2)
        metadata["stages"]["summary_agent"] = {
            "status": "success",
            "time_seconds": st5_time,
            "artifact": str(summary_json_file),
        }

        # STAGE 6: Baseline Evaluation
        print("\n--- STAGE 6: Summary Baseline Evaluation ---")
        emit_stage("evaluation")
        st6_start = time.time()
        eval_json_file = dir_evaluation / "baseline_summary_evaluation.json"
        eval_md_file = dir_evaluation / "baseline_summary_evaluation.md"
        eval_results = run_evaluation(
            aggregated_path=aggregated_file,
            summary_path=summary_json_file,
            json_output_path=eval_json_file,
            md_output_path=eval_md_file
        )

        st6_time = round(time.time() - st6_start, 2)
        metadata["stages"]["evaluation"] = {
            "status": "success",
            "time_seconds": st6_time,
            "structural_validity": eval_results["structural_validity"]["passed"],
            "grounding_percentage": eval_results["grounding"]["grounding_percentage"],
            "traceability_percentage": eval_results["traceability"]["traceability_percentage"],
            "coverage_percentage": eval_results["coverage"]["coverage_percentage"],
            "artifact_json": str(eval_json_file),
            "artifact_md": str(eval_md_file),
        }

        # STAGE 7: Human-Readable Summary Rendering
        print("\n--- STAGE 7: Summary Rendering (Markdown & HTML) ---")
        emit_stage("rendering")
        st7_start = time.time()
        render_md, render_html = render_summary_files(summary_json_file, dir_summary)

        st7_time = round(time.time() - st7_start, 2)
        metadata["stages"]["rendering"] = {
            "status": "success",
            "time_seconds": st7_time,
            "markdown_path": str(render_md),
            "html_path": str(render_html),
        }

        german = None
        if german_summary:
            # Opt-in: also translate the English summary into German (needs the en->de model).
            from backend.llm.executive_summary.translate_summary import translate_summary_file

            german_json_file = translate_summary_file(summary_json_file, dir_summary / "executive_summary_de.json")
            german_md, german_html = render_summary_files(german_json_file, dir_summary, language="de")
            german = (german_json_file, german_md, german_html)
            metadata["stages"]["rendering"].update(
                german_json_path=str(german_json_file), german_markdown_path=str(german_md),
                german_html_path=str(german_html),
            )

        if translating:
            from backend.translation.evidence import build_evidence

            build_evidence(run_dir, source_lang, segments, pages)

        total_runtime = round(time.time() - start_time, 2)
        metadata["status"] = "completed"
        metadata["total_runtime_seconds"] = total_runtime

        # Write run metadata
        metadata_file = run_dir / "run_metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print("\n" + "=" * 80)
        print("KLARO BASELINE PIPELINE RUN COMPLETED SUCCESSFULLY")
        print("=" * 80)
        print(f"Run ID:              {run_id}")
        print(f"Source PDF:          {pdf_path}")
        print(f"Output Directory:    {run_dir}")
        print(f"Total Runtime:       {total_runtime} seconds")
        print(f"Pages:               {len(pages)}")
        print(f"Chunks:              {len(chunks)}")
        print(f"Model Used:          {MODEL_TAG} (Local Ollama)")
        print(f"Grounding Score:     {eval_results['grounding']['grounding_percentage']}%")
        print(f"Traceability Score:  {eval_results['traceability']['traceability_percentage']}%")
        print("\nGenerated Reports:")
        print(f"  - Summary Markdown: {render_md}")
        print(f"  - Summary HTML:     {render_html}")
        if german:
            print(f"  - German JSON:      {german[0]}")
            print(f"  - German Markdown:  {german[1]}")
            print(f"  - German HTML:      {german[2]}")
        print(f"  - Evaluation MD:    {eval_md_file}")
        print(f"  - Metadata JSON:    {metadata_file}")
        print("=" * 80)

        emit("done", run_dir=str(run_dir))
        return 0

    except Exception as e:
        total_runtime = round(time.time() - start_time, 2)
        metadata["status"] = "failed"
        metadata["error"] = str(e) or type(e).__name__
        metadata["failed_stage"] = _current_stage
        metadata["total_runtime_seconds"] = total_runtime

        metadata_file = run_dir / "run_metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print("\n" + "=" * 80, file=sys.stderr)
        print(f"[CRITICAL FAILURE] Pipeline execution failed: {e}", file=sys.stderr)
        print(f"Run ID: {run_id}", file=sys.stderr)
        print(f"Metadata written to: {metadata_file}", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        emit("error", stage=_current_stage, error=metadata["error"])
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run complete Klaro baseline Executive Summary pipeline on an RFP PDF.")
    parser.add_argument("pdf_path", type=str, help="Path to input RFP PDF file")
    parser.add_argument("--output-dir", type=str, default=None, help="Optional parent directory for run artifacts (default: <KLARO_DATA_DIR>/runs)")
    parser.add_argument("--run-id", type=str, default=None, help="Optional unique run identifier")
    parser.add_argument("--source-lang", choices=["auto", "en", "de"], default="en",
                        help="Language of the RFP. de translates to English first; auto detects it (default: en)")
    parser.add_argument("--german-summary", action="store_true",
                        help="Also translate the finished English summary into German (needs the en->de model)")
    parser.add_argument("--progress-json", action="store_true", help="Emit JSON progress lines on stdout; human output moves to stderr")

    args = parser.parse_args()
    # Windows pipes default to the locale code page; umlauts in file names and text must not crash a print.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    if args.progress_json:
        _progress_stream, sys.stdout = sys.stdout, sys.stderr

    preflight = preflight_error()
    if preflight:
        print(f"[CRITICAL ERROR] {preflight}", file=sys.stderr)
        emit("error", stage=None, error=preflight)
        sys.exit(1)

    exit_code = run_pipeline(
        pdf_path=Path(args.pdf_path),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        run_id=args.run_id,
        source_lang=args.source_lang,
        german_summary=args.german_summary,
    )
    sys.exit(exit_code)
