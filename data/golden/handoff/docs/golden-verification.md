# Verifying a golden summary (20 to 25 min per document)

You are checking an LLM-drafted summary against the PDF. Only a human can set a summary to `verified`.
Rules for what a correct summary looks like: `docs/golden-summary-spec.md`. Schema mapping:
`data/golden/DRAFTING.md`. Eval documents (`data/golden/splits.json`) come first and get the most care.

## Setup (once)

From the repo root, with the venv active (`source .venv/bin/activate`, Windows `.venv\Scripts\activate`):

```bash
python -m scripts.golden_checks
```

Pick a document whose status is not `verified` (status is at the top of its markdown file).

## Per document

Open three things side by side:
- the PDF: `data/golden/pdfs/<doc_id>.pdf`
- the summary to edit: `data/golden/summaries_md/<doc_id>.md`
- the automatic check results: `data/golden/checks/<doc_id>.json` (flags to look at first)

**Page numbers are physical pages** (the PDF viewer's page counter, starting at 1), not the number
printed in the footer. If a citation looks off by a few pages, check the viewer counter before you
change it. `python -m scripts.golden_pages <doc_id> 12-14` prints the text our extractor saw.

1. **Flags first (2 min).** Fix or confirm anything listed in the checks file.
2. **Every date and amount (8 min).** For each line that has a number: go to the cited page and
   check that the number is there and means what the line says. Fix the number or the page.
3. **Eligibility and EMD completely (5 min).** Find the eligibility / pre-qualification section and
   the EMD / bid security clause in the PDF. Every pass/fail criterion should be in Eligibility (max 8,
   merge minor ones). EMD amount, form and exemptions should be in Commercial requirements.
4. **Missing big items (5 min).** Skim the table of contents and the NIT/data sheet. Is anything a bid
   manager would need for go/no-go missing: submission deadline, contract length, payment terms,
   performance security, evaluation method (L1 / QCBS weights), penalties / LD, unusual liability?
5. **Mandatory vs desirable, and nothing invented (3 min).** "must" only where the PDF says
   shall/must/mandatory; "Not specified in the document" only where it really is absent.
6. **Save and verify:**

```bash
python -m scripts.golden_verify <doc_id> "Your Name"
```

If it prints check failures, nothing was saved: fix the markdown and run it again. On success it
sets status `verified`, records your name, the time, and a diff of what you changed.

## Editing the markdown

- Keep the `## ` headings exactly as they are.
- One bullet per line starting with `- `. The citation goes at the end: `[p. 12]` or `[pp. 12, 13]`.
- An absent fact is the line `- Not specified in the document` with no citation.
- Important conditions lines start with `Evaluation: `, `Submission: ` or `Risk: `.
- Limits: overview 80 words; scope 8; key requirements 10; eligibility 8; commercial 8;
  Evaluation+Submission 8; Risk 6.

## Reporting

```bash
python -m scripts.golden_verify --report
```

prints bullets changed per verified document (edited / added / removed). That table goes in our
report.
