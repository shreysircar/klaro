import json
import time
from pathlib import Path

from pypdf import PdfReader


def extract_pdf_pages(pdf_path: str) -> list[dict]:
    reader = PdfReader(pdf_path)

    pages = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""

        pages.append({
            "page": page_number,
            "text": text.strip(),
        })

    return pages


if __name__ == "__main__":
    pdf_directory = Path("data/rfp")
    output_directory = Path("data/extracted")

    output_directory.mkdir(parents=True, exist_ok=True)

    for pdf_file in pdf_directory.glob("*.pdf"):
        print(f"\nProcessing: {pdf_file.name}")

        start_time = time.time()

        pages = extract_pdf_pages(str(pdf_file))

        elapsed = time.time() - start_time

        total_characters = sum(len(page["text"]) for page in pages)
        total_words = sum(len(page["text"].split()) for page in pages)

        output_file = output_directory / f"{pdf_file.stem}.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False, indent=2)

        print(f"Pages: {len(pages)}")
        print(f"Characters extracted: {total_characters:,}")
        print(f"Words extracted: {total_words:,}")
        print(f"Extraction time: {elapsed:.2f} seconds")
        print(f"Saved to: {output_file}")