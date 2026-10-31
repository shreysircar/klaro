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


# Organization-type head nouns and legal suffixes. Generic words only: no organization names.
_ORG_HEADS = {
    "agency", "authority", "bank", "board", "bureau", "centre", "center", "commission", "committee",
    "company", "corporation", "council", "department", "directorate", "division", "foundation",
    "government", "institute", "institution", "ministry", "mission", "municipality", "office",
    "organisation", "organization", "railways", "services", "society", "trust", "undertaking",
    "university",
}
_LEGAL_SUFFIX = re.compile(r"(?:[\s,]+(?:limited|ltd|inc|incorporated|pvt|private|llp|plc|co)\.?)+$", re.IGNORECASE)
# Runs of Capitalized words, joined by "of", "and" or "&" (e.g. "Ministry of Finance").
_CAPITALIZED_RUN = re.compile(r"[A-Z][\w&'.-]*(?:\s+(?:(?:of|and|&)\s+)?[A-Z][\w&'.-]*)*")


def org_key(name: str) -> str:
    """Comparison key: "The X Bank Ltd." and "X Bank Limited" are the same organization."""
    name = re.sub(r"^the\s+", "", name.strip().rstrip(".,;:"), flags=re.IGNORECASE)
    return normalize_text(_LEGAL_SUFFIX.sub("", name))


def _organizations_in(text: str) -> List[str]:
    found = []
    for run in _CAPITALIZED_RUN.findall(text):
        name = re.sub(r"^The\s+", "", run).rstrip(",;:")
        # "Assistant General Manager of X Bank" is not an organization, but "X Bank" is.
        while name:
            left = _LEGAL_SUFFIX.sub("", name.split(" of ")[0]).rstrip(".")
            if left.split()[-1].lower() in _ORG_HEADS:
                found.append(name if re.search(r"\b(?:Ltd|Inc|Co)\.$", name) else name.rstrip("."))
                break
            name = name.split(" of ", 1)[1] if " of " in name else ""
    return found


def find_issuing_organization(overview_items: List[Dict[str, Any]]) -> tuple[str, List[int]]:
    """The organization named most often in pass A overview facts (the only field that carries the
    issuer), with the pages that name it. ("Not identified", []) if none is found.
    ponytail: frequency heuristic over capitalized names; an LLM field for the issuer would be sturdier."""
    groups: Dict[str, Dict[str, Any]] = {}
    for item in overview_items:
        for name in dict.fromkeys(_organizations_in(item.get("text", ""))):
            g = groups.setdefault(org_key(name), {"count": 0, "forms": {}, "pages": set()})
            g["count"] += 1
            g["forms"][name] = g["forms"].get(name, 0) + 1
            if isinstance(item.get("page"), int):
                g["pages"].add(item["page"])
    if not groups:
        return "Not identified", []
    best = max(groups.values(), key=lambda g: g["count"])
    name = max(best["forms"], key=lambda f: (best["forms"][f], len(f)))
    return name, sorted(best["pages"])


def extract_issuing_organization(overview_items: List[Dict[str, Any]]) -> str:
    """Derives issuing organization deterministically from overview evidence."""
    return find_issuing_organization(overview_items)[0]


def aggregate_document(v5_3_path: Path, output_path: Path, pages_path: Path | None = None) -> dict:
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

    issuing_org, issuing_org_pages = find_issuing_organization(cat_accumulator["overview"])
    if issuing_org == "Not identified" and pages_path is not None:
        # The overview facts may not name the issuer (it can sit in a logo); fall back to the page text.
        pages = load_json(pages_path)
        issuing_org, issuing_org_pages = find_issuing_organization(
            [{"text": p["text"], "page": p["page"]} for p in pages]
        )

    final_schema = {
        "overview": aggregated_overview,
        "issuing_organization": issuing_org,
        "issuing_organization_pages": issuing_org_pages,
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

    fact_lists = [v for k, v in final_schema.items() if isinstance(v, list) and k != "issuing_organization_pages"]
    total_output_facts = sum(len(v) for v in fact_lists)
    duplicates_merged = total_input_facts - total_output_facts

    unique_pages = set()
    for facts in fact_lists:
        for item in facts:
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
    print(f"Issuing organization:   {issuing_org} (pages {issuing_org_pages})")
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
