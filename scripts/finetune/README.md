# LoRA fine-tuning kit (for Nikunj)

Trains a LoRA adapter for the summary stage (stage 5: aggregated facts in, 9-section summary JSON out) of
Klaro's `qwen3.5:4b`, then serves it through Ollama so the app uses it with `KLARO_MODEL=<tag>` and no code change.
Quality and memory on the real 4B model have **not** been tested yet (see "Known limits"); Yasharth ran a pipeline
smoke test on the 0.8B model of the same family.

The output is an adapter in **safetensors** format (never pickle): `adapter_model.safetensors` (tens of MB) +
`adapter_config.json` + `run_info.json` + `loss.csv`. The trainer fails if any `.pt/.bin/.pkl` ends up in that folder.

## What you need

- **An NVIDIA GPU with 16 GB or more** for the 4B model. Estimates (plus or minus 30%, nothing was run on CUDA): about 15 GiB
  with 4-bit QLoRA at 32k tokens, about 21 GiB in bf16. **8 GB is not enough**: the golden answers alone are about 4k tokens and
  the documents are 13k to 77k tokens, so nothing useful fits (`--check-only` says how many tokens fit on your GPU).
  12 GB with 4-bit fits about 18k tokens (about 3 or 4 of 32 documents untruncated). Details: `docs/finetune-log.md`.
  Apple Silicon (MPS) and CPU work in principle but are very slow. On CUDA, `pip install flash-linear-attention causal-conv1d`
  (optional) replaces slow, memory-hungry fallbacks.
- Python 3.11 to 3.13, Ollama with `qwen3.5:4b` pulled, internet for the first Hugging Face download (about 9 GB of
  base weights). This kit is the only place besides `npm run setup` that uses the network.

## Install (once)

```bash
python -m venv .venv-finetune
source .venv-finetune/bin/activate          # Windows: .venv-finetune\Scripts\Activate.ps1
# NVIDIA GPU: install the CUDA build of torch FIRST, with the index URL for your driver
# (see https://pytorch.org/get-started/locally/), for example:
#   pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements-finetune.txt    # includes requirements.txt
pip install bitsandbytes                    # optional, enables 4-bit QLoRA on CUDA
```

## Steps, in order

All commands run from the repo root with the venv active.

1. **Data.** `data/golden/sft/{train,val,eval_inputs}.jsonl` and `MANIFEST.json` are built from the golden summaries
   and the aggregated facts of each document (`data/golden/facts/`). If those files are in the repo you can skip this.
   To rebuild (needs Ollama and takes 15 to 20 minutes per document):
   ```bash
   python -m scripts.finetune.build_sft_dataset facts      # resumable; log: data/golden/facts/build.log
   python -m scripts.finetune.build_sft_dataset sft        # writes the jsonl files and MANIFEST.json
   # text mode (no facts needed): add --mode text. Documents longer than --max-seq-len are dropped and listed, not truncated;
   # but pages beyond --text-budget (default 24000) are cut, so pass --text-budget 1000000 for drop-only.
   ```
2. **Check** (no training, no model weights loaded; prints token lengths, hardware and the memory estimate):
   ```bash
   python -m scripts.finetune.train_lora --check-only
   ```
3. **Train** (settings: `configs/finetune.yaml`; about 22 examples, 4 epochs, early stopping on the validation loss):
   ```bash
   python -m scripts.finetune.train_lora            # add --resume to continue an interrupted run
   ```
   Output: `models/adapters/klaro-qwen-ft/`. Watch `loss.csv`: with this little data, val loss usually bottoms out after
   1 to 3 epochs; the best epoch is kept.
4. **Serve it with Ollama** (Yasharth does this step on his Mac; verified there on a small model). The adapter is merged into the base
   weights and Ollama's own importer converts and quantises it (`--quantize int4`, or `int8`, or `none`):
   ```bash
   python -m scripts.finetune.export_to_ollama --adapter models/adapters/klaro-qwen-ft --name klaro-qwen-ft
   ```
