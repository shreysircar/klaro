"""A/B harness for OPUS-MT quality without training (Phase 3). Nothing here changes the shipped translator.

    .venv/bin/python scripts/translation_ab/run_ab.py [--docs 10] [--limit-bullets N]

Needs both models (models/opus-mt-en-de and opus-mt-de-en). English golden summaries -> German with each variant ->
(weak signal) back to English with the app's de-en model. Writes results.json, report.md and samples.csv to ./out/.
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import protect  # noqa: E402
from chrf import chrf  # noqa: E402

from backend.llm.executive_summary.translate_summary import load_translation_model, model_dir  # noqa: E402
from backend.translation import translate_summary as ts  # noqa: E402
from backend.translation.translator import installed  # noqa: E402

BATCH = 8
BASE = dict(num_beams=4, max_new_tokens=256)
DECODE = dict(num_beams=5, length_penalty=1.2, no_repeat_ngram_size=4, max_new_tokens=256)
VARIANTS = {  # name -> (generate kwargs, mask, glossary)
    "baseline": (BASE, False, False),
    "decode": (DECODE, False, False),
    "mask": (BASE, True, False),
    "mask+decode": (DECODE, True, False),
    "glossary": (BASE, False, True),
}


def translate(texts: list[str], src: str, tgt: str, gen: dict) -> list[str]:
    import torch

    tok, model = load_translation_model(src, tgt)
    out: list[str] = []
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    res = [""] * len(texts)
    for i in range(0, len(order), BATCH):
        idx = order[i:i + BATCH]
        enc = tok([texts[j] for j in idx], return_tensors="pt", padding=True, truncation=False)
        with torch.inference_mode():
            ids = model.generate(**enc, **gen)
        for j, t in zip(idx, tok.batch_decode(ids, skip_special_tokens=True)):
            res[j] = t.strip()
    return res


def glossary(src: str, tgt: str) -> dict[str, str]:
    """Only rows marked reviewed=yes. Unreviewed rows are proposals and are never applied."""
    path = HERE / f"glossary_{src}_{tgt}.tsv"
    rows = [r for r in csv.DictReader(path.open(encoding="utf-8"), delimiter="\t")]
    return {r[src]: r[tgt] for r in rows if r["reviewed"].strip().lower() == "yes" and r[tgt].strip()}


def run_variant(name: str, segments: list[str], style: str, notes: dict) -> dict[str, str]:
    """-> {english segment: German}. Masked segments that lose a placeholder are retranslated unmasked and flagged."""
    gen, masked, use_glossary = VARIANTS[name]
    terms = glossary("en", "de") if use_glossary else None
    only = None if masked else ("glossary",)  # the glossary variant masks its terms and nothing else
    jobs, plan = [], {}
    for seg in segments:
        text, originals = protect.mask(seg, style, terms, only) if (masked or terms) else (seg, [])
        plan[seg] = (len(jobs), originals)
        jobs.append(text)
    raw = translate(jobs, "en", "de", gen)
    out, retry = {}, []
    for seg, (k, originals) in plan.items():
        if originals:
            notes["placeholders"] += len(originals)
            notes["placeholders_kept"] += protect.survived(raw[k], originals, style)
            if protect.survived(raw[k], originals, style) != len(originals):
                retry.append(seg)
                continue
            out[seg] = protect.unmask(raw[k], originals, style)
        else:
            out[seg] = raw[k]
    if retry:
        notes["retranslated_unmasked"] = len(retry)
        out.update(zip(retry, translate(retry, "en", "de", gen)))
    return out


def pick_style(segments: list[str]) -> tuple[str, dict]:
    sample = [s for s in segments if protect.spans(s)][:120]
    table = {}
    for style in protect.STYLES:
        masked = [protect.mask(s, style) for s in sample]
        raw = translate([m for m, _ in masked], "en", "de", BASE)
        kept = sum(protect.survived(r, o, style) for r, (_, o) in zip(raw, masked))
        table[style] = round(kept / max(1, sum(len(o) for _, o in masked)), 3)
    return max(table, key=table.get), table


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=10)
    ap.add_argument("--limit-bullets", type=int, default=0, help="debug: only the first N bullets per document")
    args = ap.parse_args()
    for src, tgt in (("en", "de"), ("de", "en")):
        if not installed(src, tgt):
            print(f"Model {model_dir(src, tgt)} is missing. Download: .venv/bin/python -m backend.translation.fetch_model {src} {tgt}")
            return 2

    docs = [json.loads(line) for line in (HERE.parents[1] / "data/golden/train.jsonl").read_text(encoding="utf-8").splitlines()]
    docs = [d for d in docs if d["split"] == "train"][: args.docs]
    bullets = []  # (id, english)
    for d in docs:
        items = list(ts.slots(d["summary"]))
        for i, box, key in items[: args.limit_bullets or None]:
            bullets.append((f"{d['doc_id']}:{i}", box[key]))
    segs = {b: ts.split_sentences(t) for b, t in bullets}
    unique = sorted({s for parts in segs.values() for s in parts})
    print(f"{len(docs)} documents, {len(bullets)} bullets, {len(unique)} unique segments")

    style, style_table = pick_style(unique)
    print("placeholder survival by style:", style_table, "-> using", style)

    results, outputs = {}, {}
    for name in VARIANTS:
        if name == "glossary" and not glossary("en", "de"):
            results[name] = {"skipped": "no glossary entry is marked reviewed=yes"}
            continue
        notes = {"placeholders": 0, "placeholders_kept": 0, "retranslated_unmasked": 0}
        t0 = time.time()
        done = run_variant(name, unique, style, notes)
        seconds = time.time() - t0
        german = {b: " ".join(done[s] for s in segs[b]) for b, _ in bullets}
        ok = total = flags = 0
        for b, en in bullets:
            a, t = protect.preserved(en, german[b])
            ok, total = ok + a, total + t
            flags += bool(ts.fidelity_flags(en, german[b]))
        back = translate([german[b] for b, _ in bullets], "de", "en", BASE)
        rt = sum(chrf(h, en) for h, (_, en) in zip(back, bullets)) / len(bullets)
        outputs[name] = german
        results[name] = {
            "protected_preservation": round(ok / total, 4), "placeholder_survival": round(notes["placeholders_kept"] / notes["placeholders"], 4) if notes["placeholders"] else None,
            "retranslated_unmasked": notes["retranslated_unmasked"], "bullets_with_fidelity_flags": flags,
            "roundtrip_chrf": round(rt, 2), "seconds_total": round(seconds, 1), "seconds_per_summary": round(seconds / len(docs), 1),
        }
        print(name, results[name])

    base = results["baseline"]
    verdict = {}
    for name, r in results.items():
        if name == "baseline" or "skipped" in r:
            continue
        verdict[name] = (
            r["protected_preservation"] >= base["protected_preservation"]
            and r["roundtrip_chrf"] >= base["roundtrip_chrf"] - 1.0
            and r["seconds_total"] <= 2 * base["seconds_total"]
        )
    winners = [n for n, v in verdict.items() if v and results[n]["bullets_with_fidelity_flags"] <= base["bullets_with_fidelity_flags"]]
    best = max(winners, key=lambda n: (results[n]["protected_preservation"], results[n]["roundtrip_chrf"])) if winners else None

    out = HERE / "out"
    out.mkdir(exist_ok=True)
    (out / "results.json").write_text(json.dumps({"style": style, "style_survival": style_table, "variants": results, "adopt": best}, indent=2, ensure_ascii=False), encoding="utf-8")
    other = best or "baseline"
    step = max(1, len(bullets) // 15)
    with (out / "samples.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "english", "german_baseline", f"german_{other}", "adequacy_baseline_1to5", f"adequacy_{other}_1to5", "comment"])
        for b, en in bullets[::step][:15]:
            w.writerow([b, en, outputs["baseline"][b], outputs[other][b], "", "", ""])
    lines = ["| variant | protected tokens kept | placeholders kept | fidelity-flagged bullets | round-trip chrF (weak) | s / summary |", "|---|---|---|---|---|---|"]
    for n, r in results.items():
        lines.append(f"| {n} | skipped: {r['skipped']} |||||" if "skipped" in r else
                     f"| {n} | {r['protected_preservation']:.1%} | {'' if r['placeholder_survival'] is None else format(r['placeholder_survival'], '.1%')} | {r['bullets_with_fidelity_flags']} | {r['roundtrip_chrf']} | {r['seconds_per_summary']} |")
    lines.append(f"\nPlaceholder style: `{style}`. Decision: " + (f"adopt `{best}`." if best else "no cheap improvement found."))
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
