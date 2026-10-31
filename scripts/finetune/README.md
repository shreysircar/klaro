# LoRA fine-tuning kit (for Nikunj)

Trains a LoRA adapter for the summary stage (stage 5: aggregated facts in, 9-section summary JSON out) of
Klaro's `qwen3.5:4b`, then serves it through Ollama so the app uses it with `KLARO_MODEL=<tag>` and no code change.
Quality and memory on the real 4B model have **not** been tested yet (see "Known limits"); Yasharth ran a pipeline
smoke test on the 0.8B model of the same family.

The output is an adapter in **safetensors** format (never pickle): `adapter_model.safetensors` (tens of MB) +
`adapter_config.json` + `run_info.json` + `loss.csv`. The trainer fails if any `.pt/.bin/.pkl` ends up in that folder.

## What you need

- A machine with an NVIDIA GPU is the expected case. Memory for the longest example is printed by `--check-only`
  before anything is loaded; rough numbers (4B model, 32k tokens): about 18 GB with 4-bit QLoRA, about 30 GB in bf16.
  Apple Silicon (MPS) and CPU work in principle but are very slow.
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
