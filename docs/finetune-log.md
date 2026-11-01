# Fine-tuning log (branch yasharth/lora-finetune)

Goal: a kit Nikunj can run on his GPU machine to LoRA-tune the summary stage of `qwen3.5:4b`, export the result to Ollama
and measure it on the 10 held-out documents. Guide for him: `scripts/finetune/README.md`.

## Findings from reading the code (phase 0)
- The summary stage is `backend/llm/executive_summary/agent.py`: system prompt `EXECUTIVE_SUMMARY_AGENT_SYSTEM_PROMPT`, user prompt
  `build_agent_user_prompt(json.dumps(aggregated, indent=2, ensure_ascii=False))`, `llm.chat(model=KLARO_MODEL, think=False,
  options={"temperature": 0.1})`, no `format`, no `num_ctx`. The model answers with raw JSON that `parse_agent_response` cleans;
  `agent.py` then sets `issuing_organization_pages` itself and back-fills empty sections from the facts.
- Stage-4 facts for a PDF come from calling `create_chunks`, `process_chunks_file` and `aggregate_document` directly: no pipeline
  file was changed for this kit.
- **The shipping summary stage silently truncates its input.** Ollama's context here is 4096 tokens. On a real run the summary prompt
  is about 18,000 tokens; measured `prompt_eval_count` was 2050 with the default context and 18351 with `num_ctx=32768`. So today the
  model sees roughly the last tenth of the facts. A tuned model must be served with `PARAMETER num_ctx 32768` (the export script does
  this), and the base model should be compared at the same context (`--base-32k`). Worth raising with Nikunj regardless of tuning.
- Golden summaries were written from the PDF text, while the model's input is the facts that stages 3-4 extracted. A golden bullet
  that is not in the facts teaches the model to invent. `build_sft_dataset sft` reports, per example, how many golden bullets and
  numbers are visible in the facts (`facts_coverage`) and prints low-coverage documents. It does not drop them: that is a decision
  for after the first look at the numbers.
- The golden convention conflicts with the shipping prompt in places: the prompt says return `[]` for an empty category, the golden
  summaries never leave one empty ("Not specified in the document"); golden `important_conditions` items carry `Evaluation:`,
  `Submission:` or `Risk:` prefixes and section limits the prompt does not mention. Training with the unchanged prompt pulls the
  model towards the golden convention; the prompt is deliberately not edited (training input must equal inference input).
- Base weights: Hugging Face `Qwen/Qwen3.5-4B` (`Qwen3_5ForConditionalGeneration`, 4.66B parameters, vision tower plus text model,
  hybrid: 24 Gated-DeltaNet linear-attention layers and 8 full-attention layers, an MTP head, thinking on by default). Ollama's
  `qwen3.5:4b` is architecture `qwen35`, 4.7B parameters, Q4_K_M, with vision and thinking capabilities: same family, size and
  capabilities. I cannot prove the weights are the same files (Ollama stores a quantised GGUF). `Qwen/Qwen3.5-4B-Base` is the
  pre-trained variant and is not what Ollama ships. LoRA must therefore also cover `in_proj_qkv`, `in_proj_z`, `out_proj` of the
  linear-attention layers, and must leave the vision tower and MTP head alone (`lora.target_regex`).
- Chat template: with `think=False` Ollama (and `enable_thinking=False` in the HF template) ends the prompt with
  `<|im_start|>assistant\n<think>\n\n</think>\n\n`. Training renders the prompt the same way (HF template) and learns the answer plus
  `<|im_end|>`. That Ollama's own renderer produces exactly the same bytes is assumed, not checked.

## Decisions
- Mode `facts` (default): input = the agent's real input, target = the golden summary as the JSON the agent returns (no
  `issuing_organization_pages`, which the code fills in). Mode `text` (page-marked RFP text cut by whole pages) exists as a fallback.
  Recommended: `facts`, because it trains the stage that ships and its prompts are short compared with whole documents.
- `trl` is not used: a plain `transformers.Trainer` with a 15-line answer-only loss is easier to test, and trl's assistant-only
  masking needs a chat template with generation markers, which Qwen's does not have.
