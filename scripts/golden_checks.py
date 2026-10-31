"""Phase 5: automatic checks on golden summaries. Rerunnable.

    python -m scripts.golden_checks              # all docs with a summary
    python -m scripts.golden_checks it_ippb_tsp  # one doc

Writes data/golden/checks/<doc_id>.json and checks/_table.md. A draft that passes everything becomes
auto_checked; an auto_checked doc that now fails goes back to draft. Never sets verified.
"""

import json
import re
import sys
from collections import Counter

from pydantic import ValidationError

from backend.evaluation.evaluate_summary import compute_jaccard_similarity, tokenize
from backend.llm.executive_summary.schema import ExecutiveSummaryOutput
from scripts.golden_lib import (CONDITION_PREFIXES, LIST_KEYS, NOT_SPECIFIED, ROOT, items, load_pages,
                                load_record, save_record)

LIMITS = {"scope": 8, "key_requirements": 10, "eligibility": 8, "commercial_requirements": 8}
COND_LIMITS = {"Evaluation:": 8, "Submission:": 8, "Risk:": 6}  # spec: eval+submission 8 together, risks 6
OVERVIEW_MAX_WORDS, ORG_MAX_CHARS = 80, 300
GROUNDING_MIN = 0.5
STOP = set("""the and for with that this from are was were been being has have had will shall must should may
can not any all each per its their they them which who whom whose into onto upon under over than then also only
such other more most less least same both either neither bidder bidders vendor contractor""".split())
NUM_RE = re.compile(r"\d+(?:[.,:/-]\d+)*")
QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        "₹": "Rs."})


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s.translate(QUOTES))


def content_words(text: str) -> set[str]:
    # ponytail: 5-char prefix as a poor man's stemmer (deliver/delivery); swap in a real stemmer if noisy
    return {w[:5] for w in tokenize(text.translate(QUOTES)) if w not in STOP and not w.isdigit()}


def check_doc(doc_id: str, summary: dict | None = None) -> dict:
    s = summary if summary is not None else load_record(doc_id)["summary"]
    pages = load_pages(doc_id)
    flags = []

    def flag(kind, section, idx, text, detail):
        flags.append({"type": kind, "section": section, "index": idx, "text": text, "detail": detail})

    try:
        ExecutiveSummaryOutput.model_validate(s)
    except ValidationError as e:
        flag("schema_invalid", None, None, "", str(e))
        return {"doc_id": doc_id, "passed": False, "flags": flags}

    seen: list[tuple[str, int, set[str], str]] = []
    for sec, idx, text, cited in items(s):
        if not text.strip():
            flag("empty_text", sec, idx, text, "empty item")
            continue
        if NOT_SPECIFIED in text:
            # Pure absence statement: no page expected. Mixed item (absence plus a related fact on a cited
            # page): keep going and ground the rest of the text.
            text = re.sub(re.escape(NOT_SPECIFIED) + r"\.?", "", text).strip(" :;,-")
            if not cited:
                continue
        if not cited:
            flag("no_page", sec, idx, text, "every item needs a page")
            continue
        bad = [p for p in cited if p not in pages]
        if bad:
            flag("page_out_of_range", sec, idx, text, f"pages {bad} not in 1..{len(pages)}")
            continue

        on_page = squash(" ".join(pages[p] for p in cited))
        missing = [n for n in NUM_RE.findall(text.translate(QUOTES)) if n not in on_page]
        if missing:
            flag("number_not_on_page", sec, idx, text, f"{missing} not on p.{cited}")

        near = " ".join(pages.get(q, "") for p in cited for q in (p - 1, p, p + 1))
        words = content_words(text)
        if words:
            hit = len(words & content_words(near)) / len(words)
            if hit < GROUNDING_MIN:
                flag("low_grounding", sec, idx, text,
                     f"{hit:.0%} content words on cited page±1; missing {sorted(words - content_words(near))[:8]}")

        toks = tokenize(text)
        for psec, pidx, ptoks, ptext in seen:
            if squash(text.lower()) == squash(ptext.lower()) or compute_jaccard_similarity(toks, ptoks) >= 0.8:
                flag("duplicate", sec, idx, text, f"duplicates {psec}[{pidx}]")
                break
        seen.append((sec, idx, toks, text))

    ov_words = len(s["overview"]["text"].split())
    if ov_words > OVERVIEW_MAX_WORDS:
        flag("over_limit", "overview", 0, "", f"{ov_words} words > {OVERVIEW_MAX_WORDS}")
    if len(s["issuing_organization"]) > ORG_MAX_CHARS:
        flag("over_limit", "issuing_organization", 0, "", f"{len(s['issuing_organization'])} chars > {ORG_MAX_CHARS}")
    for key, limit in LIMITS.items():
        if len(s[key]) > limit:
            flag("over_limit", key, None, "", f"{len(s[key])} items > {limit}")
    conds = s["important_conditions"]
    for prefix, limit in COND_LIMITS.items():
        n = sum(c["text"].startswith(prefix) for c in conds)
        if prefix != "Submission:" and n > limit:
            flag("over_limit", "important_conditions", None, "", f"{n} '{prefix}' items > {limit}")
    n_eval_sub = sum(c["text"].startswith(("Evaluation:", "Submission:")) for c in conds)
    if n_eval_sub > COND_LIMITS["Evaluation:"]:
        flag("over_limit", "important_conditions", None, "", f"{n_eval_sub} Evaluation+Submission items > 8")
    for i, c in enumerate(conds):
        if not c["text"].startswith(CONDITION_PREFIXES):
            flag("bad_condition_prefix", "important_conditions", i, c["text"], f"must start with {CONDITION_PREFIXES}")
    for key in LIST_KEYS:
        if not s[key]:
            flag("empty_section", key, None, "", f"use '{NOT_SPECIFIED}' instead of an empty section")

    return {"doc_id": doc_id, "passed": not flags, "flags": flags}


