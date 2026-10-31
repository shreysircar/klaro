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