- Loss is computed only at answer positions, and logits only there too (`logits_to_keep`): the vocabulary is 248k, so full logits for
  a 30k-token example would be tens of GB.
- Resume checkpoints go to `<output>.work/` (they contain pickled optimizer state) and are deleted after a successful run, so the
  final adapter folder can be scanned for pickle files.
- Val set: 3 train documents, one per sector where possible, fixed seed, sticky across reruns (`data/golden/sft/val_ids.json`).
- Token counts at dataset-build time are estimates (3.8 characters per token, calibrated on one real prompt); `train_lora.py` counts
  exactly with the real tokenizer.

## Verified on this Mac (smoke test, 0.8B model of the same family)
- `python -m scripts.finetune.smoke_test`: 6 synthetic examples (about 500 tokens each), 5 epochs, 10 optimizer steps, bf16 LoRA on
  Apple MPS (about 25 s per step, slowed by the Ollama facts job running at the same time and by the missing fast kernels). Train loss
  1.62, 0.93, 0.43, 0.27, 0.20 per epoch; val loss 0.31 down to 0.137. The adapter folder holds `adapter_model.safetensors` (41 MB),
  `adapter_config.json`, `run_info.json`, `loss.csv` and PEFT's `README.md`; the pickle scan passed; the adapter reloaded onto the
  base model and reproduced a trained answer. 10.2M of 763M parameters trained with the default `target_regex`.
- Real tokenizer check: the prompt renders as `...<|im_start|>assistant\n<think>\n\n</think>\n\n`, only the answer and `<|im_end|>`
  carry labels.
- Export: `export_to_ollama --run` merged the adapter (bf16 safetensors), `ollama create` imported it with Ollama's own safetensors
  importer (not llama.cpp), also with `-q int4` (857 MB for the 0.8B), and Ollama served it through the app's normal chat call with
  `think=False`. It reproduced the trained answer, which also shows Ollama's prompt renderer matches the HF template used for training
  (a mismatch would not have recalled a memorised answer). Ollama 0.32.x here rejects `-q q4_K_M` (accepts int4, int8, nvfp4, mxfp4,
  mxfp8), so the default is `int4`. The test models were removed from Ollama afterwards.
- Eval plumbing: the leak guard refused a training document; a full run against the smoke model produced the side-by-side table and
  CSV. Scores in that run mean nothing (toy model, mismatched input).
- Facts for the first document: 38 minutes (with Ollama shared), 13 chunks, 1 failed pass; 98% of its golden bullets are visible in the
  facts, which is encouraging for `facts` mode. Run `build_sft_dataset sft --max-failed-passes 1` to keep documents like it.

## Not verified (only Nikunj, or a first real run, can)
- Training the real 4B: speed, memory against the estimate, whether `logits_to_keep` works on the 4B class, QLoRA/bitsandbytes on CUDA,
  the optional fast kernels, and whether the loss on about 20 examples generalises to the 10 eval documents.
- Whether Ollama's safetensors import of a **4B** merged model (about 9 GB) and `int4` quantisation behave as for the 0.8B, and whether
  the safetensors import path works on an NVIDIA machine (verified on Apple Silicon only; export is meant to run on Yasharth's Mac).
- Facts mode token statistics: the 32 documents' facts are still being built (about 20 minutes each unloaded, longer when Ollama is
  shared; one document is done), so train/val/eval counts below are for text mode only.

## Known limits
- Not tested: quality, memory and speed on the real 4B model; QLoRA; CUDA; Ollama loading the exported model; whether Ollama can
  convert a merged qwen3.5 checkpoint (see phase 4 notes below).
- The memory estimate is rough (about +-30%). Qwen3.5's linear-attention layers have a slow pure-PyTorch fallback unless
  `flash-linear-attention` and `causal-conv1d` are installed on CUDA.
- About 22 training examples is very little. Expect overfitting; early stopping and the held-out eval are the guard rails, and a gain
  on 10 documents is weak evidence.
