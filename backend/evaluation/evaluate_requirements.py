import json
import re
from pathlib import Path


BASELINE_FILE = Path("data/evaluation/baseline_results.json")
GOLD_FILE = Path("data/evaluation/gold_requirements.json")


def normalize(text: str) -> set[str]:
    """
    Convert text into a set of normalized words.
    """
    text = text.lower()
    text = re.sub(r"[^a-z0-9%]+", " ", text)

    stopwords = {
        "the", "a", "an", "and", "or", "of", "to",
        "for", "in", "on", "with", "shall", "must",
        "be", "is", "are", "from", "by", "as",
        "that", "this", "their", "its"
    }

    return {
        word
        for word in text.split()
        if word not in stopwords
    }


def similarity(text_a: str, text_b: str) -> float:
    """
    Jaccard similarity between two normalized word sets.
    """
    words_a = normalize(text_a)
    words_b = normalize(text_b)

    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    union = words_a | words_b

    return len(intersection) / len(union)


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_chunk(
    chunk_id: int,
    generated_requirements: list[dict],
    gold_requirements: list[dict],
):
    print("\n" + "=" * 70)
    print(f"CHUNK {chunk_id}")
    print("=" * 70)

    if not generated_requirements:
        print("Generated requirements: 0")
        print(f"Gold requirements:      {len(gold_requirements)}")
        print("Candidate matches:      0")
        return 0, len(gold_requirements)

    matched_gold = set()

    for generated_index, generated in enumerate(generated_requirements):
        best_gold_index = None
        best_score = 0.0

        for gold_index, gold in enumerate(gold_requirements):
            if gold_index in matched_gold:
                continue

            score = similarity(
                generated["text"],
                gold["text"]
            )

            if score > best_score:
                best_score = score
                best_gold_index = gold_index

        print(f"\nGenerated #{generated_index + 1}")
        print(f"  {generated['text']}")

        if best_gold_index is not None:
            gold = gold_requirements[best_gold_index]

            print("\n  Best gold candidate:")
            print(f"  {gold['text']}")
            print(f"  Similarity: {best_score:.3f}")

            if best_score >= 0.35:
                print("  Candidate match: YES")
                matched_gold.add(best_gold_index)
            else:
                print("  Candidate match: NO")
        else:
            print("  No candidate available.")

    print("\n" + "-" * 70)
    print(f"Gold requirements covered: {len(matched_gold)} / {len(gold_requirements)}")

    return len(matched_gold), len(gold_requirements)


def main():
    baseline = load_json(BASELINE_FILE)
    gold = load_json(GOLD_FILE)

    gold_by_chunk = {
        item["chunk_id"]: item["requirements"]
        for item in gold["chunks"]
    }

    total_matched = 0
    total_gold = 0

    for chunk in baseline["chunks"]:
        chunk_id = chunk["chunk_id"]

        generated = chunk.get("parsed_output")

        if generated is None:
            generated_requirements = []
        else:
            generated_requirements = generated.get(
                "requirements",
                []
            )

        gold_requirements = gold_by_chunk.get(
            chunk_id,
            []
        )

        matched, gold_count = evaluate_chunk(
            chunk_id,
            generated_requirements,
            gold_requirements
        )

        total_matched += matched
        total_gold += gold_count

    print("\n" + "=" * 70)
    print("OVERALL BASELINE COVERAGE")
    print("=" * 70)

    print(f"Matched gold requirements: {total_matched}")
    print(f"Total gold requirements:   {total_gold}")

    if total_gold:
        coverage = total_matched / total_gold
        print(f"Gold coverage:              {coverage:.2%}")


if __name__ == "__main__":
    main()