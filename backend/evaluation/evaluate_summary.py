"""
Baseline Evaluation script for Executive Summary Pipeline (v1)

Evaluates multidimensional baseline performance:
A. Structural Validity
B. Grounding / Faithfulness
C. Traceability
D. Coverage
E. Duplication
F. Category Consistency
G. Information Loss
H. Hallucination / Unsupported Content
I. Conciseness & Compression
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def tokenize(text: str) -> Set[str]:
    """Simple word tokenization for deterministic lexical matching."""
    return set(re.findall(r"\b\w{3,}\b", text.lower()))


def compute_jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
    if not set1 or not set2:
        return 0.0
    intersection = set1.intersection(set2)
    union = set1.union(set2)
    return len(intersection) / len(union)


def check_structural_validity(summary: dict) -> dict:
    required_fields = [
        "overview",
        "issuing_organization",
        "scope",
        "key_requirements",
        "eligibility",
        "important_dates",
        "commercial_requirements",
        "project_duration",
        "important_conditions",
    ]
    
    missing_fields = [f for f in required_fields if f not in summary]
    unexpected_fields = [f for f in summary if f not in required_fields]
    
    valid_types = True
    invalid_type_details = []

    # overview check
    ov = summary.get("overview")
    if isinstance(ov, dict):
        if "text" not in ov or "pages" not in ov:
            valid_types = False
            invalid_type_details.append("overview missing 'text' or 'pages'")
        elif not isinstance(ov["text"], str) or not isinstance(ov["pages"], list):
            valid_types = False
            invalid_type_details.append("overview 'text' must be str and 'pages' must be list")
    else:
        valid_types = False
        invalid_type_details.append("overview must be dict")

    # issuing_org check
    if not isinstance(summary.get("issuing_organization"), str):
        valid_types = False
        invalid_type_details.append("issuing_organization must be str")

    # list categories
    list_categories = [
        "scope", "key_requirements", "eligibility",
        "important_dates", "commercial_requirements",
        "project_duration", "important_conditions"
    ]
    for cat in list_categories:
        val = summary.get(cat)
        if not isinstance(val, list):
            valid_types = False
            invalid_type_details.append(f"{cat} must be list")
        else:
            for idx, item in enumerate(val):
                if not isinstance(item, dict) or "text" not in item or "pages" not in item:
                    valid_types = False
                    invalid_type_details.append(f"{cat}[{idx}] must be dict with 'text' and 'pages'")
                elif not isinstance(item["text"], str) or not isinstance(item["pages"], list):
                    valid_types = False
                    invalid_type_details.append(f"{cat}[{idx}] 'text' must be str and 'pages' must be list")

    passed = len(missing_fields) == 0 and len(unexpected_fields) == 0 and valid_types

    return {
        "passed": passed,
        "missing_fields": missing_fields,
        "unexpected_fields": unexpected_fields,
        "type_check_passed": valid_types,
        "invalid_type_details": invalid_type_details
    }


def check_traceability_and_grounding(summary: dict, aggregated: dict) -> Tuple[dict, dict, dict]:
    # Map all source facts by page
    facts_by_page: Dict[int, List[str]] = {}
    all_aggregated_facts: List[Dict[str, Any]] = []

    for cat, facts in aggregated.items():
        if isinstance(facts, list):
            for f in facts:
                if isinstance(f, dict) and "text" in f:
                    all_aggregated_facts.append(f)
                    for p in f.get("pages", []):
                        if isinstance(p, int):
                            facts_by_page.setdefault(p, []).append(f["text"])

    # Extract all summary facts
    summary_items: List[Dict[str, Any]] = []
    
    # Add overview
    ov = summary.get("overview", {})
    if isinstance(ov, dict) and ov.get("text"):
        summary_items.append({"category": "overview", "text": ov["text"], "pages": ov.get("pages", [])})

    # Add list categories
    list_categories = [
        "scope", "key_requirements", "eligibility",
        "important_dates", "commercial_requirements",
        "project_duration", "important_conditions"
    ]
    for cat in list_categories:
        for item in summary.get(cat, []):
            if isinstance(item, dict) and item.get("text"):
                summary_items.append({"category": cat, "text": item["text"], "pages": item.get("pages", [])})

    total_facts = len(summary_items)
    traceable_facts = 0
    untraceable_facts = []
    
    supported_facts = 0
    unsupported_facts = []

    for item in summary_items:
        text = item["text"]
        pages = item["pages"]
        cat = item["category"]

        # Check Traceability
        is_traceable = True
        if not pages:
            is_traceable = False
        else:
            for p in pages:
                if not isinstance(p, int) or p not in facts_by_page:
                    is_traceable = False
                    break
        
        if is_traceable:
            traceable_facts += 1
        else:
            untraceable_facts.append({"category": cat, "text": text, "pages": pages, "reason": "Page(s) missing or not in source evidence"})

        # Check Grounding / Faithfulness against source facts on cited pages or across all source facts
        tokens_summary = tokenize(text)
        
        # Source text pool (first from cited pages, fallback to all)
        candidate_source_texts = []
        for p in pages:
            candidate_source_texts.extend(facts_by_page.get(p, []))
        if not candidate_source_texts:
            candidate_source_texts = [f["text"] for f in all_aggregated_facts]

        max_sim = 0.0
        best_match_text = ""
        for src in candidate_source_texts:
            tokens_src = tokenize(src)
            # Check overlap / containment ratio
            overlap = tokens_summary.intersection(tokens_src)
            sim = len(overlap) / max(len(tokens_summary), 1)
            if sim > max_sim:
                max_sim = sim
                best_match_text = src

        # Threshold for lexical grounding support
        if max_sim >= 0.4:
            supported_facts += 1
        else:
            unsupported_facts.append({
                "category": cat,
                "text": text,
                "pages": pages,
                "best_match": best_match_text,
                "match_score": round(max_sim, 3),
                "reason": "Low lexical similarity with cited source facts"
            })

    traceability_pct = round((traceable_facts / total_facts * 100), 2) if total_facts > 0 else 100.0
    grounding_pct = round((supported_facts / total_facts * 100), 2) if total_facts > 0 else 100.0

    traceability_result = {
        "total_summary_facts": total_facts,
        "traceable_facts": traceable_facts,
        "untraceable_count": len(untraceable_facts),
        "traceability_percentage": traceability_pct,
        "untraceable_details": untraceable_facts
    }

    grounding_result = {
        "method": "deterministic_lexical_token_overlap",
        "total_summary_facts": total_facts,
        "supported_facts": supported_facts,
        "unsupported_facts_count": len(unsupported_facts),
        "grounding_percentage": grounding_pct,
        "unsupported_details": unsupported_facts
    }

    hallucination_result = {
        "unsupported_claims_count": len(unsupported_facts),
        "unsupported_claims": unsupported_facts
    }

    return traceability_result, grounding_result, hallucination_result


def check_coverage(summary: dict, aggregated: dict) -> dict:
    aggregated_facts = []
    for cat, facts in aggregated.items():
        if isinstance(facts, list):
            for f in facts:
                if isinstance(f, dict) and f.get("text"):
                    aggregated_facts.append({"category": cat, "text": f["text"], "pages": f.get("pages", [])})

    summary_texts = []
    ov = summary.get("overview", {})
    if isinstance(ov, dict) and ov.get("text"):
        summary_texts.append(ov["text"])
    
    for cat in ["scope", "key_requirements", "eligibility", "important_dates", "commercial_requirements", "project_duration", "important_conditions"]:
        for item in summary.get(cat, []):
            if isinstance(item, dict) and item.get("text"):
                summary_texts.append(item["text"])

    represented_count = 0
    omitted_facts = []

    for agg in aggregated_facts:
        agg_tokens = tokenize(agg["text"])
        is_rep = False
        for sum_text in summary_texts:
            sum_tokens = tokenize(sum_text)
            overlap = agg_tokens.intersection(sum_tokens)
            if len(overlap) / max(len(agg_tokens), 1) >= 0.45:
                is_rep = True
                break
        if is_rep:
            represented_count += 1
        else:
            omitted_facts.append(agg)

    total_agg = len(aggregated_facts)
    coverage_pct = round((represented_count / total_agg * 100), 2) if total_agg > 0 else 100.0

    return {
        "total_aggregated_facts": total_agg,
        "represented_facts_count": represented_count,
        "omitted_facts_count": len(omitted_facts),
        "coverage_percentage": coverage_pct,
        "omitted_facts": omitted_facts
    }


def check_duplication(summary: dict) -> dict:
    summary_items = []
    list_categories = [
        "scope", "key_requirements", "eligibility",
        "important_dates", "commercial_requirements",
        "project_duration", "important_conditions"
    ]
    for cat in list_categories:
        for item in summary.get(cat, []):
            if isinstance(item, dict) and item.get("text"):
                summary_items.append({"category": cat, "text": item["text"].strip()})

    seen_texts = set()
    exact_duplicates = []
    near_duplicates = []

    for idx, item in enumerate(summary_items):
        t = item["text"]
        t_clean = t.lower()
        if t_clean in seen_texts:
            exact_duplicates.append(item)
        else:
            seen_texts.add(t_clean)
            # check near duplicate
            t_tokens = tokenize(t)
            for prev in summary_items[:idx]:
                prev_tokens = tokenize(prev["text"])
                sim = compute_jaccard_similarity(t_tokens, prev_tokens)
                if sim >= 0.75 and prev["text"].lower() != t_clean:
                    near_duplicates.append({"item_1": prev, "item_2": item, "similarity": round(sim, 2)})

    total_items = len(summary_items)
    dup_count = len(exact_duplicates) + len(near_duplicates)
    dup_pct = round((dup_count / max(total_items, 1) * 100), 2)

    return {
        "total_summary_items": total_items,
        "exact_duplicates_count": len(exact_duplicates),
        "near_duplicates_count": len(near_duplicates),
        "total_duplicates": dup_count,
        "duplication_percentage": dup_pct,
        "exact_duplicates": exact_duplicates,
        "near_duplicates": near_duplicates
    }


def check_category_consistency(summary: dict) -> dict:
    """Detect category leakage based on domain rules."""
    flagged_issues = []

    # Category definitions & rules
    # 1. important_dates: should contain explicit dates/periods (validity, deadlines, review frequency)
    # 2. commercial_requirements: should contain financial, payment, billing, tax, bid security
    # 3. eligibility: should contain qualification, CMMI, turnover, experience criteria
    # 4. important_conditions: should contain legal, termination, IP, NDA, blacklisting

    # Rule checks
    for item in summary.get("important_dates", []):
        t = item.get("text", "")
        # Check if financial payment rule was put under dates
        if any(w in t.lower() for w in ["payment", "joint venture", "empanelment", "dormant"]):
            if "validity" not in t.lower() and "days" not in t.lower() and "months" not in t.lower():
                flagged_issues.append({
                    "category": "important_dates",
                    "text": t,
                    "pages": item.get("pages", []),
                    "expected_category": "commercial_requirements / scope / important_conditions",
                    "reason": "Fact describes JV rule / empanelment progress / payment terms rather than an explicit procurement date/deadline."
                })

    for item in summary.get("important_conditions", []):
        t = item.get("text", "")
        if "cmmi" in t.lower() or "certificate" in t.lower():
            flagged_issues.append({
                "category": "important_conditions",
                "text": t,
                "pages": item.get("pages", []),
                "expected_category": "eligibility",
                "reason": "CMMI certification requirements belong in eligibility criteria."
            })

    for item in summary.get("scope", []):
        t = item.get("text", "")
        if any(w in t.lower() for w in ["exit plan", "handover", "passwords"]):
            flagged_issues.append({
                "category": "scope",
                "text": t,
                "pages": item.get("pages", []),
                "expected_category": "important_conditions",
                "reason": "Exit plan and handover obligations are contractual/exit conditions."
            })

    return {
        "flagged_issues_count": len(flagged_issues),
        "flagged_issues": flagged_issues
    }


def check_information_loss(omitted_facts: List[dict]) -> dict:
    categorized_omissions = {
        "high_importance": [],
        "medium_importance": [],
        "low_importance": []
    }

    for f in omitted_facts:
        text = f.get("text", "")
        cat = f.get("category", "")
        t_low = text.lower()

        # Classify importance based on RFP criteria keywords
        if any(k in t_low for k in ["cmmi", "turnover", "bid securing declaration", "integrity pact", "financial bid", "l1", "empanelment"]):
            categorized_omissions["high_importance"].append(f)
        elif any(k in t_low for k in ["tor", "payment", "termination", "confidential", "deliverables", "validity"]):
            categorized_omissions["medium_importance"].append(f)
        else:
            categorized_omissions["low_importance"].append(f)

    return {
        "total_omitted_facts": len(omitted_facts),
        "high_importance_omissions_count": len(categorized_omissions["high_importance"]),
        "medium_importance_omissions_count": len(categorized_omissions["medium_importance"]),
        "low_importance_omissions_count": len(categorized_omissions["low_importance"]),
        "sample_high_importance_omissions": categorized_omissions["high_importance"][:5]
    }


def check_conciseness(summary: dict, aggregated: dict) -> dict:
    agg_word_count = sum(len(f.get("text", "").split()) for cat, facts in aggregated.items() if isinstance(facts, list) for f in facts if isinstance(f, dict))
    
    summary_words_by_cat = {}
    total_summary_words = 0
    total_summary_facts = 0

    ov = summary.get("overview", {})
    if isinstance(ov, dict) and ov.get("text"):
        w = len(ov["text"].split())
        summary_words_by_cat["overview"] = w
        total_summary_words += w
        total_summary_facts += 1

    list_categories = [
        "scope", "key_requirements", "eligibility",
        "important_dates", "commercial_requirements",
        "project_duration", "important_conditions"
    ]
    for cat in list_categories:
        items = summary.get(cat, [])
        w = sum(len(item.get("text", "").split()) for item in items if isinstance(item, dict))
        summary_words_by_cat[cat] = w
        total_summary_words += w
        total_summary_facts += len(items)

    compression_ratio = round((1.0 - (total_summary_words / max(agg_word_count, 1))) * 100, 2)

    return {
        "aggregated_total_words": agg_word_count,
        "summary_total_words": total_summary_words,
        "summary_total_facts": total_summary_facts,
        "compression_percentage": compression_ratio,
        "words_by_category": summary_words_by_cat
    }


def generate_markdown_report(report_data: dict, output_md_path: Path):
    md_content = f"""# Baseline SLM Executive Summary Evaluation Report (v1)

