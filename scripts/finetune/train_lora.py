"""LoRA fine-tuning of the summary stage.

    python -m scripts.finetune.train_lora --check-only        validate data, token lengths and memory, then stop
    python -m scripts.finetune.train_lora                     train (configs/finetune.yaml)
    python -m scripts.finetune.train_lora --resume            continue an interrupted run

Output (output_dir): adapter_model.safetensors, adapter_config.json, run_info.json, loss.csv. Never a pickle file:
the folder is scanned and the run fails if one is there. Resumable checkpoints live next to it in
<output_dir>.work/ (they contain pickled optimizer state, are deleted after a successful run, and are never to be sent).
The only network use is the Hugging Face download of the base weights and tokenizer, inside this script.
"""

import argparse
import csv
import json
import shutil
import sys
import time
from pathlib import Path

import yaml

from scripts.finetune import hardware
from scripts.finetune.common import SFT_DIR, read_json, sha256_file, splits, write_json
from scripts.finetune.tokenize_data import IGNORE, encode_all, load_jsonl, stats

PICKLE_SUFFIXES = {".pt", ".pth", ".bin", ".pkl", ".pickle", ".ckpt", ".joblib"}


def load_config(args) -> dict:
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    for key, value in {"model_id": args.model_id, "data_dir": args.data_dir, "output_dir": args.output_dir,
                       "max_seq_len": args.max_seq_len, "epochs": args.epochs, "learning_rate": args.lr,
                       "early_stopping_patience": args.patience}.items():
        if value is not None:
            cfg[key] = value
    return cfg


def check_data(cfg: dict) -> tuple[list[dict], list[dict], dict]:
    """Loads train/val, verifies them against MANIFEST.json, and refuses any eval document."""
    data_dir = Path(cfg["data_dir"])
    manifest = read_json(data_dir / "MANIFEST.json")
    for name, info in manifest["files"].items():
        if name != "eval_inputs.jsonl" and sha256_file(data_dir / name) != info["sha256"]:
            sys.exit(f"{data_dir / name} changed since MANIFEST.json was written. Rerun build_sft_dataset sft.")
    train, val = load_jsonl(data_dir / "train.jsonl"), load_jsonl(data_dir / "val.jsonl")
    eval_ids = set(splits()["eval"]) | set(manifest["doc_ids"]["eval"])
    used = {r["doc_id"] for r in train + val}
    if used & eval_ids:
        sys.exit(f"Refusing to train: eval documents found in train/val: {sorted(used & eval_ids)}")
    if not train or not val:
        sys.exit(f"Need at least 1 train and 1 val example (have {len(train)} and {len(val)}). Build more facts first.")
    return train, val, manifest


def pickle_scan(folder: Path) -> None:
    bad = [str(p) for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in PICKLE_SUFFIXES]
    if bad:
        sys.exit(f"Pickle-style files in the output folder (not allowed, safetensors only): {bad}")


def make_model(cfg: dict, hw: hardware.Hardware, qlora: bool):
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    kwargs = dict(revision=cfg["revision"], attn_implementation=cfg["attn_implementation"])
    if qlora:
        dtype = torch.bfloat16 if hw.bf16 else torch.float16
        kwargs.update(dtype=dtype, device_map={"": 0}, quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype))
    else:
        kwargs["dtype"] = torch.bfloat16 if hw.bf16 or hw.device == "mps" else torch.float32
        if hw.device == "cuda":
            kwargs["device_map"] = {"": 0}
    model = AutoModelForCausalLM.from_pretrained(cfg["model_id"], **kwargs)
    if qlora:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=cfg["gradient_checkpointing"])
    elif cfg["gradient_checkpointing"]:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    lc = cfg["lora"]
    model = get_peft_model(model, LoraConfig(
        r=lc["r"], lora_alpha=lc["alpha"], lora_dropout=lc["dropout"], target_modules=lc["target_regex"],
        bias="none", task_type="CAUSAL_LM"))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    if trainable == 0:
        sys.exit("The LoRA target pattern matched no layers. Check lora.target_regex against the model's layer names.")
    total = sum(p.numel() for p in model.parameters())
    print(f"LoRA attached: {trainable / 1e6:.1f}M trainable of {total / 1e6:.0f}M parameters")
    return model


