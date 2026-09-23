import json
import re
from pathlib import Path

TARGET_WORDS = 1800
OVERLAP_WORDS = 200


def load_pages(json_path: str) -> list[dict]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def looks_like_heading(line: str) -> bool:
    """
    Detect strong structural headings only.
    We intentionally avoid generic ALL-CAPS detection because RFP text
    contains many short uppercase strings that are not actual section headings.
    """
    line = line.strip()
    if not line:
        return False

    # Ignore very long lines
    if len(line) > 150:
        return False

    # ---------------------------------------------------------
    # 1. Numbered headings
    # Examples:
    # 1. INVITATION FOR BID
    # 2. PROJECT PROFILE & BACKGROUND
    # 4. SCOPE OF WORK, DELIVERABLES
    # ---------------------------------------------------------
    if re.match(r"^\d{1,2}\.\s+[A-Z][A-Z0-9\s&/,()\-]+$", line):
        return True

    # ---------------------------------------------------------
    # 2. SECTION headings
    # Examples:
    # SECTION-D: SCOPE OF WORK
    # SECTION - D: SCOPE OF WORK
    # SECTION E: ELIGIBILITY & QUALIFICATION
    # ---------------------------------------------------------
    if re.match(r"^SECTION\s*[-:]?\s*[A-Z0-9]+\s*[:\-]\s*.+$", line, re.IGNORECASE):
        return True

    return False


def find_toc_pages(pages: list[dict]) -> set[int]:
    """
    Find pages that are likely to contain the Table of Contents.
    We only inspect the first part of the document because a TOC normally
    appears near the beginning.
    """
    toc_pages = set()
    for page in pages[:15]:
        text = page["text"].upper()
        # Strong TOC signals
        if (
            "TABLE OF CONTENTS" in text
            or "CONTENTS" in text
            or (
                "INVITATION FOR BID" in text
                and "PROJECT PROFILE" in text
                and "SCOPE OF WORK" in text
            )
        ):
            toc_pages.add(page["page"])
    return toc_pages


def extract_sections(pages: list[dict]) -> list[dict]:
    """Identify likely section headings while ignoring TOC pages."""
    sections = []
    toc_pages = find_toc_pages(pages)
    for page in pages:
        # Do not treat TOC entries as actual section headings
        if page["page"] in toc_pages:
            continue
        for line in page["text"].splitlines():
            if looks_like_heading(line):
                sections.append(
                    {
                        "title": line.strip(),
                        "page": page["page"],
                    }
                )
    return sections


def create_chunks(pages: list[dict]) -> list[dict]:
    chunks = []
    current_words = []
    current_pages = []
    current_section = "Document Start"
    section_index = 0

    sections = extract_sections(pages)

    for page in pages:
        page_number = page["page"]

        # Determine whether a section begins on this page
        page_sections = [s for s in sections if s["page"] == page_number]
        if page_sections:
            # Use the latest detected heading on this page
            current_section = page_sections[-1]["title"]

        words = page["text"].split()
        for word in words:
            current_words.append(word)
            if page_number not in current_pages:
                current_pages.append(page_number)

            # Chunk when target size is reached
            if len(current_words) >= TARGET_WORDS:
                chunks.append(
                    {
                        "chunk_id": len(chunks) + 1,
                        "section": current_section,
                        "pages": current_pages.copy(),
                        "word_count": len(current_words),
                        "text": " ".join(current_words),
                    }
                )
                # Maintain overlap
                current_words = current_words[-OVERLAP_WORDS:]
                current_pages = [page_number]

    # Remaining text
    if current_words:
        chunks.append(
            {
                "chunk_id": len(chunks) + 1,
                "section": current_section,
                "pages": current_pages.copy(),
                "word_count": len(current_words),
                "text": " ".join(current_words),
            }
        )

    return chunks


if __name__ == "__main__":
    extracted_directory = Path("data/extracted")
    for json_file in extracted_directory.glob("*.json"):
        print("\n" + "=" * 70)
        print(f"Document: {json_file.name}")
        print("=" * 70)

        pages = load_pages(str(json_file))
        chunks = create_chunks(pages)

        print(f"Pages: {len(pages)}")
        print(f"Chunks: {len(chunks)}")

        # Save chunks
        output_directory = Path("data/chunks")
        output_directory.mkdir(parents=True, exist_ok=True)

        output_file = output_directory / json_file.name

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

        print(f"Saved chunks to: {output_file}")

        if chunks:
            average_size = sum(c["word_count"] for c in chunks) / len(chunks)
            print(f"Average chunk size: {average_size:.0f} words")

            print("\n--- FIRST 5 CHUNKS ---")
            for chunk in chunks[:5]:
                print("\n" + "-" * 60)
                print(
                    f"Chunk: {chunk['chunk_id']} | "
                    f"Section: {chunk['section']} | "
                    f"Pages: {chunk['pages'][0]}-{chunk['pages'][-1]} | "
                    f"Words: {chunk['word_count']}"
                )
                print(chunk["text"][:500])
