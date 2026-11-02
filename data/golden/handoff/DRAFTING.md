# Drafting brief (spec v1)

The exact procedure each golden summary was drafted with. Every drafter (human or agent) follows it.
The rules are in `docs/golden-summary-spec.md`; this file adds the schema mapping and the workflow.

## Never

- Never run the Klaro app, and never read anything under `data/runs/`, `data/uploads/` or any model
  output. Draft from the extracted PDF text only.
- Never edit files under `scripts/`, `backend/` or other docs' files. Never run git.

## Mapping: spec sections → `ExecutiveSummaryOutput`

| Spec section | Schema field | Notes |
|---|---|---|
| 1 Overview | `overview` `{text, pages}` | 2 to 4 sentences, max 80 words |
| 2 Issuing organization | `issuing_organization` (str) + `issuing_organization_pages` | Legal name; department/office; tender/reference no.; contact office. Max 300 chars, one string, parts separated by `; ` |
| 3 Scope | `scope` | max 8 |
| 4 Key requirements | `key_requirements` | max 10, pass/fail items first |
| 5 Eligibility | `eligibility` | max 8 |
| 6 Timeline: dated events | `important_dates` | one item per dated event (release, pre-bid, query deadline, submission, opening) and bid validity |
| 6 Timeline: durations | `project_duration` | contract duration, extension terms, implementation/delivery milestones and periods |
| 7 Commercial terms | `commercial_requirements` | max 8. EMD, performance security, tender fee, payment terms, price basis, LD/penalties, warranty |
| 8 Evaluation and submission | `important_conditions`, text starts `Evaluation: ` or `Submission: ` | max 8 together |
| 9 Risks and red flags | `important_conditions`, text starts `Risk: ` | max 6 |

Every `important_conditions` item starts with exactly one of `Evaluation: `, `Submission: `, `Risk: `.

## Item rules (on top of the spec)

- `pages` = the extractor's physical page numbers, i.e. the `n` in `--- [PAGE n] ---`, never the
  number printed in the footer. Cite only the page(s) where the fact is actually stated (usually 1, at
  most 3). Page numbers never go in `text`.
- Every digit sequence in `text` (amounts, dates, %, counts, clause refs) must appear verbatim on a
  cited page. Copy numbers in the document's own format (`Rs. 2,50,000/-`, `26.01.2026`, `15:00 hrs`).
  Never compute, convert, total or round. If the document writes "three years", write "three years".
- A fact the document does not state: one item `{"text": "Not specified in the document", "pages": []}`.
  Never leave a list empty. If a document leaves a value blank or "to be notified", say exactly that,
  with the page.
- Mandatory wording (shall, must, required, mandatory, will be rejected) → write "must". Desirable
  wording (should, may, desirable, preferred) → write "desirable" or "preferred".
- Bidder-side obligations only. One fact per item, plain paraphrase, aim for 35 words or fewer.
- Conflicting values: list both, each with its page, and add a `Risk: ` item naming the conflict.
- Corrigenda/addenda inside the same PDF win; note the original value.
- Risks must point at a concrete clause with a page (heavy LD, unlimited liability, short timeline,
  vague scope, unusual IP/data terms, mandatory site visit, conflicts). No generic risks.

## Workflow

Several drafters run in parallel in one shared scratchpad. Every scratch file you create (notes, draft)
MUST have your doc_id in its name, e.g. `<doc_id>_notes.md`, `<doc_id>_draft.json`. `golden_save`
refuses a draft file whose name lacks the doc_id. Never reuse a generic name like `draft.json`.

1. `grep <doc_id> data/golden/manifest.csv` for the page count.
2. Read the document in ranges of about 10 pages:
   `.venv/bin/python -m scripts.golden_pages <doc_id> 1-10` (run from the repo root, with
   `PYTHONDONTWRITEBYTECODE=1`). After each range write short notes (fact + page) to a notes file in
   your scratchpad. Do not hold the whole document in mind; work from the notes. Read every page.
3. Draft the summary JSON (the `ExecutiveSummaryOutput` shape: `overview`, `issuing_organization`,
   `issuing_organization_pages`, `scope`, `key_requirements`, `eligibility`, `important_dates`,
   `commercial_requirements`, `project_duration`, `important_conditions`) to a scratch file.
4. Save: `.venv/bin/python -m scripts.golden_save <doc_id> <draft.json>` (validates with the real model,
   writes `summaries/` and `summaries_md/`, status `draft`).
5. Check: `.venv/bin/python -m scripts.golden_checks <doc_id>`, then read `data/golden/checks/<doc_id>.json`.
   For each flag go back to the cited page and fix the item (wrong page, altered number, wording too far
   from the page). Re-save and re-check until clean. A flag that is a checker false positive and cannot be
   fixed without making the item worse: leave it and report it with the reason.