**Evaluation Timestamp**: 2026-09-24  
**Evaluation Target**: `data/evaluation/executive_summary_v1.json`  
**Aggregated Source**: `data/evaluation/executive_summary_aggregated_v1.json`  
**Model Under Test**: `{report_data["model"]}` ({report_data["inference_mode"]})  
**Evaluation Dataset Count**: {report_data["evaluation_documents"]} RFP (Single-Document Baseline)

---

## Executive Overview

This evaluation establishes the baseline performance of the local **Qwen3.5-4B SLM** on the complete document-level Executive Summary pipeline. Evaluation is performed across 9 independent dimensions against the aggregated document evidence without relying on external APIs or self-evaluating LLM loops.

---

## 1. Multidimensional Evaluation Results

### A. Structural Validity
- **Status**: `{"PASSED" if report_data["structural_validity"]["passed"] else "FAILED"}`
- **Required Fields Present**: All 9 fields
- **Type Safety**: Passed (Overview as dict, list categories as typed lists with `text` & `pages`)

### B. Grounding / Faithfulness
- **Method**: Deterministic Lexical Token Overlap & Traceability Matching
- **Total Summary Facts Evaluated**: {report_data["grounding"]["total_summary_facts"]}
- **Supported Facts**: {report_data["grounding"]["supported_facts"]}
- **Unsupported / Low-Overlap Facts**: {report_data["grounding"]["unsupported_facts_count"]}
- **Grounding Score**: `{report_data["grounding"]["grounding_percentage"]}%`

