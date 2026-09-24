import argparse
import json
import time
from pathlib import Path

from backend.llm.executive_summary.schema import (
    ChunkAnalysisResult,
    ChunkInformation,
    DocumentAnalysisResult,
    ExtractedItem,
    PassAInformation,
    PassBInformation,
)
from backend.llm.executive_summary.factual_analyzer import run_pass_a
from backend.llm.executive_summary.contractual_analyzer import run_pass_b


def load_json(path: Path) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_page_labeled_chunk_text(chunk: dict, page_records: list[dict]) -> str:
    chunk_pages = set(chunk["pages"])
    pages_dict = {p["page"]: p["text"] for p in page_records if p["page"] in chunk_pages}

    parts = []
    for page_num in sorted(chunk_pages):
        text = pages_dict.get(page_num, "")
        if text:
            parts.append(f"\n--- [PAGE {page_num}] ---\n{text}")

    return "\n".join(parts) if parts else chunk.get("text", "")


def deduplicate_items(items: list[ExtractedItem]) -> list[ExtractedItem]:
    """Deterministic exact duplicate removal within a category based on normalized text."""
    seen = set()
    unique = []
    for item in items:
        norm = item.text.strip().lower()
        if norm not in seen:
            seen.add(norm)
            unique.append(item)
    return unique


def merge_passes(pass_a: PassAInformation, pass_b: PassBInformation) -> ChunkInformation:
    """Deterministic merge of Pass A and Pass B outputs with exact deduplication."""
    return ChunkInformation(
        overview=deduplicate_items(pass_a.overview),
        scope=deduplicate_items(pass_a.scope),
        requirements=deduplicate_items(pass_a.requirements),
        eligibility=deduplicate_items(pass_a.eligibility),
        important_dates=deduplicate_items(pass_b.important_dates),
        commercial_requirements=deduplicate_items(pass_b.commercial_requirements),
        project_duration=deduplicate_items(pass_b.project_duration),
        important_conditions=deduplicate_items(pass_b.important_conditions),
    )


def analyze_single_chunk(chunk: dict, page_records: list[dict]) -> ChunkAnalysisResult:
    chunk_id = chunk["chunk_id"]
    pages = chunk["pages"]
    word_count = chunk["word_count"]

    page_text = build_page_labeled_chunk_text(chunk, page_records)

    # 1. Execute Pass A
    pass_a_info, pass_a_time, pass_a_success, pass_a_err = run_pass_a(page_text, chunk_id, pages)

    # 2. Execute Pass B
    pass_b_info, pass_b_time, pass_b_success, pass_b_err = run_pass_b(page_text, chunk_id, pages)

    # 3. Deterministic Merge
    merged_info = merge_passes(pass_a_info, pass_b_info)
    total_time = round(pass_a_time + pass_b_time, 2)

    return ChunkAnalysisResult(
        chunk_id=chunk_id,
        pages=pages,
        word_count=word_count,
        pass_a_success=pass_a_success,
        pass_b_success=pass_b_success,
        pass_a_error=pass_a_err,
        pass_b_error=pass_b_err,
        pass_a_inference_time_seconds=pass_a_time,
        pass_b_inference_time_seconds=pass_b_time,
        total_inference_time_seconds=total_time,
        information=merged_info,
    )


def process_chunks_file(chunk_file_path: Path, output_file_path: Path | None = None) -> DocumentAnalysisResult:
    if not chunk_file_path.exists():
        raise FileNotFoundError(f"Chunk file not found: {chunk_file_path}")

    chunks_data = load_json(chunk_file_path)

    extracted_file_path = Path("data/extracted") / chunk_file_path.name
    if extracted_file_path.exists():
        page_records = load_json(extracted_file_path)
    else:
        page_records = []

    doc_name = chunk_file_path.stem
    print("=" * 70)
    print(f"TWO-PASS CHUNK ANALYSIS: {chunk_file_path.name}")
    print(f"Total Chunks: {len(chunks_data)}")
    print("=" * 70)

    analyzed_chunks: list[ChunkAnalysisResult] = []
    tot_pass_a_time = 0.0
    tot_pass_b_time = 0.0

    for idx, chunk in enumerate(chunks_data, start=1):
        print(f"[{idx}/{len(chunks_data)}] Analyzing Chunk {chunk['chunk_id']} (Pages {chunk['pages'][0]}-{chunk['pages'][-1]})...", flush=True)
        res = analyze_single_chunk(chunk, page_records)
        
        tot_pass_a_time += res.pass_a_inference_time_seconds
        tot_pass_b_time += res.pass_b_inference_time_seconds

        item_count = sum(len(getattr(res.information, c)) for c in [
            "overview", "scope", "requirements", "eligibility",
            "important_dates", "commercial_requirements",
            "project_duration", "important_conditions"
        ])

        status_str = f"PassA: {'OK' if res.pass_a_success else 'FAIL'} ({res.pass_a_inference_time_seconds}s) | PassB: {'OK' if res.pass_b_success else 'FAIL'} ({res.pass_b_inference_time_seconds}s)"
        print(f"   -> {status_str} | Merged Items: {item_count}")
        analyzed_chunks.append(res)

    tot_time = round(tot_pass_a_time + tot_pass_b_time, 2)

    doc_result = DocumentAnalysisResult(
        document_name=doc_name,
        total_chunks=len(analyzed_chunks),
        total_pass_a_inference_time_seconds=round(tot_pass_a_time, 2),
        total_pass_b_inference_time_seconds=round(tot_pass_b_time, 2),
        total_inference_time_seconds=tot_time,
        chunks=analyzed_chunks,
    )

    if output_file_path is None:
        output_dir = Path("data/evaluation")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file_path = output_dir / f"executive_summary_chunks_v5_3.json"

    with open(output_file_path, "w", encoding="utf-8") as f:
        f.write(doc_result.model_dump_json(indent=2))

    print("=" * 70)
    print(f"Saved complete two-pass chunk analysis to: {output_file_path}")
    print("=" * 70)

    return doc_result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Two-pass RFP chunk analysis for Executive Summarization.")
    parser.add_argument("chunk_file", type=str, help="Path to chunk JSON file (e.g. data/chunks/1.json)")
    parser.add_argument("--output", type=str, default=None, help="Optional output path")

    args = parser.parse_args()
    process_chunks_file(Path(args.chunk_file), Path(args.output) if args.output else None)
