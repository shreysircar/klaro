# Klaro golden RFP dataset: handoff

Start here. For training use `train.jsonl` (22 docs) and for evaluation use `eval.jsonl`.

- `train.jsonl`, `eval.jsonl`: one JSON object per line: `doc_id, sector, split, pages, status, extracted_path, summary`.
  `summary` is the app's `ExecutiveSummaryOutput` schema. `extracted_path` points into `extracted/` here
  (strip the `data/golden/` prefix): a list of `{page, text}` using Klaro's own PDF extractor, so page numbers match.
- Eval docs (10) must never be used for training or prompt tuning.
- Status is `auto_checked` for every record: LLM-drafted, passed automatic checks (schema valid, cited pages exist,
  numbers and words found on the cited page). NOT human-verified.
- Input is the extracted text of the whole PDF; the target is `summary`. Longest docs are 111 pages, so check context length.
- `splits.json` (seed, train/eval ids), `manifest.csv` (sector, buyer, source URL, pages, sha256). Source PDFs are not included
  (third-party documents); re-download from `source_url` in the manifest if needed.
- `summaries_md/`: the same summaries as readable markdown. `verifier_notes.md`: conflicts and gaps in each source doc.
- `docs/golden-summary-spec.md`: the writing rules. `DRAFTING.md`: how the 9 sections map onto the schema
  (timeline split into important_dates / project_duration; evaluation, submission and risks live in important_conditions
  with an `Evaluation: ` / `Submission: ` / `Risk: ` prefix).