5. **Evaluate** on the 10 held-out documents (base against tuned, using the real served models):
   ```bash
   python -m scripts.finetune.eval_adapter --tuned klaro-qwen-ft --adapter models/adapters/klaro-qwen-ft
   ```
   Results: `data/golden/eval_runs/klaro-qwen-ft/summary.md` and `results.csv`.
6. **Send to Yasharth:** zip `models/adapters/klaro-qwen-ft/` (a few tens of MB) plus `data/golden/eval_runs/klaro-qwen-ft/`.
   Do not send `models/adapters/klaro-qwen-ft.work/` (resume checkpoints, pickled optimizer state). If you merged the
   adapter and made a GGUF, that is about 3 GB; send the adapter instead unless asked.

## 8 GB path: per-section training

The whole-summary examples above need 16 GB or more. For an 8 GB GPU the training unit is one section: the pages that section's
bullets cite -> that section's bullets (JSON in the schema's own shape, page cites included), at most 4096 tokens per example.
Built only from `data/golden/extracted` and `data/golden/summaries`; no Ollama and no facts needed.

```bash
python -m scripts.finetune.build_sft_dataset sft --unit section                       # data/golden/sft-section/
python -m scripts.finetune.train_lora --config configs/finetune_8gb.yaml --check-only  # FITS / DOES NOT FIT, by how much
python -m scripts.finetune.train_lora --config configs/finetune_8gb.yaml               # 4B, 4-bit QLoRA (needs CUDA + bitsandbytes)
python -m scripts.finetune.train_lora --config configs/finetune_8gb_2b.yaml            # fallback: Qwen3.5-2B, same data
```

- A section whose pages do not fit is split into groups of page-adjacent bullets (one example per group, only that group's
  bullets in the answer). A bullet whose pages alone do not fit is dropped and listed in `MANIFEST.json` (`dropped`); text is never cut.
  "Not specified" bullets with no page are left out (no pages to build an input from). Token counts use the real Qwen tokenizer
  (`models/hf/Qwen3.5-4B`, never downloaded by the builder); without it they are estimates and `train_lora` drops what is too long.
- Same 3 val documents as the whole-summary data; the 10 eval documents never reach train or val (asserted when building, and again
  in `train_lora` and `eval_adapter`).
- `train_lora` prints a time-per-epoch estimate after the first 2 optimizer steps; `--resume` works as before.
- Everything about memory is an estimate (plus or minus 30%); nothing was run on CUDA. The 2B shape comes from its published config.
- Serve and evaluate on a Mac (after Nikunj sends the adapter):

```bash
python -m scripts.finetune.export_to_ollama --adapter models/adapters/klaro-sections-4b --name klaro-sections-4b
python -m scripts.finetune.eval_adapter --unit section --tuned klaro-sections-4b --adapter models/adapters/klaro-sections-4b
#   for the 2B adapter add:  --base qwen3.5:2b   (ollama pull qwen3.5:2b first)
```

The section eval is an **oracle-page eval: each model is given the pages the golden section cites. It measures writing and
citing, not finding the right pages.** Per section, base against tuned: valid JSON/schema, cited pages inside the input pages,
numbers verbatim on the cited page, bullet count within the spec limits, similarity to the golden bullets. Output:
`data/golden/eval_runs/<tag>-section/{summary.md,results.csv}`.
This model is not wired into the app (the app writes the whole summary in one call): see "Future work" in `docs/finetune-log.md`.

## Important: context length

Ollama's default context here is 4096 tokens. The summary prompt is 10k to 30k tokens, so **today the shipping summary
stage silently sees only the end of the facts** (measured: 2050 of 18351 tokens evaluated on a real run). The tuned
model's Modelfile sets `PARAMETER num_ctx 32768`. For a fair comparison also create a 32k copy of the base
(`export_to_ollama --base-32k`) and evaluate it with `--base klaro-base-32k`.

## Rules the kit enforces

- The 10 eval documents are never in train or val: asserted when building, checked again by `train_lora` and `eval_adapter`.
- Examples longer than `max_seq_len` are dropped and listed, never truncated.
- Loss is on the assistant answer only (there is a test that proves the prompt tokens are masked).

## Known limits

See `docs/finetune-log.md`.
