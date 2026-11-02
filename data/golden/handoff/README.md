# Golden RFP summaries

45 English RFP/tender PDFs, each with a golden summary in the app's own summary schema
(`ExecutiveSummaryOutput`, `backend/llm/executive_summary/schema.py`). Built for LoRA fine-tuning of the
summary stage (train split) and for evaluation (eval split, never used for training or prompt tuning).

**Provenance: LLM-drafted, human-verified.** Every summary was drafted by Claude (`claude-code`) from the
extracted PDF text only (the Klaro app was never run on these documents), then passed automatic checks.
A summary is only called `verified` after a named human has checked it against the PDF
(`docs/golden-verification.md`). Until then it is `draft` or `auto_checked` and must not be described as
human-verified.

| status | count |
|---|---|
| draft | 0 |
| auto_checked | 32 |
| verified | 0 |
| no summary | 13 |

Spec: `docs/golden-summary-spec.md` (v1). Schema mapping and drafting procedure: `data/golden/DRAFTING.md`.
Drafter notes for verifiers (conflicts and gaps to look at first): `verifier_notes.md`.

## Layout

| path | what |
|---|---|
| `pdfs/<doc_id>.pdf` | source documents (gitignored; refetch with `python -m scripts.golden_collect`) |
| `manifest.csv` | one row per doc: sector, buyer, source_url, pages, sha256, split, status |
| `sources.csv` | the input list for `golden_collect` (urls or local paths) |
| `extracted/<doc_id>.json` | page-numbered text from `backend/documents/pdf_extractor.py` (same page numbers as the app) |
| `summaries/<doc_id>.json` | `{doc_id, provenance, summary}`; `summary` validates with `ExecutiveSummaryOutput.model_validate` |
| `summaries_md/<doc_id>.md` | same summary as readable markdown (the file a verifier edits) |
| `checks/<doc_id>.json`, `checks/_table.md` | automatic check results |
| `splits.json` | train / eval doc ids and the seed |
| `train.jsonl`, `eval.jsonl` | export, one line per document (`python -m scripts.golden_export`) |

## Sources and sectors

| sector | docs | train | eval |
|---|---|---|---|
| Banking/finance | 6 | 5 | 1 |
| Construction/civil | 5 | 4 | 1 |
| Consulting/international | 7 | 5 | 2 |
| Education | 5 | 4 | 1 |
| Energy/utilities | 5 | 4 | 1 |
| Healthcare | 5 | 4 | 1 |
| IT | 8 | 6 | 2 |
| Municipal/smart city | 4 | 3 | 1 |

Pages per document: min 21, median 57, mean 57.4, max 111 (total 2583).
Buyers are mostly Indian public bodies (PSUs, banks, ministries, universities, smart-city SPVs), plus
US counties and utilities, Kenya, Uganda, the Philippines, South Africa, the AU and IsDB. Each source URL
is in `manifest.csv`. Documents range 2017 to 2026.

## Split

35 train, 10 eval, stratified by sector, seed 2026 (`scripts/golden_split.py`). Documents that
were used in the earlier benchmark prompt loop or the app demo are forced into train, so eval stays clean.
Eval docs: `bfsi_centralbank_sharetrading`, `civil_crpf_works`, `edu_iimtrichy_branding`, `energy_jreda_minigrid`, `health_wmchealth_epic`, `intl_kdc_culture`, `intl_santafe_bess`, `it_sikkim_smsda`, `it_trai_uccapp`, `muni_ndmc_mswconsult`.

**Drafted so far:** 32 summaries (10 eval, 22 train). 13 train PDFs
are extracted and in the manifest but have no summary (dropped to save drafting cost); `golden_export`
skips them. Undrafted: `health_nhmodisha_phc`, `health_vmmcsjh_ivfluid`, `intl_au_aeis`, `intl_dbsa_sapo`, `intl_isdb_bcc051`, `intl_pids_doheval`, `it_hpsedc_softdev`, `it_ibps_rpa`, `it_meghalaya_slmportal`, `it_mpcb_mobileapp`, `it_ocac_pmksyportal`, `muni_bscl_cctv`, `muni_nashikmc_cleaning`.

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
