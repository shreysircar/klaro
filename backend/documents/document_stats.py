import json
from pathlib import Path


def load_pages(json_path: str) -> list[dict]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def estimate_tokens(text: str) -> int:
    """
    Rough token estimate.

    For English text, a common approximation is
    around 1 token per 4 characters.
    This is only an estimate; the actual tokenizer
    of the model may produce a different count.
    """
    return len(text) // 4


if __name__ == "__main__":
    extracted_directory = Path("data/extracted")

    for json_file in extracted_directory.glob("*.json"):
        pages = load_pages(str(json_file))

        full_text = "\n".join(page["text"] for page in pages)

        page_lengths = [
            len(page["text"])
            for page in pages
        ]

        print("\n" + "=" * 60)
        print(f"Document: {json_file.name}")
        print("=" * 60)

        print(f"Pages: {len(pages):,}")
        print(f"Characters: {len(full_text):,}")
        print(f"Words: {len(full_text.split()):,}")
        print(f"Estimated tokens: {estimate_tokens(full_text):,}")

        print(f"Smallest page: {min(page_lengths):,} characters")
        print(f"Largest page: {max(page_lengths):,} characters")
        print(
            f"Average page: "
            f"{sum(page_lengths) / len(page_lengths):,.0f} characters"
        )