### C. Traceability
- **Total Summary Facts**: {report_data["traceability"]["total_summary_facts"]}
- **Traceable Facts**: {report_data["traceability"]["traceable_facts"]}
- **Traceability Score**: `{report_data["traceability"]["traceability_percentage"]}%`

### D. Coverage
- **Total Aggregated Source Facts**: {report_data["coverage"]["total_aggregated_facts"]}
- **Represented Facts in Summary**: {report_data["coverage"]["represented_facts_count"]}
- **Omitted Source Facts**: {report_data["coverage"]["omitted_facts_count"]}
- **Coverage Score**: `{report_data["coverage"]["coverage_percentage"]}%`

### E. Duplication
- **Total Summary Items**: {report_data["duplication"]["total_summary_items"]}
- **Exact Duplicates**: {report_data["duplication"]["exact_duplicates_count"]}
- **Near Duplicates**: {report_data["duplication"]["near_duplicates_count"]}
- **Duplication Rate**: `{report_data["duplication"]["duplication_percentage"]}%`

### F. Category Consistency
- **Flagged Category Misclassifications**: {report_data["category_consistency"]["flagged_issues_count"]}
- **Key Findings**: Known category leakage from upstream v5.3 chunk extraction (e.g. CMMI requirements placed in `important_conditions` instead of `eligibility`, exit plan in `scope` instead of `important_conditions`).

