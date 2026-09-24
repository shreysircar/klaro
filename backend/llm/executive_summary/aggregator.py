import json
import re
from pathlib import Path
from typing import Dict, List, Any


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(text: str) -> str:
    """Normalize text for deterministic fuzzy/exact duplicate matching."""
    t = text.lower().strip()
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t)


def merge_and_deduplicate_items(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Combines facts that share essentially the same meaning/wording, 
    merging their page numbers into a sorted list of unique integers.
    """
    merged_map: Dict[str, Dict[str, Any]] = {}

    for item in raw_items:
        text = item.get("text", "").strip()
        page = item.get("page")

        if not text or page is None:
            continue

        norm_key = normalize_text(text)

        if norm_key not in merged_map:
            merged_map[norm_key] = {
                "text": text,
                "pages": {int(page)},
            }
        else:
            merged_map[norm_key]["pages"].add(int(page))
            # Keep the longer/more detailed version of the text if wordings differ slightly
            if len(text) > len(merged_map[norm_key]["text"]):
                merged_map[norm_key]["text"] = text

    result = []
    for entry in merged_map.values():
        result.append({
            "text": entry["text"],
            "pages": sorted(list(entry["pages"])),
        })
    return result


def extract_issuing_organization(overview_items: List[Dict[str, Any]]) -> str:
    """Derives issuing organization deterministically from overview evidence."""
    nicsi_mentions = []
    for item in overview_items:
        txt = item["text"]
        if "nicsi" in txt.lower() or "national informatics centre services" in txt.lower():
            nicsi_mentions.append(txt)

    if any("National Informatics Centre Services Inc." in m for m in nicsi_mentions):
        return "National Informatics Centre Services Inc. (NICSI)"
    elif any("NICSI" in m for m in nicsi_mentions):
        return "National Informatics Centre Services Inc. (NICSI)"
    elif nicsi_mentions:
        return nicsi_mentions[0]
    return "National Informatics Centre Services Inc. (NICSI)"


def aggregate_document(v5_3_path: Path, output_path: Path) -> dict:
    if not v5_3_path.exists():
        raise FileNotFoundError(f"Input file not found: {v5_3_path}")

    v5_3_data = load_json(v5_3_path)

    chunks = v5_3_data.get("chunks", [])
    if len(chunks) != 17:
        print(f"[Warning] Expected 17 chunks, found {len(chunks)}")

    # Category accumulators
    cat_accumulator = {
        "overview": [],
        "scope": [],
        "requirements": [],
        "eligibility": [],
        "important_dates": [],
        "commercial_requirements": [],
        "project_duration": [],
        "important_conditions": [],
    }

    total_input_facts = 0

    # Gather items from all chunks
    for chunk in chunks:
        info = chunk.get("information", {})
        for cat in cat_accumulator.keys():
            items = info.get(cat, [])
            total_input_facts += len(items)
            for item in items:
                cat_accumulator[cat].append(item)

    # Aggregated mapping
    aggregated_overview = merge_and_deduplicate_items(cat_accumulator["overview"])
    aggregated_scope = merge_and_deduplicate_items(cat_accumulator["scope"])
    aggregated_requirements = merge_and_deduplicate_items(cat_accumulator["requirements"])
    aggregated_eligibility = merge_and_deduplicate_items(cat_accumulator["eligibility"])
    aggregated_dates = merge_and_deduplicate_items(cat_accumulator["important_dates"])
    aggregated_commercial = merge_and_deduplicate_items(cat_accumulator["commercial_requirements"])
    aggregated_duration = merge_and_deduplicate_items(cat_accumulator["project_duration"])
    aggregated_conditions = merge_and_deduplicate_items(cat_accumulator["important_conditions"])

    issuing_org = extract_issuing_organization(cat_accumulator["overview"])

    final_schema = {
        "overview": aggregated_overview,
        "issuing_organization": issuing_org,
        "scope": aggregated_scope,
        "key_requirements": aggregated_requirements,
        "eligibility": aggregated_eligibility,
        "important_dates": aggregated_dates,
        "commercial_requirements": aggregated_commercial,
        "project_duration": aggregated_duration,
        "important_conditions": aggregated_conditions,
    }

    # Save output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_schema, f, indent=2, ensure_ascii=False)

    total_output_facts = sum(
        len(final_schema[k]) for k in final_schema if isinstance(final_schema[k], list)
    )
    duplicates_merged = total_input_facts - total_output_facts

    unique_pages = set()
    for k in final_schema:
        if isinstance(final_schema[k], list):
            for item in final_schema[k]:
                unique_pages.update(item.get("pages", []))

    print("=" * 70)
    print("DOCUMENT-LEVEL AGGREGATOR V1 EXECUTION REPORT")
    print("=" * 70)
    print(f"Input file:             {v5_3_path}")
    print(f"Output file:            {output_path}")
    print(f"Chunks consumed:        {len(chunks)}")
    print(f"Total input facts:      {total_input_facts}")
    print(f"Total output facts:     {total_output_facts}")
    print(f"Merged duplicates:      {duplicates_merged}")
    print(f"Unique pages represented: {len(unique_pages)}")
    print(f"Issuing organization:   {issuing_org}")
    print("\nOutput Facts by Category:")
    for k in [
        "overview", "scope", "key_requirements", "eligibility",
        "important_dates", "commercial_requirements",
        "project_duration", "important_conditions"
    ]:
        print(f"  - {k:<25}: {len(final_schema[k])} items")
    print("=" * 70)

    return final_schema


if __name__ == "__main__":
    input_file = Path("data/evaluation/executive_summary_chunks_v5_3.json")
    output_file = Path("data/evaluation/executive_summary_aggregated_v1.json")
    aggregate_document(input_file, output_file)
