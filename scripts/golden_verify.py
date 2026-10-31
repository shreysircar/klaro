"""Phase 6: record a human verification.

    python -m scripts.golden_verify <doc_id> "<verifier name>"
    python -m scripts.golden_verify --report        # bullets changed per verified doc

Re-parses the edited summaries_md/<doc_id>.md into the schema, reruns the automatic checks on it and,
only if they all pass, sets status "verified" with verified_by, verified_at and a diff of what changed.
On failure nothing is written to the JSON; fix the markdown and rerun.
"""

import difflib
import sys
from datetime import datetime, timezone

from scripts import golden_checks
from scripts.golden_lib import (LIST_KEYS, ROOT, from_markdown, load_record, save_record, to_markdown,
                                write_markdown)


def _lines(summary: dict) -> dict[str, list[str]]:
    out = {"overview": [f"{summary['overview']['text']} {summary['overview']['pages']}"],
           "issuing_organization": [f"{summary['issuing_organization']} {summary.get('issuing_organization_pages', [])}"]}
    out |= {k: [f"{it['text']} {it['pages']}" for it in summary[k]] for k in LIST_KEYS}
    return out


def diff_summaries(old: dict, new: dict) -> dict:
    """Bullet-level change counts. A changed page list counts as an edit."""
    counts = {"edited": 0, "added": 0, "removed": 0}
    per_section = {}
    a, b = _lines(old), _lines(new)
    for key in a:
        sec = {"edited": 0, "added": 0, "removed": 0}
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a[key], b[key], autojunk=False).get_opcodes():
            if tag == "replace":
                n = min(i2 - i1, j2 - j1)
                sec["edited"] += n
                sec["removed"] += (i2 - i1) - n
                sec["added"] += (j2 - j1) - n
            elif tag == "delete":
                sec["removed"] += i2 - i1
            elif tag == "insert":
                sec["added"] += j2 - j1
        if any(sec.values()):
            per_section[key] = sec
        for k in counts:
            counts[k] += sec[k]
    return counts | {"bullets_changed": sum(counts.values()), "per_section": per_section}


def verify(doc_id: str, verifier: str) -> int:
    rec = load_record(doc_id)
    md_path = ROOT / "summaries_md" / f"{doc_id}.md"
    edited = from_markdown(md_path.read_text(encoding="utf-8"))
    before = rec["summary"]

    res = golden_checks.check_doc(doc_id, edited)
    if not res["passed"]:
        print(f"{doc_id}: {len(res['flags'])} check failures, NOT verified. Fix {md_path} and rerun.")
        for f in res["flags"]:
            print(f"  [{f['type']}] {f['section']}[{f['index']}] {f['detail']}\n      {f['text'][:120]}")
        return 1

    changes = diff_summaries(before, edited)
    changes["markdown_diff"] = "".join(difflib.unified_diff(
        to_markdown(rec).splitlines(keepends=True), to_markdown(rec | {"summary": edited}).splitlines(keepends=True),
        "drafted", "verified"))
    rec["summary"] = edited
    rec["provenance"] |= {"status": "verified", "verified_by": verifier,
                          "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "verification_changes": changes}
    save_record(rec)
    write_markdown(rec)
    golden_checks.main([doc_id])
    print(f"{doc_id}: verified by {verifier}; bullets changed {changes['bullets_changed']} "
          f"(edited {changes['edited']}, added {changes['added']}, removed {changes['removed']})")
    return 0


def report() -> int:
    rows = []
    for p in sorted((ROOT / "summaries").glob("*.json")):
        rec = load_record(p.stem)
        ch = rec["provenance"].get("verification_changes")
        if rec["provenance"]["status"] == "verified" and ch:
            rows.append((p.stem, rec["provenance"]["verified_by"], ch["bullets_changed"], ch["edited"],
                         ch["added"], ch["removed"]))
    print("| doc | verifier | bullets changed | edited | added | removed |\n|---|---|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(map(str, r)) + " |")
    if rows:
        print(f"\n{len(rows)} verified docs, mean bullets changed {sum(r[2] for r in rows) / len(rows):.1f}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--report"]:
        sys.exit(report())
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(verify(sys.argv[1], sys.argv[2]))
