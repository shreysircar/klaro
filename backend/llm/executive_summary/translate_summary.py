
import json
from pathlib import Path
from typing import Any

from backend.config import MODELS_DIR


def model_dir(src: str = "en", tgt: str = "de") -> Path:
    """Where the OPUS-MT model for this direction must live (Helsinki-NLP/opus-mt-<src>-<tgt>)."""
    return MODELS_DIR / f"opus-mt-{src}-{tgt}"


# Models stay loaded once per Python process, one per direction.
_loaded: dict[tuple[str, str], tuple] = {}


def load_translation_model(src: str = "en", tgt: str = "de"):
    """Load OPUS-MT exclusively from local model files."""
    if (src, tgt) not in _loaded:
        path = model_dir(src, tgt)
        if not path.exists():
            raise FileNotFoundError(
                f"Translation model not found at {path}. "
                "Download OPUS-MT before running translation."
            )

        # Imported here so the English-only pipeline never needs transformers or torch.
        from transformers import MarianMTModel, MarianTokenizer

        tokenizer = MarianTokenizer.from_pretrained(str(path), local_files_only=True)
        model = MarianMTModel.from_pretrained(str(path), local_files_only=True)
        model.eval()
        _loaded[(src, tgt)] = (tokenizer, model)

    return _loaded[(src, tgt)]


def translate_text(text: str, max_input_tokens: int = 450, src: str = "en", tgt: str = "de") -> str:
    """Translate one text string locally (default English to German)."""
    if not text or not text.strip():
        return text

    tokenizer, model = load_translation_model(src, tgt)

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
