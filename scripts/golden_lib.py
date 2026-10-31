"""Shared bits for the golden dataset scripts: paths, record I/O, markdown round trip.

Record on disk (data/golden/summaries/<doc_id>.json):
    {"doc_id": str, "provenance": {...}, "summary": <ExecutiveSummaryOutput dict>}
"""

import json
import re
from pathlib import Path

from backend.llm.executive_summary.schema import ExecutiveSummaryOutput

ROOT = Path("data/golden")
SPEC_VERSION = "v1"
NOT_SPECIFIED = "Not specified in the document"
# important_conditions holds three spec sections (the schema has no separate field for them).
CONDITION_PREFIXES = ("Evaluation:", "Submission:", "Risk:")

# (schema key, markdown heading). Same order as the app's renderer.
SECTIONS = [
    ("overview", "Overview"),
    ("issuing_organization", "Issuing organization"),
    ("scope", "Scope"),
    ("key_requirements", "Key requirements"),
    ("eligibility", "Eligibility"),
    ("important_dates", "Important dates"),
    ("commercial_requirements", "Commercial requirements"),
    ("project_duration", "Project duration"),
    ("important_conditions", "Important conditions"),
]
LIST_KEYS = [k for k, _ in SECTIONS[2:]]


def load_record(doc_id: str) -> dict:
    return json.loads((ROOT / "summaries" / f"{doc_id}.json").read_text(encoding="utf-8"))


def save_record(rec: dict) -> None:
    ExecutiveSummaryOutput.model_validate(rec["summary"])  # never write an invalid summary
    path = ROOT / "summaries" / f"{rec['doc_id']}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(rec: dict) -> None:
    (ROOT / "summaries_md").mkdir(exist_ok=True)
    (ROOT / "summaries_md" / f"{rec['doc_id']}.md").write_text(to_markdown(rec), encoding="utf-8")


def load_pages(doc_id: str) -> dict[int, str]:
    pages = json.loads((ROOT / "extracted" / f"{doc_id}.json").read_text(encoding="utf-8"))
    return {p["page"]: p["text"] for p in pages}


def items(summary: dict):
    """Yield (section, index, text, pages) for every citable item, overview first."""
    yield "overview", 0, summary["overview"]["text"], summary["overview"]["pages"]
    yield "issuing_organization", 0, summary["issuing_organization"], summary.get("issuing_organization_pages", [])
    for key in LIST_KEYS:
        for i, it in enumerate(summary.get(key, [])):
            yield key, i, it["text"], it["pages"]


def _cite(pages: list[int]) -> str:
    if not pages:
        return ""
    return f" [p. {pages[0]}]" if len(pages) == 1 else f" [pp. {', '.join(map(str, pages))}]"


def to_markdown(rec: dict) -> str:
    s, prov = rec["summary"], rec["provenance"]
    out = [f"# {rec['doc_id']}", "",
           f"<!-- status: {prov['status']} | spec {prov['spec_version']} | Edit text and the [p. N] / [pp. N, M] "
           f"citation at the end of each line. Keep headings. A line with no citation = no page. -->", ""]
    out += ["## Overview", "", s["overview"]["text"] + _cite(s["overview"]["pages"]), ""]
    out += ["## Issuing organization", "", s["issuing_organization"] + _cite(s.get("issuing_organization_pages", [])), ""]
    for key, title in SECTIONS[2:]:
        out += [f"## {title}", ""]
        out += [f"- {it['text']}{_cite(it['pages'])}" for it in s.get(key, [])]
        out.append("")
    return "\n".join(out)


CITE_RE = re.compile(r"\s*\[pp?\.\s*([\d,\s]+)\]\s*$")


def _split_cite(line: str) -> tuple[str, list[int]]:
    m = CITE_RE.search(line)
    if not m:
        return line.strip(), []
    return line[:m.start()].strip(), [int(x) for x in re.findall(r"\d+", m.group(1))]


def from_markdown(md: str) -> dict:
    """Inverse of to_markdown. Raises ValueError on an unknown heading."""
    titles = {t.lower(): k for k, t in SECTIONS}
    blocks: dict[str, list[str]] = {}
    current = None
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            current = titles.get(line[3:].strip().lower())
            if current is None:
                raise ValueError(f"unknown section heading: {line!r}")
            blocks[current] = []
        elif current and line.strip() and not line.lstrip().startswith("<!--"):
            blocks[current].append(line)

    def para(key: str) -> tuple[str, list[int]]:
        return _split_cite(" ".join(l.strip() for l in blocks.get(key, [])))

    ov_text, ov_pages = para("overview")
    org, org_pages = para("issuing_organization")
    summary = {"overview": {"text": ov_text, "pages": ov_pages},
               "issuing_organization": org, "issuing_organization_pages": org_pages}
    for key in LIST_KEYS:
        bullets: list[str] = []
        for line in blocks.get(key, []):
            if line.lstrip().startswith("- "):
                bullets.append(line.lstrip()[2:])
            elif bullets:  # wrapped continuation line
                bullets[-1] += " " + line.strip()
        summary[key] = [dict(zip(("text", "pages"), _split_cite(b))) for b in bullets]
    return ExecutiveSummaryOutput.model_validate(summary).model_dump()


if __name__ == "__main__":  # round-trip self-check
    s = {"overview": {"text": "Buyer X wants Y.", "pages": [1, 2]}, "issuing_organization": "X Ltd, ref 12/A",
         "issuing_organization_pages": [1], "scope": [{"text": "Supply 5 units", "pages": [4]}],
         "key_requirements": [], "eligibility": [{"text": NOT_SPECIFIED, "pages": []}], "important_dates": [],
         "commercial_requirements": [{"text": "EMD Rs. 50,000/- [sic]", "pages": [7]}], "project_duration": [],
         "important_conditions": [{"text": "Risk: unlimited liability", "pages": [9, 10]}]}
    rec = {"doc_id": "t", "provenance": {"status": "draft", "spec_version": "v1"}, "summary": s}
    assert from_markdown(to_markdown(rec)) == ExecutiveSummaryOutput.model_validate(s).model_dump()
    print("ok")
