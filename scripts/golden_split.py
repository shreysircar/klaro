"""Phase 3: fix the train/eval split once, before any summary exists.

    python -m scripts.golden_split          # refuses if splits.json exists
    python -m scripts.golden_split --force

Stratified by sector (largest-remainder allocation of the eval slots), fixed seed. Docs already used to
tune prompts or demo the app are forced into train so the eval set stays clean.
"""

import csv
import json
import random
import sys

from scripts.golden_lib import ROOT

SEED = 2026
N_EVAL = 10
# Benchmark dev docs (prompt loop) and the app demo RFP: seen during prompt work, never eval.
FORCE_TRAIN = {"it_ippb_tsp", "edu_iiitd_pgcat", "edu_mea_itec", "bfsi_psb_furnish", "edu_svsu_erp", "bfsi_sbi_bacs"}


def main(force: bool) -> int:
    if (ROOT / "splits.json").exists() and not force:
        print("splits.json exists; the split is fixed. Use --force only before any summary is written.")
        return 1
    with open(ROOT / "manifest.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ok = [r for r in rows if r["status"] == "ok"]
    by_sector: dict[str, list[str]] = {}
    for r in ok:
        by_sector.setdefault(r["sector"], []).append(r["doc_id"])

    quota = {s: N_EVAL * len(ids) / len(ok) for s, ids in by_sector.items()}
    alloc = {s: int(q) for s, q in quota.items()}
    for s in sorted(quota, key=lambda s: (quota[s] - alloc[s], s), reverse=True)[:N_EVAL - sum(alloc.values())]:
        alloc[s] += 1

    rng = random.Random(SEED)
    eval_ids = []
    for s in sorted(by_sector):
        pool = sorted(d for d in by_sector[s] if d not in FORCE_TRAIN)
        if len(pool) < alloc[s]:
            raise SystemExit(f"sector {s}: needs {alloc[s]} eval docs, only {len(pool)} eligible")
        eval_ids += rng.sample(pool, alloc[s])
    eval_set = set(eval_ids)
    train_ids = sorted(r["doc_id"] for r in ok if r["doc_id"] not in eval_set)

    (ROOT / "splits.json").write_text(json.dumps({
        "seed": SEED, "method": "stratified by sector, largest-remainder eval allocation, random.Random(seed).sample",
        "forced_train": sorted(FORCE_TRAIN & {r["doc_id"] for r in ok}),
        "train": train_ids, "eval": sorted(eval_ids)}, indent=2) + "\n", encoding="utf-8")
    for r in rows:
        r["split"] = "" if r["status"] != "ok" else ("eval" if r["doc_id"] in eval_set else "train")
    with open(ROOT / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"train {len(train_ids)}  eval {len(eval_ids)}: {sorted(eval_ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--force" in sys.argv))
