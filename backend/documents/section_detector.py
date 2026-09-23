import json
from pathlib import Path


KEYWORDS = [
    "scope of work",
    "deliverables",
    "eligibility",
    "qualification",
    "technical",
    "evaluation",
    "project profile",
    "project background",
    "objective",
    "requirements",
    "instruction to bidder",
    "invitation for bid",
    "commercial",
    "payment",
    "timeline",
    "schedule",
]


def load_pages(json_path: str) -> list[dict]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_sections(pages: list[dict]) -> list[dict]:
    matches = []

    for page in pages:
        lines = page["text"].splitlines()

        for line in lines:
            cleaned = line.strip().lower()

            if not cleaned:
                continue

            for keyword in KEYWORDS:
                if keyword in cleaned:
                    matches.append({
                        "page": page["page"],
                        "matched_keyword": keyword,
                        "text": line.strip(),
                    })
                    break

    return matches


if __name__ == "__main__":
    extracted_directory = Path("data/extracted")

    for json_file in extracted_directory.glob("*.json"):
        print("\n" + "=" * 70)
        print(f"Document: {json_file.name}")
        print("=" * 70)

        pages = load_pages(str(json_file))
        matches = find_sections(pages)

        for match in matches:
            print(
                f"Page {match['page']:>3} | "
                f"{match['matched_keyword']:<25} | "
                f"{match['text']}"
            )

        print(f"\nTotal matches: {len(matches)}")