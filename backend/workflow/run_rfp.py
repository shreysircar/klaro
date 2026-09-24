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

# Import existing pipeline components
from backend.documents.pdf_extractor import extract_pdf_pages
from backend.documents.chunker import create_chunks
from backend.llm.executive_summary.chunk_analyzer import process_chunks_file
from backend.llm.executive_summary.aggregator import aggregate_document
from backend.llm.executive_summary.agent import run_executive_summary_agent
from backend.evaluation.evaluate_summary import run_evaluation
from backend.llm.executive_summary.render_summary import render_summary_files


def calculate_file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def run_pipeline(pdf_path: Path, output_dir: Path | None = None, run_id: str | None = None) -> int:
    start_time = time.time()

    if not pdf_path.exists():
        print(f"[CRITICAL ERROR] Input RFP file not found: {pdf_path}", file=sys.stderr)
        return 1

    if pdf_path.suffix.lower() != ".pdf":
        print(f"[CRITICAL ERROR] Input file is not a PDF: {pdf_path}", file=sys.stderr)
        return 1

    # 1. Setup Run Directories
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    if run_id is None:
        run_id = f"run_{pdf_path.stem}_{timestamp_str}"

    if output_dir is None:
        run_dir = Path("data/runs") / run_id
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
        "model": "qwen3.5:4b",
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

        # STAGE 2: Chunking
        print("\n--- STAGE 2: Document Chunking ---")
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

        # STAGE 3: Two-Pass Chunk Analysis (Pass A + Pass B)
        print("\n--- STAGE 3: Qwen3.5-4B Two-Pass Chunk Analysis ---")
        st3_start = time.time()
        chunk_analysis_file = dir_extraction / "executive_summary_chunks_v5_3.json"
        
        # Save a temporary copy of extracted text in data/extracted if needed by chunk_analyzer
        temp_extracted_dir = Path("data/extracted")
        temp_extracted_dir.mkdir(parents=True, exist_ok=True)
        temp_extracted_file = temp_extracted_dir / chunks_file.name
        shutil.copy2(extracted_file, temp_extracted_file)

        doc_analysis = process_chunks_file(chunks_file, chunk_analysis_file)

        st3_time = round(time.time() - st3_start, 2)
        metadata["stages"]["chunk_analysis"] = {
            "status": "success",
            "time_seconds": st3_time,
            "chunks_analyzed": doc_analysis.total_chunks,
            "artifact": str(chunk_analysis_file),
        }

        # STAGE 4: Aggregation
        print("\n--- STAGE 4: Document Fact Aggregation ---")
        st4_start = time.time()
        aggregated_file = dir_aggregation / "executive_summary_aggregated_v1.json"
        aggregated_facts = aggregate_document(chunk_analysis_file, aggregated_file)

        st4_time = round(time.time() - st4_start, 2)
        metadata["stages"]["aggregation"] = {
            "status": "success",
            "time_seconds": st4_time,
            "artifact": str(aggregated_file),
        }

        # STAGE 5: Executive Summary Agent
        print("\n--- STAGE 5: Executive Summary Agent ---")
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
        st7_start = time.time()
        render_md, render_html = render_summary_files(summary_json_file, dir_summary)

        st7_time = round(time.time() - st7_start, 2)
        metadata["stages"]["rendering"] = {
            "status": "success",
            "time_seconds": st7_time,
            "markdown_path": str(render_md),
            "html_path": str(render_html),
        }

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
        print(f"Model Used:          qwen3.5:4b (Local Ollama)")
        print(f"Grounding Score:     {eval_results['grounding']['grounding_percentage']}%")
        print(f"Traceability Score:  {eval_results['traceability']['traceability_percentage']}%")
        print("\nGenerated Reports:")
        print(f"  - Summary Markdown: {render_md}")
        print(f"  - Summary HTML:     {render_html}")
        print(f"  - Evaluation MD:    {eval_md_file}")
        print(f"  - Metadata JSON:    {metadata_file}")
        print("=" * 80)

        return 0

    except Exception as e:
        total_runtime = round(time.time() - start_time, 2)
        metadata["status"] = "failed"
        metadata["error"] = str(e)
        metadata["total_runtime_seconds"] = total_runtime

        metadata_file = run_dir / "run_metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print("\n" + "=" * 80, file=sys.stderr)
        print(f"[CRITICAL FAILURE] Pipeline execution failed: {e}", file=sys.stderr)
        print(f"Run ID: {run_id}", file=sys.stderr)
        print(f"Metadata written to: {metadata_file}", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run complete Klaro baseline Executive Summary pipeline on an RFP PDF.")
    parser.add_argument("pdf_path", type=str, help="Path to input RFP PDF file")
    parser.add_argument("--output-dir", type=str, default=None, help="Optional parent directory for run artifacts (default: data/runs)")
    parser.add_argument("--run-id", type=str, default=None, help="Optional unique run identifier")

    args = parser.parse_args()
    exit_code = run_pipeline(
        pdf_path=Path(args.pdf_path),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        run_id=args.run_id
    )
    sys.exit(exit_code)
