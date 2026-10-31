"""Regenerate data/golden/README.md with live counts. Rerun after any change.

    python -m scripts.golden_readme
"""

import csv
import json
import statistics as st
from collections import Counter

from scripts.golden_lib import ROOT, SPEC_VERSION

TEXT = """# Golden RFP summaries

{n} English RFP/tender PDFs, each with a golden summary in the app's own summary schema
(`ExecutiveSummaryOutput`, `backend/llm/executive_summary/schema.py`). Built for LoRA fine-tuning of the
summary stage (train split) and for evaluation (eval split, never used for training or prompt tuning).

**Provenance: LLM-drafted, human-verified.** Every summary was drafted by Claude (`claude-code`) from the
extracted PDF text only (the Klaro app was never run on these documents), then passed automatic checks.
A summary is only called `verified` after a named human has checked it against the PDF
(`docs/golden-verification.md`). Until then it is `draft` or `auto_checked` and must not be described as
human-verified.

| status | count |
|---|---|
{status_rows}

Spec: `docs/golden-summary-spec.md` ({spec}). Schema mapping and drafting procedure: `data/golden/DRAFTING.md`.
Drafter notes for verifiers (conflicts and gaps to look at first): `verifier_notes.md`.

## Layout

| path | what |
|---|---|
| `pdfs/<doc_id>.pdf` | source documents (gitignored; refetch with `python -m scripts.golden_collect`) |
| `manifest.csv` | one row per doc: sector, buyer, source_url, pages, sha256, split, status |
| `sources.csv` | the input list for `golden_collect` (urls or local paths) |
| `extracted/<doc_id>.json` | page-numbered text from `backend/documents/pdf_extractor.py` (same page numbers as the app) |
| `summaries/<doc_id>.json` | `{{doc_id, provenance, summary}}`; `summary` validates with `ExecutiveSummaryOutput.model_validate` |
| `summaries_md/<doc_id>.md` | same summary as readable markdown (the file a verifier edits) |
| `checks/<doc_id>.json`, `checks/_table.md` | automatic check results |
| `splits.json` | train / eval doc ids and the seed |
| `train.jsonl`, `eval.jsonl` | export, one line per document (`python -m scripts.golden_export`) |

## Sources and sectors

{sector_rows}

Pages per document: min {pmin}, median {pmed}, mean {pmean:.1f}, max {pmax} (total {ptot}).
Buyers are mostly Indian public bodies (PSUs, banks, ministries, universities, smart-city SPVs), plus
US counties and utilities, Kenya, Uganda, the Philippines, South Africa, the AU and IsDB. Each source URL
is in `manifest.csv`. Documents range 2017 to 2026.

## Split

{n_train} train, {n_eval} eval, stratified by sector, seed {seed} (`scripts/golden_split.py`). Documents that
were used in the earlier benchmark prompt loop or the app demo are forced into train, so eval stays clean.
Eval docs: {eval_ids}.

**Drafted so far:** {n_sum} summaries ({n_eval_sum} eval, {n_train_sum} train). {n_undrafted} train PDFs
are extracted and in the manifest but have no summary (dropped to save drafting cost); `golden_export`
skips them. Undrafted: {undrafted}.

## Mapping onto the schema

The spec has 9 sections; the schema has different fields. Timeline is split into `important_dates`
(dated events) and `project_duration` (periods). Evaluation, submission and risks all live in
`important_conditions`, each item prefixed `Evaluation: `, `Submission: ` or `Risk: `. The schema was not changed.

## Reproduce

```bash
python -m scripts.golden_collect     # fetch + extract (needs data/golden/sources.csv)
python -m scripts.golden_split       # fixes the split once
python -m scripts.golden_checks      # automatic checks, updates draft / auto_checked
python -m scripts.golden_verify <doc_id> "Name"   # after human edits to summaries_md
python -m scripts.golden_export      # train.jsonl / eval.jsonl
```
"""


def main() -> int:
    with open(ROOT / "manifest.csv", newline="", encoding="utf-8") as f:
        ok = [r for r in csv.DictReader(f) if r["status"] == "ok"]
    splits = json.loads((ROOT / "splits.json").read_text(encoding="utf-8"))
    status = Counter({"draft": 0, "auto_checked": 0, "verified": 0})
    for r in ok:
        p = ROOT / "summaries" / f"{r['doc_id']}.json"
        status[json.loads(p.read_text(encoding="utf-8"))["provenance"]["status"] if p.exists() else "no summary"] += 1
    done = {p.stem for p in (ROOT / "summaries").glob("*.json")}
    undrafted = [d for d in splits["train"] if d not in done]
    pages = [int(r["pages"]) for r in ok]
    by_sec = Counter(r["sector"] for r in ok)
    out = TEXT.format(
        n=len(ok), spec=SPEC_VERSION, status_rows="\n".join(f"| {k} | {v} |" for k, v in status.items()),
        sector_rows="| sector | docs | train | eval |\n|---|---|---|---|\n" + "\n".join(
            f"| {s} | {n} | {sum(r['sector'] == s and r['split'] == 'train' for r in ok)} | "
            f"{sum(r['sector'] == s and r['split'] == 'eval' for r in ok)} |" for s, n in sorted(by_sec.items())),
        pmin=min(pages), pmed=st.median(pages), pmean=st.mean(pages), pmax=max(pages), ptot=sum(pages),
        n_train=len(splits["train"]), n_eval=len(splits["eval"]), seed=splits["seed"],
        n_sum=len(done), n_eval_sum=len(done & set(splits["eval"])), n_train_sum=len(done & set(splits["train"])),
        n_undrafted=len(undrafted), undrafted=", ".join(f"`{d}`" for d in undrafted) or "none",
        eval_ids=", ".join(f"`{d}`" for d in splits["eval"]))
    (ROOT / "README.md").write_text(out, encoding="utf-8")
    print(f"wrote {ROOT / 'README.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
