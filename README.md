# Klaro

## Klaro — Multilingual Agentic Proposal Analyzer

Klaro is a BTech major project focused on analyzing **RFP (Request for Proposal)** documents using locally deployable **Small Language Models (SLMs)** and agentic workflows.

## Current Focus

The current phase focuses on:

- RFP PDF processing
- Document extraction and chunking
- Local SLM experimentation
- RFP requirement extraction
- Executive Summary generation
- Baseline evaluation

### Planned Agents

1. **Executive Summary Agent**
2. **Requirements Extraction Agent**
3. **Starter Pack Agent**

---

## Tech Stack

- **Python 3.12+**
- **Ollama**
- **Qwen 3.5 4B** — current baseline model
- **PyPDF**
- **JSON-based document processing**

---

## Setup

### 1. Clone the Repository

```bash
git clone <REPOSITORY_URL>
cd klaro
```

### 2. Create a Virtual Environment

#### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 4. Install Ollama

Install Ollama from:

https://ollama.com

Then download the current baseline model:

```powershell
ollama pull qwen3.5:4b
```

Check the installation:

```powershell
ollama list
```

You should see:

```text
qwen3.5:4b
```

---

## Current Architecture

### Workflow Overview

```text
RFP PDF
   ↓
PDF Extraction
   ↓
Page-level Text
   ↓
Chunking
   ↓
Local Qwen 3.5 4B
   ↓
Structured Output
   ↓
Requirement Extraction
   ↓
Evaluation
```

---

## Executive Summary Extension

Eventually, the workflow will extend into:

```text
RFP
 ↓
Document Processing
 ↓
Chunking
 ↓
RFP-specific SLM
 ↓
Structured Information
 ↓
Executive Summary Agent
 ↓
Final Executive Summary
```

---

## Project Structure

```text
klaro/
├── backend/
│   ├── documents/          # PDF extraction, statistics and chunking
│   ├── llm/                # LLM/SLM experiments
│   └── evaluation/         # Evaluation utilities
│
├── data/
│   └── evaluation/         # Sanitized evaluation data
│
├── tests/
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Confidential RFP Data

Actual RFP documents are **not stored in this repository**.

The following directories/files contain confidential RFP data and must remain local:

```text
data/rfp/
data/extracted/
data/chunks/
data/evaluation/gold_requirements.json
data/evaluation/baseline_results.json
```

Raw model outputs containing RFP-derived text must also remain local.

**Do not commit confidential RFP content to GitHub.**

Sanitized evaluation files are provided for shared development.