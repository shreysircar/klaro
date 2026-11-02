# Klaro LoRA fine-tuning on an 8 GB GPU

Goal: train a LoRA adapter for Qwen3.5-4B (fallback: Qwen3.5-2B) on per-section examples. One example is the RFP pages a section
cites, and the answer is that section's bullets with page numbers. Each example is at most 4096 tokens, so it fits 8 GB.
322 train, 39 val examples. Pipeline test, not the final model. Never train on the eval docs (`eval` in `data/golden/splits.json`);
the scripts refuse.

## Requirements
- NVIDIA GPU, 8 GB, driver supporting CUDA 12.8 (for another CUDA version pick the matching index on pytorch.org and report it)
- Python 3.11 to 3.13
- Disk: 4B weights about 9 GB (Hugging Face cache) plus the venv; 30 GB free (guess)
- RAM: 16 GB (guess)
- bitsandbytes (required: the config trains in 4-bit and exits without it)
- Windows: PyPI torch is CPU-only, so CUDA torch is installed first (step 2)

Nothing here has been run on a CUDA GPU. All numbers are estimates (plus or minus 30%).

## Steps
Run everything from the repo root.

### 1. Get the code
Achieves: code and training data in `data/golden/sft-section/`.

    git fetch
    git switch yasharth/lora-finetune
    git pull

or from the zip. Windows PowerShell: `Expand-Archive klaro-for-nikunj.zip -DestinationPath .` then `cd klaro-for-nikunj`.
Linux: `unzip klaro-for-nikunj.zip` then `cd klaro-for-nikunj`.

### 2. Environment and CUDA torch
Achieves: isolated environment with GPU torch. Install torch before the requirements file so pip keeps the CUDA build.

Windows PowerShell:

    py -3.12 -m venv .venv-finetune
    .venv-finetune\Scripts\Activate.ps1
    pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cu128
    python -c "import torch; print(torch.__version__, torch.cuda.is_available())"

Linux:

    python3 -m venv .venv-finetune
    source .venv-finetune/bin/activate
    pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cu128
    python -c "import torch; print(torch.__version__, torch.cuda.is_available())"

The last line must end in `True`. Then, both systems:

    pip install -r requirements-finetune.txt
    pip install bitsandbytes
    python -c "import torch; print(torch.__version__, torch.cuda.is_available())"

The second check must still print `True`.

### 3. Download the 4B weights (about 9 GB)
Achieves: base model cached locally. Optional, training downloads it on first run.

    hf download Qwen/Qwen3.5-4B

### 4. Check memory fit
Achieves: verdict before training. Loads no weights, trains nothing.

    python -m scripts.finetune.train_lora --config configs/finetune_8gb.yaml --check-only

- `FITS at max_seq_len 4096 ...`: go to step 5.
- `DOES NOT FIT ... misses by X GiB`: go to "If it does not fit".

The estimate for the 4B is about 7.3 GiB against a budget of about 7.4 GiB (92% of 8 GiB), so it is borderline either way.

### 5. Train
Achieves: the adapter, in `models/adapters/klaro-sections-4b/`.

    python -m scripts.finetune.train_lora --config configs/finetune_8gb.yaml

Interrupted run: same command plus `--resume`.

## If it does not fit, or CUDA runs out of memory
Achieves: the same data on the 2B model, estimated 5.2 GiB at 4096 tokens. The adapter works only with the 2B, not the app's 4B.

    hf download Qwen/Qwen3.5-2B
    python -m scripts.finetune.train_lora --config configs/finetune_8gb_2b.yaml --check-only
    python -m scripts.finetune.train_lora --config configs/finetune_8gb_2b.yaml

Output: `models/adapters/klaro-sections-2b/`. The 2B weights are about 4.5 GB.

## What to watch during training
- `time estimate ... min per epoch` is printed after the first 2 optimizer steps. 3 epochs at most, about 40 steps each.
- Loss is printed every step. It is noisy; the trend should go down.
- Validation loss is measured at the end of each epoch. Training stops early if it does not improve for one epoch and keeps the
  best epoch, so stopping before epoch 3 is expected.
- Normal warnings: unauthenticated Hugging Face requests; `causal_conv1d` / `flash-linear-attention` falling back to PyTorch
  (works, slower). Optional on Linux: `pip install flash-linear-attention causal-conv1d` (may need a compiler).
- GPU memory: `nvidia-smi -l 5` in a second terminal; note the peak.

## Send back
- Adapter folder zipped (contains `loss.csv` and `run_info.json`). Use `klaro-sections-2b` if the 2B was trained.

Windows PowerShell:

    Compress-Archive -Path models\adapters\klaro-sections-4b -DestinationPath klaro-sections-4b.zip

Linux:

    zip -r klaro-sections-4b.zip models/adapters/klaro-sections-4b

- Full output of the `--check-only` command
- The `time estimate` line and the real time per epoch
- GPU model and peak memory from `nvidia-smi`
- Not the `.work` folder next to the adapter (resume checkpoints, pickled files)

## Problems
Messages from the code:
- `quantization: 4bit needs CUDA and a working bitsandbytes`: torch is the CPU build (step 2 check prints `False`) or bitsandbytes is missing.
- `changed since MANIFEST.json was written`: a file in `data/golden/sft-section` was changed. Re-pull or re-unzip; do not rebuild the data.
- `Refusing to train: eval documents found`: do not work around it; report it.

Guesses, not seen yet:
- bitsandbytes install failing on Windows
- PowerShell blocking `Activate.ps1`: run `Set-ExecutionPolicy -Scope Process Bypass` in that window
- out of memory mid-epoch rather than at the start (the check uses the longest example, so unlikely)
- `hf` not found: venv not activated