def write_loss_csv(path: Path, log_history: list[dict]) -> None:
    """One row per epoch: mean train loss and the validation loss measured at the end of it."""
    rows: dict[int, dict] = {}
    for h in log_history:
        ep = round(h.get("epoch", 0))
        if "loss" in h:
            rows.setdefault(ep, {}).setdefault("train", []).append(h["loss"])
        if "eval_loss" in h:
            rows.setdefault(ep, {})["val"] = h["eval_loss"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "train_loss", "val_loss"])
        for ep, r in sorted(rows.items()):
            t = r.get("train", [])
            w.writerow([ep, round(sum(t) / len(t), 4) if t else "", r.get("val", "")])


LOSS_CHUNK = 256  # answer tokens per lm_head call: 256 x 248k x fp32 is ~0.25 GiB, the whole answer would be ~4 GiB


def _chunk_nll(lm_head, h, target):
    import torch.nn.functional as F

    return F.cross_entropy(lm_head(h).float(), target, reduction="sum")


def answer_only_loss(model, inputs, chunk: int = LOSS_CHUNK):
    """Cross-entropy on answer tokens only. The vocabulary is ~250k, so logits for a ~4k-token answer are several GB:
    the transformer runs once, then lm_head + loss run chunk by chunk under checkpointing (each chunk's logits are
    freed and recomputed in the backward pass), which is what lets an 8 GB GPU train."""
    from torch.utils.checkpoint import checkpoint

    labels = inputs.pop("labels")[0]
    keep = (labels[1:] != IGNORE).nonzero().squeeze(1)  # positions whose next token is an answer token
    base = model.get_base_model() if hasattr(model, "get_base_model") else model
    hidden = base.model(**inputs).last_hidden_state[0][keep]
    target = labels[1:][keep]
    total = sum(checkpoint(_chunk_nll, base.lm_head, hidden[i:i + chunk], target[i:i + chunk], use_reentrant=False)
                for i in range(0, len(keep), chunk))
    return total / len(keep)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/finetune.yaml")
    ap.add_argument("--model-id")
    ap.add_argument("--data-dir")
    ap.add_argument("--output-dir")
    ap.add_argument("--max-seq-len", type=int)
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--lr", type=float)
    ap.add_argument("--patience", type=int, help="early-stopping patience in epochs (config: early_stopping_patience)")
    ap.add_argument("--max-steps", type=int, default=-1, help="stop after this many optimizer steps (smoke tests)")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--keep-work", action="store_true", help="keep <output_dir>.work/ after a successful run")
    args = ap.parse_args()
    cfg = load_config(args)

    train_rows, val_rows, manifest = check_data(cfg)
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(cfg["model_id"], revision=cfg["revision"])
    train, dropped_t = encode_all(tok, train_rows, cfg["max_seq_len"])
    val, dropped_v = encode_all(tok, val_rows, cfg["max_seq_len"])
    dropped = dropped_t + dropped_v
    print(f"train: {stats(train)}\nval:   {stats(val)}")
    for d in dropped:
        print(f"DROPPED (not truncated): {d['doc_id']} has {d['tokens']} tokens > max_seq_len {cfg['max_seq_len']}")
    if not train or not val:
        sys.exit("Nothing left to train on after dropping over-long examples. Raise max_seq_len or use --mode text.")

    hw = hardware.detect()
    qlora = hw.qlora_ok and cfg["quantization"] in ("auto", "4bit")
    if cfg["quantization"] == "4bit" and not qlora and not args.check_only:
        sys.exit("quantization: 4bit needs CUDA and a working bitsandbytes (pip install bitsandbytes).")
    if cfg["quantization"] == "4bit" and not qlora:
        print("note: this machine cannot run 4-bit (needs CUDA and bitsandbytes); the estimate below is for 4-bit QLoRA, "
              "compared with this machine's memory.")
        qlora = True  # check-only only: size the run the config asks for
    longest = max(len(e["input_ids"]) for e in train + val)
    answer = max(sum(l != IGNORE for l in e["labels"]) for e in train + val)
    shape = hardware.shape_of(cfg["model_id"])
    est = hardware.estimate_gib(shape, longest, answer, qlora, cfg["lora"]["r"]) if shape else None
    print(f"hardware: {hw.name}, {hw.memory_gib:.0f} GiB usable, {'4-bit QLoRA' if qlora else 'bf16 LoRA'}")
    if est:
        budget = 0.92 * hw.memory_gib
        print(f"estimated peak memory for the longest example ({longest} tokens): ~{est['total']} GiB  {est}")
        if est["total"] <= budget:
            print(f"FITS at max_seq_len {cfg['max_seq_len']} on this GPU: estimated {est['total']} of {budget:.1f} GiB usable "
                  f"(margin {budget - est['total']:.1f} GiB; the estimate is plus or minus 30%).")
        else:
            fits = hardware.max_seq_that_fits(shape, answer, qlora, hw.memory_gib, cfg["lora"]["r"])
            print(f"DOES NOT FIT at max_seq_len {cfg['max_seq_len']} on this GPU: misses by {est['total'] - budget:.1f} GiB "
                  f"(estimated {est['total']} GiB, {budget:.1f} GiB usable).")
            sys.exit(f"This will not fit: ~{est['total']} GiB needed, {hw.memory_gib:.1f} GiB available. On this GPU about "
                     f"{fits} tokens per example (input + answer, answers are up to {answer}) fit with "
                     f"{'4-bit' if qlora else 'bf16'}; the data is built for longer ones. Use a GPU with more memory"
                     f"{'' if qlora else ', or install bitsandbytes for 4-bit'}.")
    else:
        print("memory estimate: unknown model shape, skipped")
    if args.check_only:
        print("check-only: data and memory look fine. Nothing was trained.")
        return 0

    import torch
    from transformers import EarlyStoppingCallback, Trainer, TrainerCallback, TrainingArguments, set_seed
    from transformers.trainer_utils import get_last_checkpoint

    set_seed(cfg["seed"])
    out, work = Path(cfg["output_dir"]), Path(str(cfg["output_dir"]) + ".work")
    started = time.time()
    model = make_model(cfg, hw, qlora)

    class Rows(torch.utils.data.Dataset):
        def __init__(self, rows): self.rows = rows
        def __len__(self): return len(self.rows)
        def __getitem__(self, i): return self.rows[i]

    def collate(batch):  # batch size is 1: no padding needed
        e = batch[0]
        ids = torch.tensor([e["input_ids"]])
        return {"input_ids": ids, "attention_mask": torch.ones_like(ids), "labels": torch.tensor([e["labels"]])}

    class EpochTime(TrainerCallback):
        """Prints a time-per-epoch estimate after the first optimizer steps (later steps differ in length)."""
        def __init__(self, after: int = 2):
            self.after, self.t0, self.start = after, 0.0, 0

        def on_train_begin(self, args, state, control, **kw):
            self.t0, self.start = time.time(), state.global_step

        def on_step_end(self, args, state, control, **kw):
            done = state.global_step - self.start
            if done == self.after:
                per = (time.time() - self.t0) / done
                per_epoch = per * state.max_steps / args.num_train_epochs
                print(f"time estimate (from the first {done} steps, {per:.0f} s per optimizer step): about {per_epoch / 60:.0f} min "
                      f"per epoch, about {per_epoch * args.num_train_epochs / 60:.0f} min if all {args.num_train_epochs:g} epochs run. "
                      "This is an estimate: step times vary with example length, and early stopping may end sooner.", flush=True)

    class AnswerOnlyTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            loss = answer_only_loss(model, dict(inputs))
            return (loss, {"loss": loss}) if return_outputs else loss

    # transformers 5: warmup_steps below 1 is a share of the steps (it replaced warmup_ratio)
    targs = TrainingArguments(
        output_dir=str(work), num_train_epochs=cfg["epochs"], max_steps=args.max_steps,
        per_device_train_batch_size=cfg["per_device_batch_size"], per_device_eval_batch_size=1,
        gradient_accumulation_steps=cfg["grad_accum"], learning_rate=cfg["learning_rate"],
        lr_scheduler_type=cfg["lr_scheduler"], warmup_steps=cfg["warmup_ratio"], weight_decay=cfg["weight_decay"],
        bf16=hw.bf16 and hw.device != "cpu", fp16=qlora and not hw.bf16,
        optim="paged_adamw_8bit" if qlora else "adamw_torch", seed=cfg["seed"], data_seed=cfg["seed"],
        eval_strategy="epoch" if args.max_steps < 0 else "no", save_strategy="epoch" if args.max_steps < 0 else "no",
        load_best_model_at_end=args.max_steps < 0, metric_for_best_model="eval_loss", greater_is_better=False,
        save_total_limit=2, logging_steps=1, report_to="none", remove_unused_columns=False, label_names=["labels"],
        dataloader_pin_memory=False, use_cpu=hw.device == "cpu",
    )
    callbacks = [EpochTime()] + ([EarlyStoppingCallback(cfg["early_stopping_patience"])] if args.max_steps < 0 else [])
    trainer = AnswerOnlyTrainer(model=model, args=targs, train_dataset=Rows(train), eval_dataset=Rows(val),
                                data_collator=collate, callbacks=callbacks)
    last = get_last_checkpoint(str(work)) if args.resume and work.is_dir() else None
    result = trainer.train(resume_from_checkpoint=last)

    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    trainer.model.save_pretrained(str(out), safe_serialization=True)  # adapter_model.safetensors + adapter_config.json
    write_loss_csv(out / "loss.csv", trainer.state.log_history)
    evals = [h["eval_loss"] for h in trainer.state.log_history if "eval_loss" in h]
    import importlib.metadata as md
    versions = {p: md.version(p) for p in ("torch", "transformers", "peft", "accelerate") }
    try:
        versions["bitsandbytes"] = md.version("bitsandbytes")
    except md.PackageNotFoundError:
        pass
    write_json(out / "run_info.json", {
        "base_model": {"id": cfg["model_id"], "revision_requested": cfg["revision"],
                       "revision_used": getattr(model.config, "_commit_hash", None)},
        "datasets": {n: i["sha256"] for n, i in manifest["files"].items()}, "dataset_mode": manifest["mode"],
        "train_docs": manifest["doc_ids"]["train"], "val_docs": manifest["doc_ids"]["val"],
        "hyperparameters": cfg, "seed": cfg["seed"], "quantization": "4bit-nf4" if qlora else "none",
        "hardware": {"device": hw.device, "name": hw.name}, "dropped_examples": dropped,
        "final": {"train_loss": result.training_loss, "best_val_loss": min(evals) if evals else None,
                  "steps": trainer.state.global_step, "epochs_run": round(trainer.state.epoch or 0, 2)},
        "libraries": versions, "seconds": round(time.time() - started),
        "chat_template": tok.chat_template, "prompt_rendering": "apply_chat_template(system,user, add_generation_prompt=True, enable_thinking=False) "
                                                                 "+ answer + <|im_end|>; loss on answer tokens only",
    })
    pickle_scan(out)
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    print(f"Saved adapter to {out}: {sorted(p.name for p in out.iterdir())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