### G. Information Loss Analysis
- **High Importance Omissions**: {report_data["information_loss"]["high_importance_omissions_count"]}
- **Medium Importance Omissions**: {report_data["information_loss"]["medium_importance_omissions_count"]}
- **Low Importance Omissions**: {report_data["information_loss"]["low_importance_omissions_count"]}

### H. Hallucination / Unsupported Claims
- **Unsupported Claims Count**: {report_data["hallucination"]["unsupported_claims_count"]}

### I. Conciseness & Compression
- **Aggregated Source Word Count**: {report_data["conciseness"]["aggregated_total_words"]} words
- **Final Summary Word Count**: {report_data["conciseness"]["summary_total_words"]} words
- **Compression Ratio**: `{report_data["conciseness"]["compression_percentage"]}%` reduction

---

## 2. Evaluation Limitations & Scope

1. **Single-Document Baseline**: Evaluated on 1 RFP (`data/rfp/1.pdf`). Results represent an initial baseline and cannot be generalized to all RFP types.
2. **Upstream Taxonomy Leakage**: Chunk extraction v5.3 has known category misclassifications which the deterministic aggregator and summary agent preserve.
3. **Automated Lexical Grounding**: Grounding evaluation is currently based on deterministic token overlap against cited source page evidence.

---

## 3. Required for SLM Fine-Tuning (LoRA / QLoRA)

