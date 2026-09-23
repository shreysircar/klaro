import json
import time
from pathlib import Path

from ollama import chat


MODEL = "qwen3.5:4b"


def load_chunk(json_path: str, chunk_id: int = 1) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    return next(
        chunk for chunk in chunks
        if chunk["chunk_id"] == chunk_id
    )


def load_pages(json_path: str) -> list[dict]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_page_labeled_text(
    chunk: dict,
    pages: list[dict]
) -> str:

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


def analyze_chunk(
    chunk: dict,
    page_text: str
) -> dict:

    prompt = f"""
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

    print(f"\nInference time: {elapsed:.2f} seconds")

    raw_output = response.message.content

    print("\n" + "=" * 70)
    print("RAW MODEL OUTPUT")
    print("=" * 70)

    print(raw_output)

    print("\n" + "=" * 70)
    print(f"OUTPUT LENGTH: {len(raw_output)} characters")
    print("=" * 70)

    try:
        return json.loads(raw_output)

    except json.JSONDecodeError as e:

        print("\nJSON PARSING FAILED")
        print(f"Error: {e}")

        # Save raw response for debugging
        output_file = Path("data") / "raw_qwen_output.txt"

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(raw_output)

        print(f"Raw output saved to: {output_file}")

        raise


if __name__ == "__main__":

    chunk_file = Path("data/chunks/rfp_1.json")
    extracted_file = Path("data/extracted/rfp_1.json")

    chunk = load_chunk(
        str(chunk_file),
        chunk_id=5
    )

    pages = load_pages(
        str(extracted_file)
    )

    page_text = build_page_labeled_text(
        chunk,
        pages
    )

    print("=" * 70)
    print("STRUCTURED RFP BASELINE ANALYSIS")
    print("=" * 70)

    print(f"Chunk ID: {chunk['chunk_id']}")
    print(f"Pages: {chunk['pages']}")
    print(f"Words: {chunk['word_count']}")

    print("\nSending chunk to Qwen...")

    result = analyze_chunk(
        chunk,
        page_text
    )

    print("\n" + "=" * 70)
    print("STRUCTURED MODEL OUTPUT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False
        )
    )