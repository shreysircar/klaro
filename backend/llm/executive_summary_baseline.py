import json
import time
from pathlib import Path

from ollama import chat


MODEL = "qwen3.5:4b"

CHUNK_FILE = Path("data/chunks/rfp_1.json")
PAGE_FILE = Path("data/extracted/rfp_1.json")


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


def build_page_labeled_text(
    chunk: dict,
    pages: list[dict]
) -> str:

    chunk_pages = set(chunk["pages"])

    selected_pages = [
        page
        for page in pages
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
You are an RFP executive summary system.

Create a concise, factual executive summary of the provided RFP text.

IMPORTANT RULES:

1. Use ONLY information explicitly present in the RFP text.
2. Do not use outside knowledge.
3. Do not invent missing information.
4. Preserve the terminology used by the RFP.
5. If a field is not available in the provided text, use an empty string
   or an empty list.
6. Do not include unsupported interpretations.
7. Keep the summary concise.
8. Every important factual statement should be traceable to the
   provided RFP text.

Return ONLY valid JSON.

Use exactly this structure:

{{
  "overview": "",
  "issuing_organization": "",
  "scope": "",
  "key_requirements": [],
  "eligibility": [],
  "important_dates": [],
  "commercial_requirements": [],
  "project_duration": "",
  "important_conditions": []
}}

RFP TEXT:

{page_text}
"""


def run_baseline(chunk_id: int):

    chunk = load_chunk(chunk_id)
    pages = load_pages()

    page_text = build_page_labeled_text(
        chunk,
        pages
    )

    prompt = build_prompt(page_text)

    print("=" * 70)
    print("EXECUTIVE SUMMARY BASELINE")
    print("=" * 70)

    print(f"Chunk ID: {chunk_id}")
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
        ]
    )

    elapsed = time.time() - start_time

    raw_output = response.message.content

    print(f"Inference time: {elapsed:.2f} seconds")

    print("\n" + "=" * 70)
    print("RAW OUTPUT")
    print("=" * 70)

    print(raw_output)

    print("\n" + "=" * 70)

    try:
        result = json.loads(raw_output)

        print("JSON VALID: YES")

        print("\n" + "=" * 70)
        print("PARSED OUTPUT")
        print("=" * 70)

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False
            )
        )

    except json.JSONDecodeError as e:

        print("JSON VALID: NO")
        print(f"Error: {e}")

        output_file = Path(
            "data/executive_summary_raw.txt"
        )

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(raw_output)

        print(
            f"Raw output saved to: {output_file}"
        )


if __name__ == "__main__":
    run_baseline(1)