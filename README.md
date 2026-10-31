# Klaro

## Klaro — Multilingual Agentic Proposal Analyzer

Klaro is a major project focused on analyzing **RFP (Request for Proposal)** documents using locally deployable **Small Language Models (SLMs)** and agentic workflows.

---

## Quick start (desktop app)

You need: **Python 3.11+** (3.12 or 3.13 recommended), **Node.js 22.12+**, and **[Ollama](https://ollama.com/download)**
running. Then, once:

```bash
ollama pull qwen3.5:4b
```

From the repo root (same on macOS and Windows PowerShell):

```bash
npm install
npm run dev
```

`npm install` also installs the Electron app's packages. `npm run dev` first runs the setup script (`npm run setup`,
safe to repeat), then opens the app:

| Step | What it does | First run |
|---|---|---|
| 1-2 | finds Python 3.11+, creates `.venv` | seconds |
| 3 | `pip install -r requirements.txt` (only when that file changes) | several minutes, about 1 GB (PyTorch) |
| 4 | downloads the German to English model `Helsinki-NLP/opus-mt-de-en` into `models/` | one time, about 310 MB |
| 5 | checks that Ollama is running and has the model; prints the fix if not, never blocks | seconds |

The setup script is the only thing in Klaro that uses the internet (PyPI and huggingface.co). Once it has run, the app works
offline: nothing leaves the machine. `KLARO_SKIP_SETUP=1 npm run dev` skips it.

**German RFPs:** drop the PDF in as usual. The app detects German, offers an Auto / German / English selector, translates
on this computer, and analyses the English text. Page numbers and highlights refer to the original PDF; the English tab shows
the translation placed over the original layout. On Windows, PyTorch needs the
[Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe).

**Tests:** `npm test` (renderer tests, then the Python tests).

