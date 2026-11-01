"""Builds the fine-tuning data from data/golden/.

    python -m scripts.finetune.build_sft_dataset facts [--only DOC ...] [--limit N]
        Runs stages 1-4 of the app on every golden doc (train docs first, then eval docs) and saves the
        aggregated facts to data/golden/facts/<doc_id>.json. About 15-20 minutes per document with Ollama.
        Resumable: finished docs are skipped. Log: data/golden/facts/build.log. Stop it with Ctrl+C or
        `kill <pid>`; the document in progress restarts from its first chunk next time.
    python -m scripts.finetune.build_sft_dataset sft --unit section [--max-seq-len 4096] [--out-dir DIR]
        The 8 GB path: one example per section (or group of its bullets): the pages the section cites -> the section's
        bullets. Built only from data/golden/extracted and summaries. Writes data/golden/sft-section/.
    python -m scripts.finetune.build_sft_dataset sft [--mode facts|text] [--max-seq-len N] [--text-budget N]
        Writes data/golden/sft/{train,val,eval_inputs}.jsonl and MANIFEST.json from what exists. Rerun it
        whenever more summaries or facts are done. Eval documents never reach train or val.
"""

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.finetune import section_unit
from scripts.finetune.common import (FACTS_DIR, OLLAMA_BASE_TAG, ROOT, SFT_DIR, USABLE_STATUS, estimate_tokens,
                                     facts_messages, golden_record, manifest_rows, read_json, sha256_file, splits,
                                     target_text, write_json)
from scripts.golden_lib import load_pages

VAL_DOCS = 3
SEED = 2026
LOG = FACTS_DIR / "build.log"


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def usable_docs() -> dict[str, list[str]]:
    """Doc ids with a golden summary that passed the automatic checks, by split (train first)."""
    out: dict[str, list[str]] = {}
    for split, ids in splits().items():
        out[split] = [d for d in ids if (r := golden_record(d)) and r["provenance"]["status"] in USABLE_STATUS]
    return out


# ---- facts: stages 1-4 -------------------------------------------------------------------------------

def build_facts_for(doc_id: str) -> None:
    # Imported here: they pull in ollama and the whole pipeline, which `sft` does not need.
    from backend.config import MODEL_TAG
    from backend.documents.chunker import create_chunks
    from backend.llm.executive_summary.aggregator import aggregate_document
    from backend.llm.executive_summary.chunk_analyzer import process_chunks_file

    extracted = ROOT / "extracted" / f"{doc_id}.json"
    work = FACTS_DIR / "_work" / doc_id
    work.mkdir(parents=True, exist_ok=True)
    chunks_file, analysis_file, aggregated_file = work / "chunks.json", work / "analysis.json", work / "aggregated.json"

    t0 = time.time()
    chunks = create_chunks(read_json(extracted))  # the extracted text keeps the app's page numbers
    write_json(chunks_file, chunks)
    process_chunks_file(chunks_file, analysis_file, extracted_file_path=extracted)
    aggregate_document(analysis_file, aggregated_file, extracted)

    analysis = read_json(analysis_file)
    failed = sum((not c["pass_a_success"]) + (not c["pass_b_success"]) for c in analysis["chunks"])
    write_json(FACTS_DIR / f"{doc_id}.json", {
        "doc_id": doc_id, "model": MODEL_TAG, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0), "chunks": len(chunks), "failed_passes": failed,
        "aggregated": read_json(aggregated_file),
    })
    log(f"{doc_id}: done in {round(time.time() - t0)}s, {len(chunks)} chunks, {failed} failed passes")


