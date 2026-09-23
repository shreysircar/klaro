# Klaro — Initial Baseline Experiment

## Objective

Evaluate a locally running small language model baseline for extracting explicit requirements from RFP documents.

## Model

- Model: Qwen 3.5 4B
- Runtime: Ollama
- Thinking: Disabled
- Output format: JSON
- Prompt version: atomic_requirements_v1
- Processing: chunk-level analysis

## Input Processing

The RFP documents were:

1. Extracted from PDF into page-level text.
2. Preserved with page numbers.
3. Divided into approximately 1800-word chunks.
4. Each chunk was sent independently to the model.

## Requirement Extraction Output

The baseline requested:

```json
{
  "requirements": [
    {
      "text": "...",
      "page": 1,
      "evidence": "..."
    }
  ]
}


