"""Shared bits of the fine-tuning kit: paths, the exact training prompt, hashes, token estimates.

The training input must be byte-for-byte what backend/llm/executive_summary/agent.py sends at inference,
so the prompt pieces are imported from the app, never copied.
"""

import hashlib
import json
from pathlib import Path

from backend.llm.executive_summary.prompts import EXECUTIVE_SUMMARY_AGENT_SYSTEM_PROMPT, build_agent_user_prompt
from backend.llm.executive_summary.schema import ExecutiveSummaryOutput

ROOT = Path("data/golden")
FACTS_DIR = ROOT / "facts"
SFT_DIR = ROOT / "sft"
EVAL_RUNS_DIR = ROOT / "eval_runs"
ADAPTERS_DIR = Path("models/adapters")

# Hugging Face repo of the weights behind Ollama's qwen3.5:4b (same architecture, 4.7B parameters, vision + thinking).
BASE_MODEL_ID = "Qwen/Qwen3.5-4B"
SMOKE_MODEL_ID = "Qwen/Qwen3.5-0.8B"  # smallest chat model of the same family, for the pipeline smoke test
OLLAMA_BASE_TAG = "qwen3.5:4b"
INFERENCE_OPTIONS = {"temperature": 0.1}  # agent.py: think=False, no format, no num_ctx
USABLE_STATUS = ("auto_checked", "verified")

# Keys the agent is asked to return (see the prompt). issuing_organization_pages is not one of them:
# agent.py fills it in from the aggregator after the model answers.
TARGET_KEYS = ["overview", "issuing_organization", "scope", "key_requirements", "eligibility", "important_dates",
               "commercial_requirements", "project_duration", "important_conditions"]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)  # never leave a half-written file behind


def splits() -> dict[str, list[str]]:
    s = read_json(ROOT / "splits.json")
    return {"train": list(s["train"]), "eval": list(s["eval"])}


def manifest_rows() -> dict[str, dict]:
    import csv

    with open(ROOT / "manifest.csv", encoding="utf-8", newline="") as f:
        return {r["doc_id"]: r for r in csv.DictReader(f)}


def golden_record(doc_id: str) -> dict | None:
    path = ROOT / "summaries" / f"{doc_id}.json"
    return read_json(path) if path.is_file() else None


def target_text(summary: dict) -> str:
    """The raw JSON the agent should answer with: the prompt's schema, nothing else."""
    ExecutiveSummaryOutput.model_validate(summary)  # raises on an invalid golden summary
    return json.dumps({k: summary[k] for k in TARGET_KEYS}, ensure_ascii=False, indent=2)


def facts_messages(aggregated: dict) -> list[dict]:
    """[system, user] exactly as the summary agent builds them."""
    aggregated_json = json.dumps(aggregated, indent=2, ensure_ascii=False)
    return [
        {"role": "system", "content": EXECUTIVE_SUMMARY_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": build_agent_user_prompt(aggregated_json)},
    ]


CHARS_PER_TOKEN = 3.8  # measured against Ollama on a real facts prompt (21.5k estimated at 3.3, 18.4k real)


def estimate_tokens(text: str) -> int:
    return round(len(text) / CHARS_PER_TOKEN)


def load_tokenizer(path_or_id: str | None = None):
    """The real Qwen tokenizer if its files are on disk (never downloads); else None."""
    from transformers import AutoTokenizer

    for candidate in [path_or_id, "models/hf/Qwen3.5-4B"]:
        if candidate and Path(candidate).is_dir():
            return AutoTokenizer.from_pretrained(candidate, local_files_only=True)
    return None
