"""One-time download of an OPUS-MT model into config.MODELS_DIR. Run by the setup script, never at run time.

    python -m backend.translation.fetch_model [src tgt]       (default: de en)
"""

import os
import sys

from backend.translation.translator import check

# Only what the PyTorch Marian model needs (the repo also holds TensorFlow and Rust copies of the weights).
FILES = ["config.json", "generation_config.json", "pytorch_model.bin", "source.spm", "target.spm",
         "tokenizer_config.json", "vocab.json"]


def fetch(src: str = "de", tgt: str = "en") -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from huggingface_hub import snapshot_download

    from backend.llm.executive_summary.translate_summary import model_dir

    path = model_dir(src, tgt)
    snapshot_download(f"Helsinki-NLP/opus-mt-{src}-{tgt}", local_dir=str(path), allow_patterns=FILES)
    size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and ".cache" not in f.parts)
    print(f"Model saved to {path} ({size / 1e6:.0f} MB)")


if __name__ == "__main__":
    langs = sys.argv[1:3] if len(sys.argv) >= 3 else ["de", "en"]
    if check(*langs) is None:
        print("Translation model already installed.")
    else:
        fetch(*langs)
        error = check(*langs)
        if error:
            sys.exit(error)