def sync_md_status(doc_id: str, status: str) -> None:
    """Update only the status in the markdown header, so human edits in the file survive."""
    md = ROOT / "summaries_md" / f"{doc_id}.md"
    if md.exists():
        text = md.read_text(encoding="utf-8")
        md.write_text(re.sub(r"<!-- status: \w+", f"<!-- status: {status}", text, count=1), encoding="utf-8")


def main(doc_ids: list[str]) -> int:
    (ROOT / "checks").mkdir(exist_ok=True)
    if not doc_ids:
        doc_ids = sorted(p.stem for p in (ROOT / "summaries").glob("*.json"))
    for doc_id in doc_ids:
        res = check_doc(doc_id)
        (ROOT / "checks" / f"{doc_id}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                                                        encoding="utf-8")
        rec = load_record(doc_id)
        status = rec["provenance"]["status"]
        if res["passed"] and status == "draft":
            rec["provenance"]["status"] = "auto_checked"
        elif not res["passed"] and status == "auto_checked":
            rec["provenance"]["status"] = "draft"
        if rec["provenance"]["status"] != status and not (res["flags"] and res["flags"][0]["type"] == "schema_invalid"):
            save_record(rec)
        sync_md_status(doc_id, rec["provenance"]["status"])

    # dataset-wide table, rebuilt from every checks file so partial reruns keep the full picture
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "checks").glob("*.json"))]
    kinds = sorted({f["type"] for r in results for f in r["flags"]})
    lines = ["| doc | passed | " + " | ".join(kinds) + " |", "|---|---|" + "---|" * len(kinds)]
    total = Counter()
    for r in results:
        c = Counter(f["type"] for f in r["flags"])
        total += c
        lines.append(f"| {r['doc_id']} | {'yes' if r['passed'] else 'no'} | " + " | ".join(str(c[k]) for k in kinds) + " |")
    lines.append(f"| **total** | {sum(r['passed'] for r in results)}/{len(results)} | "
                 + " | ".join(str(total[k]) for k in kinds) + " |")
    (ROOT / "checks" / "_table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