- Golden summaries are `auto_checked` (LLM-drafted, machine-checked), not human-verified.

## 8 GB GPU: why the 4B kit needs 16 GB or more (Nov 1)

Nikunj's GPU has 8 GB. **Every memory number below is an estimate (plus or minus 30%) from `scripts/finetune/hardware.py`.
Nothing was run on CUDA; the only runs were on a Mac with the 0.8B model.** 4-bit means QLoRA (needs CUDA and bitsandbytes);
the estimate assumes a 4.2k-token answer, gradient checkpointing and the chunked loss below.

### What changed in the trainer
The loss runs `lm_head` in chunks of 256 answer tokens under checkpointing (`train_lora.answer_only_loss`) instead of
materialising logits for the whole answer (248k vocabulary: about 8 GiB for a 4.2k-token answer). Same loss and gradients
(0.8B model: 11.286130 both ways; unit test added). This took the 4B estimate at 32k tokens from 22.8 to 14.7 GiB.

### Token length per document (text mode, nothing cut; prompt plus golden answer, 32 documents, estimated as chars / 3.8)
| | tokens |
|---|---|
| median | 34,597 |
| min | 13,201 |
| max | 77,294 |
| golden answer alone: median / min / max | 3,699 / 3,206 / 4,962 |

Documents that fit in total length: 8k: 0, 12k: 0, 14k: 1, 16k: 3, 20k: 4, 24k: 6, 32k: 14 (of 32). Facts mode is no shorter:
the 5 facts files built so far are 17.7k to 24.5k tokens in total (facts prompt 14.0k to 20.7k plus the answer).

### Estimated peak memory in GiB by sequence length (input + answer)
| sequence | 4B 4-bit | 4B bf16 | 2B 4-bit | 2B bf16 |
|---|---|---|---|---|
| 6k | 7.8 | 13.8 | 5.5 | 8.1 |
| 8k | 8.3 | 14.3 | 5.8 | 8.5 |
| 12k | 9.4 | 15.4 | 6.5 | 9.1 |
| 16k | 10.5 | 16.5 | 7.2 | 9.8 |
| 24k | 12.6 | 18.6 | 8.6 | 11.2 |
| 32k | 14.7 | 20.7 | 10.0 | 12.6 |

The 2B shape (hidden 2048, 24 layers, MLP 6144) is from a third-party copy of its config.json; the parameter count is approximate.

### Why 8 GB does not fit
- 4B: weights, optimizer and CUDA overhead already take about 5 GiB, and the answer (about 4.2k tokens) is part of the
  sequence. By the estimate even 6k tokens (about 2k of input) needs 7.8 GiB, and a desktop GPU has about 7.5 GiB usable.
  `--check-only` reports 0 tokens that fit.
- Documents are far longer than what fits: median 34.6k tokens, only 1 of 32 under 14k. The 2B model at 8 GB would allow
  about 14k tokens (estimate), which leaves 0 train, 0 val and 1 eval example when nothing is truncated (built and counted, then deleted).

### What fits at 16 GB (estimate)
4B with 4-bit QLoRA: about 31.8k tokens, 14.7 GiB at 32k. This is the data in `data/golden/sft/` (cap 32,768). 4B in bf16 does not
fit 16 GB beyond about 9k tokens (needs 20.7 GiB at 32k). 12 GB with 4-bit: about 18k tokens, so about 3 or 4 of 32 documents.

### Options considered
- **Qwen3.5-2B** (same family, Ollama tag `qwen3.5:2b` per secondary sources, not checked on ollama.com): not done. Fits about
  14k to 16k tokens at 8 GB, which leaves almost no documents untruncated, and an adapter for the 2B cannot be used on the app's 4B
  (the app would have to switch to a tuned 2B). Nothing was downloaded.
