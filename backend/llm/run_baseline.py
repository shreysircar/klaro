import json
import time
from pathlib import Path

from ollama import chat


MODEL = "qwen3.5:4b"

CHUNK_FILE = Path("data/chunks/rfp_1.json")
PAGE_FILE = Path("data/extracted/rfp_1.json")
RESULT_FILE = Path("data/evaluation/baseline_results.json")


def load_chunk(chunk_id: int) -> dict:
    with open(CHUNK_FILE, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    return next(
        chunk for chunk in chunks
        if chunk["chunk_id"] == chunk_id
    )


def load_pages() -> list[dict]:
    with open(PAGE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_page_labeled_text(chunk: dict, pages: list[dict]) -> str:
    chunk_pages = set(chunk["pages"])

    selected_pages = [
        page for page in pages
        if page["page"] in chunk_pages
    ]

    parts = []

    for page in selected_pages:
        parts.append(
            f"\n[PAGE {page['page']}]\n"
            f"{page['text']}"
        )

    return "\n".join(parts)


def build_prompt(page_text: str) -> str:
    return f"""
You are an RFP requirements extraction system.

Extract explicit requirements stated in the provided RFP text.

STRICT RULES:

1. Extract ONLY requirements explicitly stated in the text.
2. Do not use outside knowledge.
3. Do not infer or reinterpret requirements.
4. Preserve the terminology used by the RFP.
5. Every requirement must have a page number.
6. Every requirement must have a SHORT exact quote from the RFP.
7. Extract at most 8 requirements.
8. Keep each evidence quote under 30 words.
9. Do not include general descriptions unless they are explicitly
   stated as a requirement or obligation.
10. If there are no explicit requirements, return an empty list.

Return ONLY valid JSON.

Use exactly this structure:

{{
  "requirements": [
    {{
      "text": "requirement stated in the RFP",
      "page": 1,
      "evidence": "short exact quote from the RFP"
    }}
  ]
}}

RFP TEXT:

{page_text}
"""


def run_chunk(chunk_id: int):
    chunk = load_chunk(chunk_id)
    pages = load_pages()

    page_text = build_page_labeled_text(chunk, pages)
    prompt = build_prompt(page_text)

    print("=" * 70)
    print(f"RUNNING BASELINE — CHUNK {chunk_id}")
    print("=" * 70)
    print(f"Pages: {chunk['pages']}")
    print(f"Words: {chunk['word_count']}")
    print()

    start_time = time.time()

    response = chat(
        model=MODEL,
        think=False,
        format="json",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
    )

    elapsed = time.time() - start_time

    raw_output = response.message.content

    print(f"Inference time: {elapsed:.2f} seconds")
    print()
    print(raw_output)

    try:
        parsed_output = json.loads(raw_output)
        json_valid = True
    except json.JSONDecodeError:
        parsed_output = None
        json_valid = False

    with open(RESULT_FILE, "r", encoding="utf-8") as f:
        results = json.load(f)

    results["chunks"] = [
        item
        for item in results["chunks"]
        if item["chunk_id"] != chunk_id
    ]

    results["chunks"].append(
        {
            "chunk_id": chunk_id,
            "pages": chunk["pages"],
            "word_count": chunk["word_count"],
            "inference_time_seconds": round(elapsed, 2),
            "json_valid": json_valid,
            "raw_output": raw_output,
            "parsed_output": parsed_output
        }
    )

    results["chunks"].sort(
        key=lambda item: item["chunk_id"]
    )

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            results,
            f,
            indent=2,
            ensure_ascii=False
        )

    print()
    print("=" * 70)
    print(f"Saved to: {RESULT_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    run_chunk(3)