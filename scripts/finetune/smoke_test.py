"""End-to-end smoke test of the kit on a tiny model (default Qwen/Qwen3.5-0.8B, same family as the 4B).

    python -m scripts.finetune.smoke_test --model-id models/hf/Qwen3.5-0.8B

Builds a SYNTHETIC mini dataset from train-split golden summaries (short prompts, partial targets), trains a few
epochs, then checks: loss went down, the adapter is safetensors only, it reloads and generates. This proves the
pipeline works. It says nothing about quality or memory on the real 4B model.
"""

import argparse
import json
import sys
from pathlib import Path

from scripts.finetune.common import ROOT, SFT_DIR, golden_record, read_json, sha256_file, splits, write_json

SMOKE_DIR = ROOT / "sft_smoke"
SYSTEM = "You are the Executive Summary Agent. Answer with the summary as JSON only."


def make_data(n_train: int = 6, n_val: int = 2) -> None:
    ids = [d for d in splits()["train"] if golden_record(d)][:n_train + n_val]
    if len(ids) < n_train + n_val:
        sys.exit("Not enough golden summaries for the smoke test.")
    rows = []
    for d in ids:
        s = golden_record(d)["summary"]
        facts = {"overview": s["overview"]["text"], "scope": [i["text"] for i in s["scope"][:2]]}
        answer = {"overview": s["overview"], "issuing_organization": s["issuing_organization"][:80],
                  "scope": s["scope"][:2]}
        rows.append({"doc_id": d, "sector": "smoke", "mode": "smoke", "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "FACTS:\n" + json.dumps(facts, ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)}]})
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    parts = {"train.jsonl": rows[:n_train], "val.jsonl": rows[n_train:]}
    for name, part in parts.items():
        (SMOKE_DIR / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in part), encoding="utf-8")
    write_json(SMOKE_DIR / "MANIFEST.json", {
        "mode": "smoke", "files": {n: {"sha256": sha256_file(SMOKE_DIR / n), "examples": len(p)} for n, p in parts.items()},
        "doc_ids": {"train": [r["doc_id"] for r in rows[:n_train]], "val": [r["doc_id"] for r in rows[n_train:]], "eval": []}})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", default="models/hf/Qwen3.5-0.8B")
    ap.add_argument("--out", default="models/adapters/smoke")
    ap.add_argument("--epochs", type=int, default=8)
    args = ap.parse_args()

    make_data()
    from scripts.finetune import train_lora

    sys.argv = ["train_lora", "--model-id", args.model_id, "--data-dir", str(SMOKE_DIR), "--output-dir", args.out,
                "--max-seq-len", "2048", "--epochs", str(args.epochs), "--lr", "3e-4", "--patience", "99"]
    if train_lora.main() != 0:
        return 1

    out = Path(args.out)
    import csv

    rows = list(csv.DictReader(open(out / "loss.csv", encoding="utf-8")))
    first, last = float(rows[0]["train_loss"]), float(rows[-1]["train_loss"])
    print(f"train loss per epoch: {[r['train_loss'] for r in rows]}  val: {[r['val_loss'] for r in rows]}")
    assert last < first * 0.8, f"loss did not go down enough: {first} -> {last}"
    files = sorted(p.name for p in out.iterdir())
    assert "adapter_model.safetensors" in files and "adapter_config.json" in files, files
    print(f"adapter folder: {files}")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.model_id)
    base = AutoModelForCausalLM.from_pretrained(args.model_id, dtype=torch.float32)
    model = PeftModel.from_pretrained(base, str(out)).eval()
    prompt = tok.apply_chat_template(read_json(SMOKE_DIR / "MANIFEST.json") and
                                     [json.loads(l)["messages"][:2] for l in (SMOKE_DIR / "train.jsonl").read_text(encoding="utf-8").splitlines()][0],
                                     tokenize=False, add_generation_prompt=True, enable_thinking=False)
    ids = tok(prompt, return_tensors="pt", add_special_tokens=False)
    with torch.inference_mode():
        gen = model.generate(**ids, max_new_tokens=80, do_sample=False)
    print("reloaded adapter generates:\n", tok.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True))
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
