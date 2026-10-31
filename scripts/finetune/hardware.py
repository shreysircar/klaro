"""What the machine can do, and a rough memory estimate for a training run."""

import os
from dataclasses import dataclass

GIB = 1024 ** 3

# Shapes of models we know, for --check-only without network. Others are read from their config.json.
KNOWN = {
    "Qwen/Qwen3.5-4B": dict(params=4.66e9, embed=248320 * 2560, hidden=2560, layers=32, inter=9216, vocab=248320),
}


@dataclass
class Hardware:
    device: str          # cuda | mps | cpu
    name: str
    memory_gib: float    # usable memory for training
    bf16: bool
    qlora_ok: bool       # CUDA and bitsandbytes importable


def detect() -> Hardware:
    import torch

    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        try:
            import bitsandbytes  # noqa: F401
            qlora = True
        except Exception:  # missing, or built without GPU support
            qlora = False
        return Hardware("cuda", f"{p.name} ({torch.cuda.device_count()} GPU)", p.total_memory / GIB,
                        torch.cuda.is_bf16_supported(), qlora)
    if torch.backends.mps.is_available():
        try:
            mem = torch.mps.recommended_max_memory() / GIB
        except Exception:
            mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / GIB * 0.6
        return Hardware("mps", "Apple GPU (MPS)", mem, True, False)
    ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / GIB if hasattr(os, "sysconf") else 8.0
    return Hardware("cpu", "CPU", ram * 0.7, False, False)


def shape_of(model_id: str) -> dict | None:
    if model_id in KNOWN:
        return KNOWN[model_id]
    try:
        from transformers import AutoConfig

        c = AutoConfig.from_pretrained(model_id)
        t = getattr(c, "text_config", c)
        vocab = t.vocab_size
        h, layers, inter = t.hidden_size, t.num_hidden_layers, t.intermediate_size
        embed = vocab * h
        params = embed + layers * (3 * h * inter + 6 * h * h)  # rough: MLP plus attention-sized projections
        return dict(params=params, embed=embed, hidden=h, layers=layers, inter=inter, vocab=vocab)
    except Exception:
        return None


def estimate_gib(shape: dict, seq: int, answer_tokens: int, qlora: bool, rank: int = 16) -> dict:
    """Rough peak memory in GiB (about +-30%). Components are returned so the report can show them.
    Assumes gradient checkpointing and logits computed only at answer positions (train_lora.py does both)."""
    h, layers, inter, vocab = shape["hidden"], shape["layers"], shape["inter"], shape["vocab"]
    weights = ((shape["params"] - shape["embed"]) * 0.55 + shape["embed"] * 2) if qlora else shape["params"] * 2
    lora_params = layers * (3 * (h + inter) + 4 * 2 * h) * rank
    optimizer = lora_params * 16                       # fp32 weights, grads, two Adam moments
    checkpoints = layers * seq * h * 2                 # one bf16 hidden state saved per layer
    one_layer = seq * (inter * 3 + h * 8) * 2          # the layer being recomputed in the backward pass
    logits = answer_tokens * vocab * 4 * 2             # fp32 logits and their gradient, answer positions only
    parts = {"weights": weights, "lora_and_optimizer": optimizer, "layer_checkpoints": checkpoints,
             "one_layer_peak": one_layer, "logits": logits, "runtime_overhead": 1.5 * GIB}
    out = {k: round(v / GIB, 1) for k, v in parts.items()}
    out["total"] = round(sum(parts.values()) / GIB * 1.1, 1)  # 10% slack for fragmentation
    return out
