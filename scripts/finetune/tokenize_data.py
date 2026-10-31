"""Turns chat examples into (input_ids, labels) with the loss on the assistant answer only."""

import json
from pathlib import Path

IGNORE = -100
IM_END = "<|im_end|>"


def prompt_text(tok, messages: list[dict]) -> str:
    """Everything up to where the model starts answering, rendered exactly like inference with think=False:
    ...<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n"""
    return tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)


def build_example(tok, messages: list[dict], max_len: int) -> dict | None:
    """-> {input_ids, labels, prompt_tokens} or None if longer than max_len (the caller reports it; no truncation).
    Tokenised once as a whole, so the answer's first token is the same as at inference; a token that straddles the
    prompt/answer boundary counts as prompt (masked)."""
    assert messages[-1]["role"] == "assistant"
    prompt = prompt_text(tok, messages)
    full = prompt + messages[-1]["content"] + IM_END
    enc = tok(full, add_special_tokens=False, return_offsets_mapping=True)
    ids = enc["input_ids"]
    if len(ids) > max_len:
        return None
    labels = [i if start >= len(prompt) else IGNORE for i, (start, _end) in zip(ids, enc["offset_mapping"])]
    if all(l == IGNORE for l in labels):
        raise ValueError("no answer tokens left to learn from")
    return {"input_ids": ids, "labels": labels, "prompt_tokens": sum(l == IGNORE for l in labels)}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def encode_all(tok, rows: list[dict], max_len: int) -> tuple[list[dict], list[dict]]:
    """-> (encoded examples, dropped [{doc_id, tokens}]). Each kept example carries its doc_id."""
    kept, dropped = [], []
    for r in rows:
        ex = build_example(tok, r["messages"], max_len)
        if ex is None:
            n = len(tok(prompt_text(tok, r["messages"]) + r["messages"][-1]["content"], add_special_tokens=False)["input_ids"])
            dropped.append({"doc_id": r["doc_id"], "tokens": n})
        else:
            kept.append({**ex, "doc_id": r["doc_id"]})
    return kept, dropped


def stats(examples: list[dict]) -> dict:
    n = sorted(len(e["input_ids"]) for e in examples)
    a = sorted(sum(l != IGNORE for l in e["labels"]) for e in examples)
    q = lambda v, p: v[min(len(v) - 1, int(p * len(v)))] if v else 0
    return {"examples": len(n), "tokens_min": q(n, 0), "tokens_median": q(n, 0.5), "tokens_max": q(n, 0.999),
            "answer_tokens_median": q(a, 0.5), "answer_tokens_max": q(a, 0.999)}