def cmd_facts(args) -> int:
    from backend.config import MODEL_TAG, preflight_error

    if MODEL_TAG != OLLAMA_BASE_TAG:
        sys.exit(f"KLARO_MODEL is {MODEL_TAG!r}. Facts must come from the base model {OLLAMA_BASE_TAG!r}: "
                 "training on facts made by a tuned model would compound its own mistakes.")
    if (problem := preflight_error()):
        sys.exit(problem)
    docs = usable_docs()
    todo = [d for split in ("train", "eval") for d in docs[split] if not (FACTS_DIR / f"{d}.json").is_file()]
    if args.only:
        todo = [d for d in todo if d in args.only]
    if args.limit:
        todo = todo[:args.limit]
    log(f"facts: {len(todo)} documents to build ({sum(len(v) for v in docs.values())} usable, model {MODEL_TAG})")
    for n, doc_id in enumerate(todo, start=1):
        log(f"[{n}/{len(todo)}] {doc_id} ({manifest_rows()[doc_id]['pages']} pages) starting")
        try:
            build_facts_for(doc_id)
        except Exception as e:  # one bad document must not stop the other 30
            log(f"{doc_id}: FAILED {type(e).__name__}: {e}")
    log("facts: finished")
    return 0


# ---- sft: assemble the jsonl files -------------------------------------------------------------------

def facts_coverage(summary: dict, aggregated: dict) -> dict:
    """How much of the golden summary is visible in the facts the model will be given. A low value means the
    target asks the model for things its input does not contain, which teaches it to invent."""
    from scripts.finetune.common import ROOT as _  # noqa: F401 (keeps import order obvious)
    from scripts.golden_checks import NUM_RE, content_words
    from scripts.golden_lib import items

    blob = json.dumps(aggregated, ensure_ascii=False)
    have_words, have_numbers = content_words(blob), set(NUM_RE.findall(blob))
    total = covered = nums = nums_found = 0
    for _sec, _i, text, _pages in items(summary):
        if "Not specified in the document" in text:
            continue
        words = content_words(text)
        total += 1
        covered += bool(words) and len(words & have_words) / len(words) >= 0.5
        for n in NUM_RE.findall(text):
            nums += 1
            nums_found += n in have_numbers
    return {"bullets": total, "bullets_in_facts": covered, "numbers": nums, "numbers_in_facts": nums_found,
            "bullet_coverage": round(covered / total, 2) if total else 1.0,
            "number_coverage": round(nums_found / nums, 2) if nums else 1.0}


def text_messages(doc_id: str, budget: int) -> tuple[list[dict], dict]:
    """Page-marked RFP text, cut by whole pages (from the end) to fit `budget` estimated tokens."""
    from backend.llm.executive_summary.prompts import EXECUTIVE_SUMMARY_AGENT_SYSTEM_PROMPT

    pages = read_json(ROOT / "extracted" / f"{doc_id}.json")
    kept, used = [], 0
    for p in pages:
        part = f"--- [PAGE {p['page']}] ---\n{p['text']}\n"
        if used + estimate_tokens(part) > budget:
            break
        kept.append(part)
        used += estimate_tokens(part)
    user = ("Summarize the following RFP text into the Executive Summary JSON schema. Cite the PAGE numbers "
            "shown in the markers.\n\nRFP TEXT:\n" + "\n".join(kept))
    return ([{"role": "system", "content": EXECUTIVE_SUMMARY_AGENT_SYSTEM_PROMPT},
             {"role": "user", "content": user}],
            {"pages_total": len(pages), "pages_kept": len(kept), "cut": len(kept) < len(pages)})


def choose_val(train_ready: list[str], sectors: dict[str, str]) -> list[str]:
    """3 val docs, one per sector where possible, fixed seed. Sticky: earlier picks are kept on reruns."""
    path = SFT_DIR / "val_ids.json"
    chosen = [d for d in (read_json(path) if path.is_file() else []) if d in train_ready][:VAL_DOCS]
    rng = random.Random(SEED)
    by_sector: dict[str, list[str]] = {}
    for d in sorted(train_ready):
        by_sector.setdefault(sectors[d], []).append(d)
    order = sorted(by_sector)
    rng.shuffle(order)
    for sector in order:  # one doc per sector first, so val covers different kinds of RFP
        if len(chosen) >= VAL_DOCS:
            break
        pool = [d for d in by_sector[sector] if d not in chosen]
        if pool and sector not in {sectors[c] for c in chosen}:
            chosen.append(rng.choice(pool))
    rest = [d for d in sorted(train_ready) if d not in chosen]
    while len(chosen) < VAL_DOCS and rest:
        chosen.append(rest.pop(rng.randrange(len(rest))))
    if len(chosen) == VAL_DOCS:  # only freeze a complete choice, so early reruns do not lock in a lopsided val set
        write_json(path, chosen)
    return chosen


