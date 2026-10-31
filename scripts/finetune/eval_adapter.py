"""Compare the base model and the tuned model on the 10 held-out eval documents.

    python -m scripts.finetune.eval_adapter --tuned klaro-qwen-ft                    base and tuned
    python -m scripts.finetune.eval_adapter --tuned klaro-qwen-ft --only tuned       just one side
    python -m scripts.finetune.eval_adapter --score-only data/golden/eval_runs/klaro-qwen-ft   rescore saved outputs

The summary stage is run through Ollama exactly as the app does (system prompt, facts, think off, temperature 0.1),
so this measures the model that is actually served (quantised), not the training-time weights.
Output: data/golden/eval_runs/<tuned tag>/{base,tuned}/<doc>.json, results.csv, summary.md.
Refuses to run if any eval document appears in the training MANIFEST or in the adapter's run_info.json.
"""

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

from scripts.finetune.common import EVAL_RUNS_DIR, INFERENCE_OPTIONS, OLLAMA_BASE_TAG, SFT_DIR, read_json, write_json
from scripts.golden_checks import (COND_LIMITS, GROUNDING_MIN, LIMITS, NUM_RE, ORG_MAX_CHARS, OVERVIEW_MAX_WORDS,
                                   content_words, squash)
from scripts.golden_lib import CONDITION_PREFIXES, LIST_KEYS, NOT_SPECIFIED, items, load_pages

SECTIONS = ["overview", "issuing_organization", *LIST_KEYS]


def refuse_if_leaking(eval_ids: set[str], adapter: Path | None) -> None:
    manifest = read_json(SFT_DIR / "MANIFEST.json")
    seen = set(manifest["doc_ids"]["train"]) | set(manifest["doc_ids"]["val"])
    if adapter and (adapter / "run_info.json").is_file():
        info = read_json(adapter / "run_info.json")
        seen |= set(info.get("train_docs", [])) | set(info.get("val_docs", []))
    if eval_ids & seen:
        sys.exit(f"Refusing to evaluate: these eval documents were used for training or validation: {sorted(eval_ids & seen)}")


def generate(tag: str, messages: list[dict], timeout: float) -> tuple[str, float]:
    import ollama

    from backend.config import OLLAMA_URL  # same host as the app; a long timeout, as a 20k-token prompt takes minutes

    t0 = time.time()
    client = ollama.Client(host=OLLAMA_URL, timeout=timeout)
    resp = client.chat(model=tag, think=False, options=INFERENCE_OPTIONS, messages=messages)
    return (resp.message.content or "").strip(), round(time.time() - t0, 1)


def parse(raw: str, issuer: str) -> tuple[dict | None, bool, str | None]:
    """-> (summary dict or None, strict json ok, error). Uses the app's own tolerant parser."""
    from backend.llm.executive_summary.agent import parse_agent_response

    body = raw.strip()
    body = re.sub(r"^```\w*\n|\n```$", "", body)
    try:
        json.loads(body)
        strict = True
    except json.JSONDecodeError:
        strict = False
    try:
        return parse_agent_response(raw, issuer).model_dump(), strict, None
    except Exception as e:  # pydantic ValidationError and anything the parser raises
        return None, strict, f"{type(e).__name__}: {str(e)[:160]}"


def score(summary: dict | None, golden: dict, doc_id: str) -> dict:
    """All checks reuse scripts/golden_checks.py logic (limits, grounding words, number matching)."""
    if summary is None:
        return {"schema_valid": 0}
    pages = load_pages(doc_id)
    its = [(s, i, t, p) for s, i, t, p in items(summary) if s != "issuing_organization"]
    real = [x for x in its if NOT_SPECIFIED not in x[2]]

    limits_ok = all(len(summary[k]) <= v for k, v in LIMITS.items())
    limits_ok &= len(summary["overview"]["text"].split()) <= OVERVIEW_MAX_WORDS
    limits_ok &= len(summary["issuing_organization"]) <= ORG_MAX_CHARS
    conds = summary["important_conditions"]
    limits_ok &= all(sum(c["text"].startswith(p) for c in conds) <= n for p, n in COND_LIMITS.items() if p != "Submission:")
    limits_ok &= sum(c["text"].startswith(("Evaluation:", "Submission:")) for c in conds) <= 8
    prefix_ok = all(c["text"].startswith(CONDITION_PREFIXES) for c in conds)

    has_page = [bool(p) and all(q in pages for q in p) for _s, _i, _t, p in real]
    nums = nums_ok = grounded = 0
    for _s, _i, text, cited in real:
        on_page = squash(" ".join(pages.get(p, "") for p in cited))
        for n in NUM_RE.findall(text.translate({0x2018: "'", 0x2019: "'"})):
            nums += 1
            nums_ok += n in on_page
        near = " ".join(pages.get(q, "") for p in cited for q in (p - 1, p, p + 1))
        w = content_words(text)
        grounded += bool(w) and len(w & content_words(near)) / len(w) >= GROUNDING_MIN

    def sec_words(s: dict, key: str) -> set[str]:
        v = s[key]
        return content_words(v["text"] if isinstance(v, dict) else v if isinstance(v, str) else " ".join(i["text"] for i in v))

    sim = {}
    for key in SECTIONS:
        a, b = sec_words(summary, key), sec_words(golden, key)
        sim[key] = round(len(a & b) / len(a | b), 3) if a | b else 1.0
    words = lambda s: sum(len(t.split()) for _a, _b, t, _c in items(s))
    return {
        "schema_valid": 1, "limits_ok": int(limits_ok), "condition_prefix_ok": int(prefix_ok),
        "bullets": len(real), "bullets_with_page": round(sum(has_page) / len(real), 3) if real else 0.0,
        "numbers": nums, "numbers_on_page": round(nums_ok / nums, 3) if nums else 1.0,
        "grounded": round(grounded / len(real), 3) if real else 0.0,
        "words": words(summary), "golden_words": words(golden), "length_ratio": round(words(summary) / max(1, words(golden)), 2),
        "similarity_mean": round(sum(sim.values()) / len(sim), 3), **{f"sim_{k}": v for k, v in sim.items()},
    }


