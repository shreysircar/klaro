"""Serve a trained adapter through Ollama, so the app uses it with KLARO_MODEL=<name> and no code change.

    python -m scripts.finetune.export_to_ollama --adapter models/adapters/klaro-qwen-ft --name klaro-qwen-ft
        prints the plan and the exact commands (nothing is run)
    ... --run                    execute the steps that need no extra software
    ... --method adapter         Modelfile ADAPTER on top of qwen3.5:4b (see below: probably unsupported for this architecture)
    ... --method merge           merge the adapter into the base weights, then `ollama create` converts and quantises
    ... --base-32k               also create klaro-base-32k: the base model with the same long context, for a fair eval

Ollama's documented safetensors-adapter support covers Llama, Mistral and Gemma only. qwen3.5 (hybrid
linear-attention, multimodal) is not listed, so `merge` is the default (it worked for the 0.8B smoke model). The adapter was trained on full-precision
weights while Ollama serves a quantised base (Q4_K_M), so behaviour can differ slightly: eval_adapter.py measures
the served model, not the training-time one.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from scripts.finetune.common import ADAPTERS_DIR, BASE_MODEL_ID, OLLAMA_BASE_TAG, read_json

CTX = 32768  # the summary prompt is 10k to 30k tokens; Ollama's default of 4096 silently cuts it


def base_modelfile_lines(tag: str = OLLAMA_BASE_TAG) -> list[str]:
    """TEMPLATE / RENDERER / PARSER / PARAMETER lines of the base model, so a model made from raw weights behaves the same."""
    out = subprocess.run(["ollama", "show", tag, "--modelfile"], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    keep, in_license = [], False
    for line in out.splitlines():
        if line.startswith('LICENSE """'):
            in_license = True
        if not in_license and line.split(" ", 1)[0] in ("TEMPLATE", "RENDERER", "PARSER", "PARAMETER", "SYSTEM"):
            keep.append(line)
        if in_license and line.rstrip().endswith('"""') and not line.startswith('LICENSE """'):
            in_license = False
    return [l for l in keep if not l.startswith("PARAMETER num_ctx")]


def write_modelfile(path: Path, source: str, extra: list[str], ctx: int) -> None:
    lines = [f"FROM {source}", *extra, *base_modelfile_lines(), f"PARAMETER num_ctx {ctx}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_adapter(adapter: Path, out: Path, base_id: str) -> None:
    """Base weights (bf16) + adapter -> plain safetensors checkpoint in `out`. Loads the base the same way the trainer did,
    so the adapter's layer names match."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    base = AutoModelForCausalLM.from_pretrained(base_id, dtype=torch.bfloat16)
    merged = PeftModel.from_pretrained(base, str(adapter)).merge_and_unload()
    merged.save_pretrained(str(out), safe_serialization=True)
    AutoTokenizer.from_pretrained(base_id).save_pretrained(str(out))


def sh(cmd: list[str]) -> None:
    print("$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--name", required=True, help="Ollama tag to create, then set KLARO_MODEL to it")
    ap.add_argument("--method", choices=["merge", "adapter"], default="merge")
    ap.add_argument("--ctx", type=int, default=CTX)
    ap.add_argument("--quantize", default="int4", choices=["int4", "int8", "none"], help="Ollama's own quantiser for safetensors imports")
    ap.add_argument("--base-32k", action="store_true")
    ap.add_argument("--run", action="store_true", help="execute (default: print the plan only)")
    args = ap.parse_args()

    adapter = Path(args.adapter)
    if not (adapter / "adapter_model.safetensors").is_file():
        sys.exit(f"{adapter}/adapter_model.safetensors not found. Train first (scripts/finetune/train_lora.py).")
    info = read_json(adapter / "run_info.json") if (adapter / "run_info.json").is_file() else {}
    base_id = info.get("base_model", {}).get("id", BASE_MODEL_ID)
    work = ADAPTERS_DIR / f"{args.name}.modelfile"
    merged = Path("models/merged") / args.name
    steps: list[list[str]] = []

    if args.method == "adapter":
        write_modelfile(work, OLLAMA_BASE_TAG, [f"ADAPTER {adapter.resolve()}"], args.ctx)
        steps.append(["ollama", "create", args.name, "-f", str(work)])
        print("Method adapter: Ollama documents safetensors adapters for Llama, Mistral and Gemma only. If `ollama create`\n"
              "fails with an architecture error, use --method merge.")
    else:
        write_modelfile(work, str(merged.resolve()), [], args.ctx)
        steps.append(["ollama", "create", args.name, "-f", str(work)] + ([] if args.quantize == "none" else ["-q", args.quantize]))
        print(f"Method merge: 1) merge {adapter} into {base_id} -> {merged} (bf16 safetensors, about 9 GB for the 4B);\n"
              f"2) `ollama create` imports the safetensors with Ollama's own importer ({args.quantize}). Verified on the 0.8B smoke model:\n"
              "it imports, serves through the same chat API and reproduces the trained output. Ollama's `-q` accepts int4, int8 (and\n"
              "nvfp4/mxfp4/mxfp8), not GGUF types such as q4_K_M. Fallback if a future Ollama cannot import it: llama.cpp\n"
              "(not installed by this script; ask first): python convert_hf_to_gguf.py <merged dir> --outtype bf16 ; llama-quantize <in.gguf> <out.gguf> Q4_K_M ;\n"
              "then `FROM <out.gguf>` in the Modelfile.")
    if args.base_32k:
        base_mf = ADAPTERS_DIR / "klaro-base-32k.modelfile"
        base_mf.parent.mkdir(parents=True, exist_ok=True)
        base_mf.write_text(f"FROM {OLLAMA_BASE_TAG}\nPARAMETER num_ctx {args.ctx}\n", encoding="utf-8")
        steps.append(["ollama", "create", "klaro-base-32k", "-f", str(base_mf)])

    print(f"\nModelfile: {work}\n--- Commands ---")
    if args.method == "merge":
        print(f"(merge in Python: scripts.finetune.export_to_ollama.merge_adapter('{adapter}', '{merged}', '{base_id}'))")
    for s in steps:
        print("$ " + " ".join(s))
    print(f"\nThen run the app with KLARO_MODEL={args.name}\n")
    if not args.run:
        print("Plan only. Add --run to execute.")
        return 0
    if args.method == "merge":
        merge_adapter(adapter, merged, base_id)
    for s in steps:
        sh(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