def assert_no_leak(train_ids, val_ids, eval_ids) -> None:
    leak = set(eval_ids) & (set(train_ids) | set(val_ids))
    assert not leak, f"eval documents found in train/val: {sorted(leak)}"


def _pcts(values: list[int]) -> str:
    v = sorted(values)
    q = lambda p: v[min(len(v) - 1, int(p * len(v)))] if v else 0
    return f"p50 {q(0.5)}, p95 {q(0.95)}, max {v[-1] if v else 0}"


def cmd_sft_section(args, count=None) -> int:
    """count(messages) -> exact tokens; default is the real Qwen tokenizer from models/hf (never downloaded here), else an estimate."""
    from scripts.finetune.common import load_tokenizer
    from scripts.finetune.tokenize_data import token_len

    tok = None if count else load_tokenizer(args.tokenizer)
    if count is None:
        if tok:
            count = lambda msgs: token_len(tok, msgs)
        else:
            print("WARNING: no tokenizer files found (models/hf/Qwen3.5-4B); token counts are estimates (chars / 3.8). "
                  "train_lora.py counts exactly and drops anything over max_seq_len.")
            count = lambda msgs: estimate_tokens(section_unit.SYSTEM_PROMPT + "".join(m["content"] for m in msgs[1:]))
    docs, rows = usable_docs(), manifest_rows()
    sectors = {d: rows[d]["sector"] for d in rows}
    seed = ROOT / "sft" / "val_ids.json"  # same 3 val documents as the 32k data
    if not (SFT_DIR / "val_ids.json").is_file() and seed.is_file():
        write_json(SFT_DIR / "val_ids.json", read_json(seed))

    dropped, no_pages = [], []

    def doc_examples(doc_id: str) -> list[dict]:
        summary = golden_record(doc_id)["summary"]
        page_text = load_pages(doc_id)
        out = []
        for key in section_unit.SECTIONS:
            exs, drops, empty = section_unit.build_examples(key, summary, page_text, count, args.max_seq_len)
            dropped.extend({"doc_id": doc_id, **d} for d in drops)
            if empty:
                no_pages.append({"doc_id": doc_id, "section": key})
            out += [{"doc_id": doc_id, "sector": sectors[doc_id], "unit": "section", "section": key, **e} for e in exs]
        return out

    by_doc = {d: doc_examples(d) for d in docs["train"] + docs["eval"]}
    val_ids = choose_val([d for d in docs["train"] if by_doc[d]], sectors)
    train = [e for d in docs["train"] if d not in val_ids for e in by_doc[d]]
    val = [e for d in val_ids for e in by_doc[d]]
    eval_ex = [e for d in docs["eval"] for e in by_doc[d]]
    assert_no_leak({e["doc_id"] for e in train}, {e["doc_id"] for e in val}, set(splits()["eval"]) | set(docs["eval"]))

    def write_jsonl(name: str, rows_: list[dict]) -> Path:
        path = SFT_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_), encoding="utf-8")
        return path

    keep = ("doc_id", "sector", "unit", "section", "group", "groups", "pages", "tokens")
    eval_inputs = [{**{k: e[k] for k in keep}, "messages": e["messages"][:2],
                    "golden": section_unit.answer_obj(e["section"], e["bullets"])} for e in eval_ex]
    files = {"train.jsonl": write_jsonl("train.jsonl", [{k: e[k] for k in (*keep, "messages")} for e in train]),
             "val.jsonl": write_jsonl("val.jsonl", [{k: e[k] for k in (*keep, "messages")} for e in val]),
             "eval_inputs.jsonl": write_jsonl("eval_inputs.jsonl", eval_inputs)}
    per_section = {k: {"train": sum(e["section"] == k for e in train), "val": sum(e["section"] == k for e in val),
                       "eval": sum(e["section"] == k for e in eval_ex)} for k in section_unit.SECTIONS}
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mode": "section", "unit": "section", "seed": SEED,
        "max_seq_len": args.max_seq_len, "token_counts": "exact (Qwen tokenizer, chat template, think off)" if tok else "estimated",
        "files": {n: {"sha256": sha256_file(p), "examples": sum(1 for _ in open(p, encoding="utf-8"))} for n, p in files.items()},
        "doc_ids": {"train": sorted({e["doc_id"] for e in train}), "val": sorted(val_ids), "eval": sorted({e["doc_id"] for e in eval_ex})},
        "examples_per_section": per_section, "dropped": dropped, "sections_without_cited_pages": no_pages,
        "skipped": [], "eval_leak_check": "passed",
    }
    write_json(SFT_DIR / "MANIFEST.json", manifest)

    print(f"unit=section  max_seq_len={args.max_seq_len}  tokens: {manifest['token_counts']}")
    print(f"examples: train={len(train)} val={len(val)} eval={len(eval_ex)}  (val docs: {', '.join(sorted(val_ids))})")
    print(f"{'section':26}{'train':>7}{'val':>6}{'eval':>6}")
    for k, v in per_section.items():
        print(f"{k:26}{v['train']:>7}{v['val']:>6}{v['eval']:>6}")
    print(f"tokens per training example (train+val): {_pcts([e['tokens'] for e in train + val])}")
    print(f"sections with no cited page (no example): {len(no_pages)}; dropped (pages alone do not fit): {len(dropped)}")
    for d in dropped:
        print(f"  dropped {d['doc_id']} {d['section']} bullet {d['bullet']} pages {d['pages']}: {d['tokens']} tokens")
    return 0


