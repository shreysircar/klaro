# Klaro LoRA fine-tuning: steps for Nikunj (8 GB GPU path)

This zip is the repo plus the golden data that is not in git. Training data for your GPU is ready in
`data/golden/sft-section/` (do not rebuild it). Details: `scripts/finetune/README.md`, background: `docs/finetune-log.md`.
The result is a folder with `adapter_model.safetensors` (no pickle). Never send .pt/.pkl files.

**What this trains:** one example = the RFP pages that one section of a summary cites -> that section's bullets (with page
numbers). Examples are at most 4096 tokens, so they fit 8 GB. It is not what the app does today (the app writes the whole
summary in one call); it teaches writing, citing and copying numbers exactly. Nothing is truncated: long sections are split into
groups of bullets, and 3 bullets whose pages alone do not fit were dropped (listed in `data/golden/sft-section/MANIFEST.json`).
Never train on the 10 eval documents; the scripts refuse if they find them in training.

## 1. Environment (separate from the app's)
Windows PowerShell:

    py -3.12 -m venv .venv-finetune
    .venv-finetune\Scripts\Activate.ps1
    pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cu128
    pip install -r requirements-finetune.txt
    pip install bitsandbytes

Linux:

    python3 -m venv .venv-finetune
    source .venv-finetune/bin/activate
    pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cu128
    pip install -r requirements-finetune.txt
    pip install bitsandbytes

Use the CUDA version your driver supports (see pytorch.org). `bitsandbytes` is required here: the 8 GB config trains in
4-bit and stops with a message if it is missing. Optional, if it installs: `pip install flash-linear-attention causal-conv1d`
(faster and lighter on memory).

## 2. Check that it fits (send Yasharth the whole output)

    python -m scripts.finetune.train_lora --config configs/finetune_8gb.yaml --check-only

It prints `FITS at max_seq_len 4096` or `DOES NOT FIT ... misses by X GiB`. The numbers are estimates (plus or minus 30%);
nothing has been run on a CUDA GPU yet. If it says DOES NOT FIT, use the 2B config in step 4 instead.

## 3. Train the 4B model (about 9 GB of Hugging Face downloads the first time)
Optional pre-download:

    hf download Qwen/Qwen3.5-4B

Train (add `--resume` to continue an interrupted run):

    python -m scripts.finetune.train_lora --config configs/finetune_8gb.yaml

After the first steps it prints a line "time estimate ... min per epoch". My own guess, not measured: roughly 0.5 to 2
hours per epoch on an 8 GB laptop GPU (about 1 million tokens per epoch, 3 epochs, early stopping). Output:
`models/adapters/klaro-sections-4b/` (watch `loss.csv`).

## 4. If the 4B runs out of memory (CUDA out of memory): use the 2B
Optional pre-download (about 4.5 GB):

    hf download Qwen/Qwen3.5-2B

    python -m scripts.finetune.train_lora --config configs/finetune_8gb_2b.yaml

Output: `models/adapters/klaro-sections-2b/`. The 2B adapter only works with the 2B model, not the app's 4B.

## 5. Send back to Yasharth
- the adapter folder `models/adapters/klaro-sections-4b/` (or `-2b`), zipped; it holds `loss.csv` and `run_info.json`:
  Windows `Compress-Archive -Path models\adapters\klaro-sections-4b -DestinationPath klaro-sections-4b.zip`,
  Linux `zip -r klaro-sections-4b.zip models/adapters/klaro-sections-4b`
- the output of step 2, the "time estimate" line from step 3, and the peak GPU memory (`nvidia-smi` while it trains)
- NOT the `.work` folder next to it (resume checkpoints, pickled optimizer state)

Yasharth does the Ollama export and the evaluation on his Mac.
