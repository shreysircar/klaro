"""Phase 7: export train.jsonl / eval.jsonl, one line per document.

    python -m scripts.golden_export [--include-drafts]

Only auto_checked / verified records are exported unless --include-drafts is given.

Change to_example() if training needs another shape (e.g. aggregated facts as input). Ask first.
"""

import csv
import json
import sys
from collections import Counter

from scripts.golden_lib import ROOT, load_record


def to_example(rec: dict, row: dict) -> dict:
    return {"doc_id": rec["doc_id"], "sector": row["sector"], "split": row["split"], "pages": int(row["pages"]),
            "status": rec["provenance"]["status"],
            "extracted_path": f"data/golden/extracted/{rec['doc_id']}.json", "summary": rec["summary"]}


def main() -> int:
    with open(ROOT / "manifest.csv", newline="", encoding="utf-8") as f:
        rows = {r["doc_id"]: r for r in csv.DictReader(f) if r["status"] == "ok"}
    splits = json.loads((ROOT / "splits.json").read_text(encoding="utf-8"))
    status = Counter()
    for split in ("train", "eval"):
        lines = []
        for doc_id in splits[split]:
            if not (ROOT / "summaries" / f"{doc_id}.json").exists():
                print(f"skip {doc_id}: no summary", file=sys.stderr)
                continue
            rec = load_record(doc_id)
            if rec["provenance"]["status"] == "draft" and "--include-drafts" not in sys.argv:
                print(f"skip {doc_id}: still draft (failed checks)", file=sys.stderr)
                continue
            status[rec["provenance"]["status"]] += 1
            lines.append(json.dumps(to_example(rec, rows[doc_id]), ensure_ascii=False))
        (ROOT / f"{split}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{split}.jsonl: {len(lines)} docs")
    print(dict(status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
