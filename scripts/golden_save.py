"""Save a drafted summary as a golden record (Phase 4). Validates with the app's real Pydantic model.

    python -m scripts.golden_save <doc_id> <draft_summary.json>

Writes summaries/<doc_id>.json (status "draft") and summaries_md/<doc_id>.md.
Refuses to overwrite a verified record.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.llm.executive_summary.schema import ExecutiveSummaryOutput
from scripts.golden_lib import ROOT, SPEC_VERSION, load_pages, save_record, write_markdown


def main(doc_id: str, draft_path: str) -> int:
    load_pages(doc_id)  # the doc must be extracted (and so in the manifest as ok)
    if doc_id not in Path(draft_path).name:  # parallel drafters share a scratchpad; generic names collide
        print(f"draft file name must contain the doc_id ({doc_id}); got {Path(draft_path).name}")
        return 1
    summary = ExecutiveSummaryOutput.model_validate(
        json.loads(Path(draft_path).read_text(encoding="utf-8"))).model_dump()
    out = ROOT / "summaries" / f"{doc_id}.json"
    if out.exists() and json.loads(out.read_text(encoding="utf-8"))["provenance"]["status"] == "verified":
        print(f"{doc_id} is verified by a human; edit summaries_md and use golden_verify instead.")
        return 1
    out.parent.mkdir(exist_ok=True)
    rec = {"doc_id": doc_id,
           "provenance": {"drafted_by": "claude-code",
                          "drafted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "spec_version": SPEC_VERSION, "status": "draft",
                          "verified_by": None, "verified_at": None, "verification_changes": None},
           "summary": summary}
    save_record(rec)
    write_markdown(rec)
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