def cmd_sft(args) -> int:
    if args.unit == "section":
        return cmd_sft_section(args)
    docs, rows, skipped = usable_docs(), manifest_rows(), []
    sectors = {d: rows[d]["sector"] for d in rows}

    def example(doc_id: str) -> dict | None:
        rec = golden_record(doc_id)
        try:
            target = target_text(rec["summary"])
        except Exception as e:  # pydantic ValidationError
            skipped.append({"doc_id": doc_id, "reason": f"golden summary invalid: {str(e)[:120]}"})
            return None
        if args.mode == "facts":
            fp = FACTS_DIR / f"{doc_id}.json"
            if not fp.is_file():
                skipped.append({"doc_id": doc_id, "reason": "facts not built yet"})
                return None
            facts = read_json(fp)
            if facts["failed_passes"] > args.max_failed_passes:
                skipped.append({"doc_id": doc_id, "reason": f"{facts['failed_passes']} chunk passes failed while building facts"})
                return None
            messages, extra = facts_messages(facts["aggregated"]), {"facts_coverage": facts_coverage(rec["summary"], facts["aggregated"])}
        else:
            messages, extra = text_messages(doc_id, args.text_budget)
            extra = {"text_cut": extra}
        prompt_tokens = estimate_tokens("".join(m["content"] for m in messages))
        total = prompt_tokens + estimate_tokens(target)
        if total > args.max_seq_len:
            skipped.append({"doc_id": doc_id, "reason": f"~{total} tokens > max_seq_len {args.max_seq_len} (dropped, not truncated)"})
            return None
        return {"doc_id": doc_id, "sector": sectors[doc_id], "mode": args.mode, "est_tokens": total,
                "messages": messages + [{"role": "assistant", "content": target}], **extra}

    train_all = [e for d in docs["train"] if (e := example(d))]
    eval_ex = [e for d in docs["eval"] if (e := example(d))]
    val_ids = choose_val([e["doc_id"] for e in train_all], sectors)
    val = [e for e in train_all if e["doc_id"] in val_ids]
    train = [e for e in train_all if e["doc_id"] not in val_ids]

    eval_ids = {e["doc_id"] for e in eval_ex} | set(splits()["eval"])
    assert_no_leak({e["doc_id"] for e in train}, {e["doc_id"] for e in val}, eval_ids)

    def write_jsonl(name: str, rows_: list[dict]) -> Path:
        path = SFT_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_), encoding="utf-8")
        return path

    def issuer_of(doc_id: str) -> str:  # what agent.py falls back to when the model leaves the issuer blank
        fp = FACTS_DIR / f"{doc_id}.json"
        return read_json(fp)["aggregated"].get("issuing_organization", "Not identified") if fp.is_file() else "Not identified"

    eval_inputs = [{"doc_id": e["doc_id"], "sector": e["sector"], "mode": e["mode"], "messages": e["messages"][:2],
                    "issuer": issuer_of(e["doc_id"]), "golden": golden_record(e["doc_id"])["summary"]} for e in eval_ex]
    files = {"train.jsonl": write_jsonl("train.jsonl", train), "val.jsonl": write_jsonl("val.jsonl", val),
             "eval_inputs.jsonl": write_jsonl("eval_inputs.jsonl", eval_inputs)}
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mode": args.mode, "seed": SEED,
        "max_seq_len": args.max_seq_len, "token_counts": "estimated (chars / 3.8); train_lora.py counts exactly",
        "files": {n: {"sha256": sha256_file(p), "examples": sum(1 for _ in open(p, encoding="utf-8"))} for n, p in files.items()},
        "doc_ids": {"train": [e["doc_id"] for e in train], "val": [e["doc_id"] for e in val], "eval": [e["doc_id"] for e in eval_ex]},
        "skipped": skipped, "eval_leak_check": "passed",
    }
    write_json(SFT_DIR / "MANIFEST.json", manifest)

    est = sorted(e["est_tokens"] for e in train + val)
    print(f"mode={args.mode}  train={len(train)}  val={len(val)}  eval={len(eval_ex)}  skipped={len(skipped)}")
    if est:
        print(f"estimated tokens per training example: min {est[0]}, median {est[len(est)//2]}, max {est[-1]}")
    if args.mode == "facts" and train + val:
        cov = [e["facts_coverage"]["bullet_coverage"] for e in train + val]
        print(f"golden bullets visible in the input facts: mean {sum(cov)/len(cov):.0%}, min {min(cov):.0%}")
        for e in train + val:
            if e["facts_coverage"]["bullet_coverage"] < 0.6:
                print(f"  low coverage {e['facts_coverage']['bullet_coverage']:.0%}: {e['doc_id']}")
    for s in skipped:
        print(f"  skipped {s['doc_id']}: {s['reason']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("facts")
    f.add_argument("--only", nargs="*")
    f.add_argument("--limit", type=int)
    s = sub.add_parser("sft")
    s.add_argument("--mode", choices=["facts", "text"], default="facts")
    s.add_argument("--max-seq-len", type=int, default=None, help="default 32768 (whole), 4096 (section)")
    s.add_argument("--max-failed-passes", type=int, default=0,
                   help="facts built with more failed model passes than this are skipped (a failed pass leaves a chunk's facts out)")
    s.add_argument("--text-budget", type=int, default=24000, help="text mode: estimated tokens of RFP text per example")
    s.add_argument("--unit", choices=["whole", "section"], default="whole",
                   help="whole: the app's summary stage (facts or text in, whole summary out). section: pages a section cites -> its bullets")
    s.add_argument("--tokenizer", default=None, help="folder with the Qwen tokenizer files (default models/hf/Qwen3.5-4B)")
    s.add_argument("--out-dir", help="write the jsonl files and MANIFEST.json here instead of data/golden/sft "
                                      "(section unit: data/golden/sft-section)")
    args = ap.parse_args()
    if getattr(args, "max_seq_len", 1) is None:
        args.max_seq_len = 4096 if args.unit == "section" else 32768
    global SFT_DIR
    if getattr(args, "out_dir", None):
        SFT_DIR = Path(args.out_dir)
    elif getattr(args, "unit", None) == "section":
        SFT_DIR = ROOT / "sft-section"
    return cmd_facts(args) if args.cmd == "facts" else cmd_sft(args)


if __name__ == "__main__":
    sys.exit(main())