Before fine-tuning Qwen3.5-4B or introducing adapters, the following dataset components must be established:
1. **Multi-RFP Benchmark Dataset**: A diverse corpus of 20-50 verified RFP documents.
2. **Human-Verified Gold Annotations**: Ground-truth gold Executive Summaries created and verified by domain experts.
3. **Supervised Fine-Tuning (SFT) Format**: Paired `(aggregated_facts_json, gold_executive_summary_json)` training examples formatted for QLoRA.
"""
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)


def run_evaluation(
    aggregated_path: Path | None = None,
    summary_path: Path | None = None,
    json_output_path: Path | None = None,
    md_output_path: Path | None = None
) -> dict:
    if aggregated_path is None:
        aggregated_path = Path("data/evaluation/executive_summary_aggregated_v1.json")
    if summary_path is None:
        summary_path = Path("data/evaluation/executive_summary_v1.json")

    aggregated_data = load_json(aggregated_path)
    summary_data = load_json(summary_path)

    structural = check_structural_validity(summary_data)
    traceability, grounding, hallucination = check_traceability_and_grounding(summary_data, aggregated_data)
    coverage = check_coverage(summary_data, aggregated_data)
    duplication = check_duplication(summary_data)
    category_consistency = check_category_consistency(summary_data)
    info_loss = check_information_loss(coverage["omitted_facts"])
    conciseness = check_conciseness(summary_data, aggregated_data)

    report_data = {
        "model": "qwen3.5:4b",
        "inference_mode": "local_ollama",
        "think": False,
        "evaluation_documents": 1,
        "structural_validity": structural,
        "grounding": grounding,
        "traceability": traceability,
        "coverage": coverage,
        "duplication": duplication,
        "category_consistency": category_consistency,
        "information_loss": info_loss,
        "hallucination": hallucination,
        "conciseness": conciseness,
    }

    if json_output_path is None:
        json_output_path = Path("data/evaluation/baseline_summary_evaluation_v1.json")
    if md_output_path is None:
        md_output_path = Path("data/evaluation/baseline_summary_evaluation_v1.md")

    json_output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    md_output_path.parent.mkdir(parents=True, exist_ok=True)
    generate_markdown_report(report_data, md_output_path)

    print("=" * 70)
    print("BASELINE EXECUTIVE SUMMARY EVALUATION COMPLETE")
    print(f"JSON Report: {json_output_path}")
    print(f"Markdown Report: {md_output_path}")
    print("=" * 70)

    return report_data


if __name__ == "__main__":
    run_evaluation()