def run_side(label: str, tag: str, rows: list[dict], out: Path, reuse: bool, timeout: float = 1800) -> list[dict]:
    results = []
    for n, row in enumerate(rows, start=1):
        doc_id, path = row["doc_id"], out / label / f"{row['doc_id']}.json"
        issuer, gen_error = row.get("issuer", "Not identified"), None
        if path.is_file() and reuse:  # only when asked: a retuned model under the same tag must not reuse old outputs
            saved = read_json(path)
            raw, secs = saved["raw"], saved["seconds"]
        else:
            print(f"[{label} {n}/{len(rows)}] {doc_id} ...", flush=True)
            try:
                raw, secs = generate(tag, row["messages"], timeout)
            except Exception as e:  # one failed call is a result (schema invalid), not a reason to lose the other 9
                raw, secs, gen_error = "", 0.0, f"{type(e).__name__}: {str(e)[:200]}"
                print(f"   FAILED: {gen_error}", flush=True)
        summary, strict, err = parse(raw, issuer)
        err = gen_error or err
        write_json(path, {"doc_id": doc_id, "model": tag, "seconds": secs, "raw": raw, "strict_json": strict, "error": err, "summary": summary})
        results.append({"doc_id": doc_id, "model_label": label, "model": tag, "seconds": secs, "strict_json": int(strict),
                        **score(summary, row["golden"], doc_id)})
    return results


def write_report(results: list[dict], out: Path) -> None:
    cols = sorted({k for r in results for k in r}, key=lambda k: (k not in ("doc_id", "model_label", "model"), k))
    with open(out / "results.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(results)
    metrics = [("schema valid", "schema_valid"), ("strict JSON", "strict_json"), ("section limits respected", "limits_ok"),
               ("condition prefixes ok", "condition_prefix_ok"), ("bullets with a page", "bullets_with_page"),
               ("numbers verbatim on cited page", "numbers_on_page"), ("content-word grounding", "grounded"),
               ("length vs golden (words ratio)", "length_ratio"), ("similarity to golden (mean of sections)", "similarity_mean"),
               ("seconds per summary", "seconds")]
    labels = sorted({r["model_label"] for r in results}, key=lambda l: l != "base")
    lines = ["| metric | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    for name, key in metrics:
        cells = []
        for lab in labels:
            vals = [r[key] for r in results if r["model_label"] == lab and key in r]
            cells.append(f"{sum(vals) / len(vals):.2f}" if vals else "-")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", f"{len({r['doc_id'] for r in results})} eval documents. Means over documents; schema-invalid outputs count as 0 "
              "for schema valid and are left out of the other means. Per-document numbers: results.csv.",
              "Numbers and grounding use the same logic as scripts/golden_checks.py. Similarity is Jaccard of content words "
              "against the golden summary, per section. Golden summaries are auto_checked drafts unless a doc is `verified`."]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tuned", help="Ollama tag of the tuned model, e.g. klaro-qwen-ft")
    ap.add_argument("--base", default=OLLAMA_BASE_TAG)
    ap.add_argument("--only", choices=["base", "tuned"])
    ap.add_argument("--adapter", help="adapter folder, to check its run_info.json for leaked eval docs")
    ap.add_argument("--inputs", default=str(SFT_DIR / "eval_inputs.jsonl"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--timeout", type=float, default=1800, help="seconds per model call")
    ap.add_argument("--resume", action="store_true", help="reuse outputs already saved in the run folder")
    ap.add_argument("--score-only", metavar="RUN_DIR", help="rescore the outputs already saved in this run folder")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.inputs).read_text(encoding="utf-8").splitlines() if l.strip()][:args.limit]
    refuse_if_leaking({r["doc_id"] for r in rows}, Path(args.adapter) if args.adapter else None)
    if args.score_only:
        out, tuned = Path(args.score_only), args.tuned or "tuned"
    else:
        if not args.tuned and args.only != "base":
            sys.exit("Give --tuned <ollama tag>, or --only base.")
        out, tuned = EVAL_RUNS_DIR / (args.tuned or "base-only"), args.tuned
        from backend.config import preflight_error
        if (problem := preflight_error()):
            sys.exit(problem)
    out.mkdir(parents=True, exist_ok=True)
    sides = [("base", args.base)] + ([("tuned", tuned)] if tuned else [])
    results = []
    for label, tag in sides:
        if args.only and label != args.only:
            continue
        results += run_side(label, tag, rows, out, bool(args.score_only or args.resume), args.timeout)
    write_report(results, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
