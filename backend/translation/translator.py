"""Segment-level translation of a document's pages with the local OPUS-MT model (see translate_summary.py).

    python -m backend.translation.translator --check [src tgt]    exit 0 if the model is installed
Prints one JSON line {"ok": bool, "error": str|null}.
"""

import hashlib
import json
import sys
from typing import Callable

from backend.config import DATA_DIR
from backend.llm.executive_summary.translate_summary import load_translation_model, model_dir
from backend.translation.segments import number_flags, segment_page

BATCH_SIZE = 8
MAX_INPUT_TOKENS = 500  # Marian's limit is 512; segments are capped far below this, so hitting it is a bug


def check(src: str = "de", tgt: str = "en") -> str | None:
    """None if the model for this direction is installed, else a message with the fix command."""
    path = model_dir(src, tgt)
    if path.is_dir() and (any(path.glob("*.bin")) or any(path.glob("*.safetensors"))):
        try:
            import sentencepiece, torch, transformers  # noqa: F401,E401
        except ImportError as e:
            return f"The translation libraries are missing ({e.name}). Run: npm run setup"
        except OSError as e:  # on Windows: torch's DLLs fail to load without the Visual C++ runtime
            return (f"PyTorch could not be loaded ({e}). On Windows install the Microsoft Visual C++ "
                    "Redistributable: https://aka.ms/vs/17/release/vc_redist.x64.exe")
        return None
    return (
        f"The {src}->{tgt} translation model is not installed at {path}. Download it once (needs internet) "
        f"with: npm run setup\n(or: python -m backend.translation.fetch_model {src} {tgt})"
    )


def _translate_batch(texts: list[str], src: str, tgt: str) -> list[str]:
    import torch

    tokenizer, model = load_translation_model(src, tgt)
    inputs = tokenizer(texts, return_tensors="pt", padding=True, truncation=False)
    if inputs["input_ids"].shape[1] > MAX_INPUT_TOKENS:
        raise ValueError(f"A segment has {inputs['input_ids'].shape[1]} tokens; the limit is {MAX_INPUT_TOKENS}.")
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=256, num_beams=4)
    return [t.strip() for t in tokenizer.batch_decode(out, skip_special_tokens=True)]


def _cache_path(src: str, tgt: str):
    return DATA_DIR / "translation_cache" / f"{src}-{tgt}.json"


def translate_pages(
    pages: list[dict], src: str, tgt: str, on_page: Callable[[int, int], None] | None = None
) -> tuple[list[dict], list[dict]]:
    """-> (segments [{id, page, src, en, flags}], pages_en [{page, text}]). Page numbers are kept as given."""
    cache_file = _cache_path(src, tgt)
    cache: dict[str, str] = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.is_file() else {}
    key = lambda s: hashlib.sha256(f"{src}>{tgt}\n{s}".encode("utf-8")).hexdigest()

    segments: list[dict] = []
    pages_en: list[dict] = []
    for done, page in enumerate(pages, start=1):
        texts = segment_page(page["text"])
        todo = sorted({t for t in texts if key(t) not in cache}, key=len)  # similar lengths pad less
        for i in range(0, len(todo), BATCH_SIZE):
            batch = todo[i:i + BATCH_SIZE]
            for text, en in zip(batch, _translate_batch(batch, src, tgt)):
                cache[key(text)] = en
        if todo:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        page_segments = [
            {"id": f"p{page['page']}-{n}", "page": page["page"], "src": t, "en": cache[key(t)],
             "flags": number_flags(t, cache[key(t)])}
            for n, t in enumerate(texts, start=1)
        ]
        segments += page_segments
        pages_en.append({"page": page["page"], "text": "\n".join(s["en"] for s in page_segments)})
        if on_page:
            on_page(done, len(pages))
    return segments, pages_en


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] != "--check":
        sys.exit("usage: python -m backend.translation.translator --check [src tgt]")
    error = check(*args[1:3]) if len(args) >= 3 else check()
    print(json.dumps({"ok": error is None, "error": error}))
    sys.exit(0 if error is None else 1)