**When something breaks**, send me: the screenshot, `<userData>/logs/backend.log` (macOS: `~/Library/Application
Support/klaro/logs/`, Windows: `%APPDATA%\klaro\logs\`), and for a failed run its `pipeline.log` (in `data/runs/<run id>/`).
Windows testers: follow `docs/windows-test-checklist.md`.

---

## Current Status & Achievements

As of the latest milestone, the **Baseline Executive Summary Pipeline** is fully implemented, evaluated, rendered, and packaged into a single reproducible end-to-end CLI workflow.

### What Works

1. **Document Processing Pipeline**:
   - **PDF Extraction**: Extracts page-by-page text using `pypdf` (`backend/documents/pdf_extractor.py`).
   - **Document Statistics**: Computes character, word, and estimated token metrics (`backend/documents/document_stats.py`).
   - **Section-Aware Chunking**: Creates ~1800-word overlapping chunks (`backend/documents/chunker.py`).

2. **Executive Summary Pipeline**:
   - **Two-Pass Chunk Extraction (v5.3)**: Extracts factual (Pass A) and commercial/contractual (Pass B) information per chunk (`backend/llm/executive_summary/chunk_analyzer.py`).
   - **Deterministic Aggregator (v1)**: Combines chunk-level facts, deduplicates near-identical items, and aggregates unique page references (`backend/llm/executive_summary/aggregator.py`).
   - **Executive Summary Agent (v1)**: Synthesizes aggregated facts into a structured 9-category executive summary JSON using local `Qwen3.5-4B` (`backend/llm/executive_summary/agent.py`).

3. **Human-Readable Presentation Layer**:
   - **Summary Renderer**: Generates clean Markdown (`.md`) and styled, responsive HTML (`.html`) reports with page-level traceability pills without altering facts (`backend/llm/executive_summary/render_summary.py`).

4. **Baseline Evaluation Framework**:
   - **9-Dimensional Evaluator**: Programmatically evaluates structural validity, grounding (100%), traceability (100%), coverage, duplication, category leakage, information loss, hallucinations, and compression ratio (`backend/evaluation/evaluate_summary.py`).

5. **End-to-End Orchestration CLI**:
   - **Reproducible Workflow**: Runs the complete 7-stage baseline pipeline end-to-end on any RFP PDF with a single CLI command (`backend/workflow/run_rfp.py`).

---

## Architecture & Data Flow

```text
RFP PDF
  ↓
Stage 1: PDF Extraction (pypdf)
  ↓
Stage 2: Section-Aware Chunking (~1800 words/chunk)
  ↓
Stage 3: Two-Pass Qwen3.5-4B Analysis (Pass A + Pass B per chunk)
  ↓
Stage 4: Deterministic Aggregation & Page Deduplication
  ↓
Stage 5: Executive Summary Agent (Qwen3.5-4B JSON synthesis)
  ↓
Stage 6: 9-Dimensional Baseline Evaluation
  ↓
Stage 7: Markdown & HTML Presentation Renderer
  ↓
Self-Contained Run Artifacts (data/runs/<run_id>/)
```

---

## Quick Start Guide for Next Contributors

### Prerequisites

- **OS**: Windows / Linux / macOS
- **Python**: 3.11+
- **Ollama**: Installed and running locally

---

### Step 1: Set Up Environment

```powershell
# Clone the repository
git clone <REPOSITORY_URL>
cd klaro

# Create and activate Python virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # On Linux/macOS: source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

### Step 2: Set Up Local Ollama & Qwen Model

1. Download and install Ollama from [https://ollama.com](https://ollama.com).
2. Ensure Ollama is running (check system tray or run `ollama list`).
3. Pull the baseline Qwen3.5 4B model:

```powershell
ollama pull qwen3.5:4b
```

Verify that `qwen3.5:4b` appears in the list:

```powershell
ollama list
```

---

### Step 3: Run the Complete Baseline Pipeline on an RFP

Place your target RFP PDF in `data/rfp/` (or any path), then execute the unified workflow CLI:

```powershell
.\.venv\Scripts\python.exe -m backend.workflow.run_rfp data/rfp/1.pdf
```

#### Custom Output Directory or Run ID

```powershell
.\.venv\Scripts\python.exe -m backend.workflow.run_rfp path/to/my_rfp.pdf --run-id my_custom_run
```

---

### Step 4: Inspect Run Artifacts

The workflow automatically creates a unique self-contained run folder under `data/runs/<run_id>/`:

```text
data/runs/<run_id>/
├── input/
│   └── 1.pdf                              # Source RFP copy
├── extracted/
│   └── 1.json                             # Page-by-page text
├── chunks/
│   └── 1.json                             # Section-aware text chunks
├── extraction/
│   └── executive_summary_chunks_v5_3.json # Two-pass chunk extraction results
├── aggregation/
│   └── executive_summary_aggregated_v1.json # Merged document facts
├── summary/
│   ├── executive_summary.json            # Machine-readable Executive Summary JSON
│   ├── executive_summary.md              # Human-readable Markdown summary
│   └── executive_summary.html            # Browser-viewable HTML summary report
├── evaluation/
│   ├── baseline_summary_evaluation.json  # 9-dimensional evaluation data
│   └── baseline_summary_evaluation.md    # Human-readable evaluation report
└── run_metadata.json                     # Execution metadata, SHA256 hash & timings
```

---

### Step 5: Run Unit Tests

To verify that all renderer and workflow orchestration components work cleanly:

```powershell
.\.venv\Scripts\python.exe -m unittest backend/evaluation/test_workflow.py backend/evaluation/test_render_summary.py
```

---

## Canonical Schemas

### Executive Summary Output Schema (9 Fields)

All executive summary outputs strictly adhere to this schema:

```json
{
  "overview": {
    "text": "High-level summary of what the RFP is for...",
    "pages": [9, 30]
  },
  "issuing_organization": "National Informatics Centre Services Inc. (NICSI)",
  "scope": [
    { "text": "Design, Development, Implementation and Maintenance...", "pages": [30, 34] }
  ],
  "key_requirements": [
    { "text": "Bidder must submit Bid Securing Declaration...", "pages": [84] }
  ],
  "eligibility": [
    { "text": "Bidder must possess valid CMMI Level-3 or Level-5 certification...", "pages": [83] }
  ],
  "important_dates": [
    { "text": "Bid must be valid for 120 days from submission deadline...", "pages": [31] }
  ],
  "commercial_requirements": [
    { "text": "Billing on Time & Material basis...", "pages": [45] }
  ],
  "project_duration": [],
  "important_conditions": [
    { "text": "Confidentiality obligations apply...", "pages": [56] }
  ]
}
```

---

## Confidentiality & Git Security Notice

Actual RFP documents contain confidential procurement details. **Never commit raw RFP files or extracted text to GitHub.**

The following paths are excluded via `.gitignore`:

```text
data/rfp/
data/extracted/
data/chunks/
data/runs/
```

Keep all raw PDF and model output artifacts local.

---

## Next Milestone Focus (For Future Contributors)

Now that the baseline Executive Summary pipeline is frozen and reproducible:

1. **Multi-RFP Benchmark Expansion**: Run `backend.workflow.run_rfp` across 20–50 additional RFPs to build an evaluation corpus.
2. **Requirements Extraction Agent**: Build the second core agent (extracting tabular requirement sheets from RFP sections).
3. **Starter Pack Agent**: Build the compliance checklist and response template generator.
4. **Fine-Tuning Data Preparation**: Prepare SFT `(aggregated_facts, gold_summary)` pairs for future QLoRA training once human-annotated gold data is available.