- **Per-section training** (one section's facts in, that section out, 2-3k tokens): not done. Fits 8 GB, but the app writes the whole summary
  in one call, so Nikunj's summary agent and prompts would change, and the facts are built for only 5 of 32 documents.
- **Truncating the RFP text to fit**: not done. The model would see part of the document and learn to write a full summary from it,
  which teaches it to invent. Ruled out by Yasharth.
- **Paid GPU with 16 GB or more**: not done here (decision pending). It is the only option that trains on the existing data unchanged.

### Text mode and truncation
`build_sft_dataset sft --mode text` drops a document whose total length exceeds `--max-seq-len` and lists it in `MANIFEST.json`
(`skipped`). Separately it cuts trailing pages of the RFP text above `--text-budget` (default 24000 estimated tokens), so the
current `data/golden/sft/` files contain cut documents (`text_cut` in each row). For drop-only behaviour pass a very large
`--text-budget` (for example `--text-budget 1000000`). `--out-dir` writes the files somewhere other than `data/golden/sft/`.

## Per-section unit for 8 GB (Nov 1)

**What it trains.** One example = the extracted text of the pages that one section's golden bullets cite (page markers kept,
pages in order) plus the section name and its rules from the spec (limit, mandatory vs desirable, cite pages) -> that section's
bullets as JSON in the schema's own shape (`{"scope": [{"text", "pages"}]}`; overview and issuing organization have their own shape).
Nine sections = the nine schema fields (evaluation, submission and risks are the prefixed items of `important_conditions`).
`max_seq_len` 4096 for system + pages + answer. A section that does not fit is split into groups of page-adjacent bullets; a bullet
whose pages alone do not fit is dropped and listed; nothing is ever truncated. Built from `data/golden/extracted` and
`data/golden/summaries` only (`build_sft_dataset sft --unit section`, code in `section_unit.py`).

**Result with the real tokenizer** (train 19 docs, val 3, eval 10): 322 train, 39 val, 165 eval examples. Tokens per train+val
example: p50 3041, p95 3980, max 4091. Dropped: 3 bullets (pages alone over 4096 tokens: `bfsi_lic_dpdptools` commercial bullet 4,
`civil_crpf_works` conditions bullets 7 and 9). Per section (train/val/eval): overview 19/3/10, issuing organization 19/3/10, scope
35/3/18, key requirements 41/6/22, eligibility 24/3/14, important dates 27/3/15, commercial 47/5/17, project duration 25/3/13,
important conditions 85/10/46. Estimated peak memory at 4096 tokens, 4-bit: 7.3 GiB (4B) and 5.2 GiB (2B), plus or minus 30%, so
the 4B is borderline on 8 GB (the budget is 92% of the card); nothing was run on CUDA. `configs/finetune_8gb_2b.yaml` is the fallback.
The 2B uses the same tokenizer files (identical `tokenizer.json`); with thinking off both chat templates render the same prompt.
Its `config.json` (hidden 2048, 24 layers, MLP 6144, vocab 248320, tied embeddings) matches the shape in `hardware.py`.

**Why it is not the app's summary stage.** The app writes the whole summary in one call from aggregated facts (stage 5), a 10k to
30k token prompt. This unit never sees facts and never writes a whole summary: it sees only the pages a section cites. So it
trains writing, citing and copying numbers exactly, not finding the right pages and not combining facts across a document. Its
eval is an oracle-page eval (the model is handed the golden pages) and says nothing about the app's end-to-end quality.

**Future work only: what the pipeline would have to change to use it.** A section-by-section summary stage: after aggregation, for
each of the nine sections pick the pages its facts cite, call the tuned model once per section (split when the pages do not fit
4096 tokens), merge the nine answers into `ExecutiveSummaryOutput`, and cope with groups (dedupe, apply the section limits after
merging). That changes `agent.py` and the prompts in Nikunj's pipeline and costs about 9 to 30 model calls instead of one. Not done.

**Other decisions.** The trainer's `quantization: 4bit` in the 8 GB configs fails loudly without CUDA and bitsandbytes instead of
falling back to bf16; `--check-only` still sizes the run on any machine and prints FITS / DOES NOT FIT and the miss in GiB.
The 2B's tokenizer and config files (about 27 KB; the tokenizer file was already cached) were downloaded by accident when I ran
`--check-only` on the 2B config; no weights were downloaded.
