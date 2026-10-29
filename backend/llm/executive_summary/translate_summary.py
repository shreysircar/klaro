
import json
from pathlib import Path
from typing import Any

from transformers import MarianMTModel, MarianTokenizer


# Resolve the model directory from the Klaro project root.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = PROJECT_ROOT / "models" / "opus-mt-en-de"

# Keep the model loaded once per Python process.
_tokenizer = None
_model = None


def load_translation_model():
    """Load OPUS-MT exclusively from local model files."""
    global _tokenizer, _model

    if _model is None or _tokenizer is None:
        if not MODEL_DIR.exists():
            raise FileNotFoundError(
                f"Translation model not found at {MODEL_DIR}. "
                "Download OPUS-MT before running translation."
            )

        _tokenizer = MarianTokenizer.from_pretrained(
            str(MODEL_DIR),
            local_files_only=True,
        )
        _model = MarianMTModel.from_pretrained(
            str(MODEL_DIR),
            local_files_only=True,
        )
        _model.eval()

    return _tokenizer, _model


def translate_text(text: str, max_input_tokens: int = 450) -> str:
    """Translate one English text string into German locally."""
    if not text or not text.strip():
        return text

    tokenizer, model = load_translation_model()

    # Avoid silently truncating long text: callers should chunk it first.
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=False,
    )

    input_length = inputs["input_ids"].shape[1]
    if input_length > max_input_tokens:
        raise ValueError(
            f"Text contains {input_length} tokens; limit is "
            f"{max_input_tokens}. Split the text into smaller pieces."
        )

    import torch

    with torch.inference_mode():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=256,
            num_beams=4,
        )

    return tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()


def translate_summary_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Translate summary text fields while preserving JSON keys and page metadata.
    The issuing organization's official name is deliberately left unchanged.
    """
    translated = json.loads(json.dumps(data, ensure_ascii=False))

    # Translate the overview statement.
    overview = translated.get("overview")
    if isinstance(overview, dict) and isinstance(overview.get("text"), str):
        overview["text"] = translate_text(overview["text"])

    # Translate text in list-based sections.
    sections = [
        "scope",
        "key_requirements",
        "eligibility",
        "important_dates",
        "commercial_requirements",
        "project_duration",
        "important_conditions",
    ]

    for section in sections:
        items = translated.get(section, [])
        if not isinstance(items, list):
            continue

        for item in items:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                item["text"] = translate_text(item["text"])
            elif isinstance(item, str):
                # Defensive support for older summary formats.
                index = items.index(item)
                items[index] = translate_text(item)

    return translated


def translate_summary_file(
    english_json_path: Path,
    german_json_path: Path | None = None,
) -> Path:
    """Translate an English summary JSON into a separate German JSON file."""
    english_json_path = Path(english_json_path)

    if not english_json_path.exists():
        raise FileNotFoundError(
            f"English summary JSON not found: {english_json_path}"
        )

    if german_json_path is None:
        german_json_path = english_json_path.with_name(
            f"{english_json_path.stem}_de.json"
        )
    else:
        german_json_path = Path(german_json_path)

    with english_json_path.open("r", encoding="utf-8-sig") as file:
        english_data = json.load(file)

    german_data = translate_summary_data(english_data)

    # Validate the output before writing it.
    if not isinstance(german_data.get("overview"), dict):
        raise ValueError("Translated summary has an invalid overview structure.")

    german_json_path.parent.mkdir(parents=True, exist_ok=True)
    with german_json_path.open("w", encoding="utf-8") as file:
        json.dump(german_data, file, ensure_ascii=False, indent=2)

    return german_json_path
