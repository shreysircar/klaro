"""Single source of truth for Klaro settings. Env vars override defaults."""

import os
from pathlib import Path

import ollama

VERSION = "0.1.0"
MODEL_TAG = os.environ.get("KLARO_MODEL", "qwen3.5:4b")
OLLAMA_URL = os.environ.get("KLARO_OLLAMA_URL", "http://127.0.0.1:11434")
DATA_DIR = Path(os.environ.get("KLARO_DATA_DIR", "data"))
LLM_TIMEOUT = float(os.environ.get("KLARO_LLM_TIMEOUT", "300"))
PORT = int(os.environ.get("KLARO_PORT", "0"))
HOST = "127.0.0.1"
# OPUS-MT translation models, one folder per direction (models/opus-mt-de-en). Never downloaded at run time.
MODELS_DIR = Path(os.environ.get("KLARO_MODELS_DIR", Path(__file__).resolve().parents[1] / "models"))

# Summary stage (stage 5). Defaults keep today's behaviour: the original prompt and Ollama's default context (4096).
SUMMARY_PROMPT = os.environ.get("KLARO_SUMMARY_PROMPT", "v1")  # v1 = original prompt, v2 = golden-spec rules
NUM_CTX = int(os.environ.get("KLARO_NUM_CTX", "0"))  # 0 = Ollama default; else the cap for the summary stage's context
SUMMARY_OUT_TOKENS = int(os.environ.get("KLARO_SUMMARY_OUT_TOKENS", "4096"))  # room reserved for the answer inside the context
CHARS_PER_TOKEN = 3.5  # conservative estimate for JSON facts (measured 3.9 with the Qwen tokenizer)

# Every pipeline LLM call goes through this client so host and timeout apply everywhere.
llm = ollama.Client(host=OLLAMA_URL, timeout=LLM_TIMEOUT)


def _same_model(name: str, tag: str) -> bool:
    with_latest = lambda s: s if ":" in s else f"{s}:latest"
    return with_latest(name) == with_latest(tag)


def ollama_status() -> tuple[bool, bool]:
    """(ollama reachable, model pulled). Short timeout: this is a health check."""
    try:
        models = ollama.Client(host=OLLAMA_URL, timeout=5).list().models
    except Exception:
        return False, False
    return True, any(_same_model(m.model or "", MODEL_TAG) for m in models)


def preflight_error() -> str | None:
    """Readable reason the pipeline can't run, or None if Ollama and the model are ready."""
    reachable, pulled = ollama_status()
    if not reachable:
        return f"Ollama is not running at {OLLAMA_URL}. Start the Ollama app and try again."
    if not pulled:
        return f"Model {MODEL_TAG} is not installed. Run: ollama pull {MODEL_TAG}"
    return None
