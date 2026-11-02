"""Stage 5 only, from saved golden facts: run the summary agent with one configuration over the dev docs and measure it.

    .venv/bin/python scripts/summary_eval.py --label baseline --prompt v1 --ctx 0
    .venv/bin/python scripts/summary_eval.py --label v2 --prompt v2 --ctx 16384
    .venv/bin/python scripts/summary_eval.py --label v2b --prompt v2 --ctx 16384 --system-file experiments/prompts/v2b.txt

Dev docs = every data/golden/facts/*.json whose doc is in the train split (never the eval split). Writes
experiments/out/<label>/<doc>.json, experiments/out/<label>/metrics.json, and appends a row to experiments/summary-ledger.csv
(the verdict column is filled by hand). The golden summary similarity is a weak signal: the goldens are auto_checked, not human verified.
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "translation_ab"))

from chrf import chrf  # noqa: E402

from backend import config  # noqa: E402
from backend.evaluation.evaluate_summary import check_duplication, check_traceability_and_grounding  # noqa: E402
from backend.llm.executive_summary import agent  # noqa: E402

LISTS = ["scope", "key_requirements", "eligibility", "important_dates", "commercial_requirements", "project_duration", "important_conditions"]
LIMITS = {"scope": 8, "key_requirements": 10, "eligibility": 8, "important_dates": 15, "commercial_requirements": 8, "project_duration": 3, "important_conditions": 10}
OVERVIEW_WORDS = 80
NUM = re.compile(r"\d[\d.,']*\d|\d")
LEDGER = ROOT / "experiments" / "summary-ledger.csv"
COLS = ["label", "change", "prompt", "num_ctx", "docs", "words_total", "overview_words", "limits_ok_docs", "grounding_pct", "traceability_pct",
        "dup_bullets", "cited_pct", "numbers_on_page_pct", "issuer_correct", "issuer_partial", "similarity", "seconds", "prompt_tokens", "truncated_docs", "verdict"]


def dev_docs() -> list[str]:
    train = {json.loads(l)["doc_id"] for l in (ROOT / "data/golden/train.jsonl").read_text(encoding="utf-8").splitlines()}
    docs = sorted(p.stem for p in (ROOT / "data/golden/facts").glob("*.json"))
    return [d for d in docs if d in train]


def items(summary: dict):
    for k in LISTS:
        for it in summary.get(k, []):
            yield k, it


def words(t: str) -> int:
    return len(t.split())


def digits(tok: str) -> str:
    return re.sub(r"\D", "", tok).lstrip("0")


def numbers_on_pages(summary: dict, pages_text: dict[int, str]) -> tuple[int, int]:
    ok = total = 0
    for _, it in items(summary):
        if not it["pages"]:
            continue
        page_digits = {digits(t) for p in it["pages"] for t in NUM.findall(pages_text.get(p, ""))}
        for tok in NUM.findall(it["text"]):
            if digits(tok):
                total += 1
                ok += digits(tok) in page_digits
    return ok, total


def dup_bullets(summary: dict) -> int:
    bags = [(set(re.findall(r"\w+", it["text"].lower())), it) for _, it in items(summary)]
    bags = [b for b in bags if len(b[0]) >= 4]
    dup = set()
    for i in range(len(bags)):
        for j in range(i + 1, len(bags)):
            a, b = bags[i][0], bags[j][0]
            if len(a & b) / len(a | b) >= 0.7:
                dup.update((i, j))
    return len(dup)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def issuer_status(out: str, golden: str) -> str:
    name = norm(re.split(r"[;\n]", golden)[0])
    o = norm(out)
    if not o or o == "not identified":
        return "missing"
    if name and (name in o or o in name and len(o.split()) >= 3 and o == name):
        return "correct"
    if o and (o in norm(golden) or o in name):
        return "partial"
    return "wrong"


def similarity(summary: dict, golden: dict) -> float:
    """Mean chrF between the joined text of each section and the golden's. Weak: goldens are auto_checked only."""
    scores = []
    for k in LISTS:
        a = " ".join(i["text"] for i in summary.get(k, []))
        b = " ".join(i["text"] if isinstance(i, dict) else i for i in golden.get(k, []))
        if b:
            scores.append(chrf(a, b))
    return sum(scores) / len(scores) if scores else 0.0


def ps_memory() -> tuple[int | None, int | None]:
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_URL}/api/ps", timeout=5) as r:
            m = json.load(r)["models"]
        return (m[0].get("context_length"), m[0].get("size")) if m else (None, None)
    except Exception:
        return None, None


def TOK(text: str):
    from transformers import AutoTokenizer

    global _tok
    _tok = globals().get("_tok") or AutoTokenizer.from_pretrained(ROOT / "models/hf/Qwen3.5-4B")
    return _tok(text)


class Spy:
    """Wraps the Ollama client so the harness sees prompt_eval_count and the loaded context, without changing the agent."""

    def __init__(self, real):
        self.real, self.last, self.ps = real, None, (None, None)

    def chat(self, **kw):
        r = self.real.chat(**kw)
        self.last = r
        self.ps = ps_memory()
        return r


def run(label: str, change: str, prompt: str, ctx: int, system_file: str | None, only: list[str] | None) -> dict:
    config.SUMMARY_PROMPT, config.NUM_CTX = prompt, ctx
    if system_file:
        agent.EXECUTIVE_SUMMARY_AGENT_SYSTEM_PROMPT_V2 = Path(system_file).read_text(encoding="utf-8")
    spy = Spy(agent.llm)
    agent.llm = spy
    out_dir = ROOT / "experiments" / "out" / label
    out_dir.mkdir(parents=True, exist_ok=True)
    train = {json.loads(l)["doc_id"]: json.loads(l) for l in (ROOT / "data/golden/train.jsonl").read_text(encoding="utf-8").splitlines()}
    rows = []
    for doc in only or dev_docs():
        facts = json.loads((ROOT / f"data/golden/facts/{doc}.json").read_text(encoding="utf-8"))["aggregated"]
        fpath = out_dir / f"{doc}.facts.json"
        fpath.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
        t0 = time.time()
        summary = agent.run_executive_summary_agent(fpath, out_dir / f"{doc}.json").model_dump()
        seconds = time.time() - t0
        fpath.unlink()
        pages = {p["page"]: p["text"] for p in json.loads((ROOT / f"data/golden/handoff/extracted/{doc}.json").read_text(encoding="utf-8"))}
        _, ground, _ = check_traceability_and_grounding(summary, facts)
        trace = check_traceability_and_grounding(summary, facts)[0]
        listed = [it for _, it in items(summary)]
        ok, total = numbers_on_pages(summary, pages)
        ow = words(summary["overview"]["text"])
        counts = {k: len(summary[k]) for k in LISTS}
        ctx_len, mem = spy.ps
        ptoks = spy.last.prompt_eval_count or 0
        system = agent.EXECUTIVE_SUMMARY_AGENT_SYSTEM_PROMPT_V2 if prompt == "v2" else agent.EXECUTIVE_SUMMARY_AGENT_SYSTEM_PROMPT
        expected = len(TOK(system + agent.build_agent_user_prompt(json.dumps(facts, indent=2, ensure_ascii=False)))["input_ids"])
        sent_ctx = ctx_len or (4096 if not ctx else ctx)
        rows.append({
            "doc": doc, "seconds": round(seconds, 1), "prompt_tokens": ptoks, "context": sent_ctx, "ollama_memory_bytes": mem,
            "expected_prompt_tokens": expected, "truncated": ptoks < 0.75 * expected,
            "words_total": ow + sum(words(i["text"]) for i in listed), "overview_words": ow,
            "limits_ok": ow <= OVERVIEW_WORDS and all(counts[k] <= LIMITS[k] for k in LISTS), "counts": counts,
            "cited_pct": 100 * sum(bool(i["pages"]) for i in listed) / max(1, len(listed)),
            "grounding_pct": ground["grounding_percentage"], "traceability_pct": trace["traceability_percentage"],
            "numbers_ok": ok, "numbers_total": total, "dup_bullets": dup_bullets(summary),
            "issuer": summary["issuing_organization"], "issuer_golden": train[doc]["summary"]["issuing_organization"][:80],
            "issuer_status": issuer_status(summary["issuing_organization"], train[doc]["summary"]["issuing_organization"]),
            "similarity": round(similarity(summary, train[doc]["summary"]), 1),
        })
        print(json.dumps({k: v for k, v in rows[-1].items() if k != "counts"}, ensure_ascii=False), flush=True)
    mean = lambda k: round(sum(r[k] for r in rows) / len(rows), 1)
    agg = {
        "label": label, "change": change, "prompt": prompt, "num_ctx": ctx, "docs": len(rows),
        "words_total": mean("words_total"), "overview_words": mean("overview_words"), "limits_ok_docs": f"{sum(r['limits_ok'] for r in rows)}/{len(rows)}",
        "grounding_pct": mean("grounding_pct"), "traceability_pct": mean("traceability_pct"), "dup_bullets": mean("dup_bullets"),
        "cited_pct": mean("cited_pct"), "numbers_on_page_pct": round(100 * sum(r["numbers_ok"] for r in rows) / max(1, sum(r["numbers_total"] for r in rows)), 1),
        "issuer_correct": sum(r["issuer_status"] == "correct" for r in rows), "issuer_partial": sum(r["issuer_status"] == "partial" for r in rows),
        "similarity": mean("similarity"), "seconds": mean("seconds"), "prompt_tokens": mean("prompt_tokens"),
        "truncated_docs": sum(r["truncated"] for r in rows), "verdict": "",
    }
    (out_dir / "metrics.json").write_text(json.dumps({"summary": agg, "docs": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    new = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS)
        if new:
            w.writeheader()
        w.writerow(agg)
    print("LEDGER", json.dumps(agg, ensure_ascii=False))
    return agg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--change", default="")
    ap.add_argument("--prompt", choices=["v1", "v2"], default="v1")
    ap.add_argument("--ctx", type=int, default=0, help="KLARO_NUM_CTX cap; 0 = Ollama default")
    ap.add_argument("--system-file", help="replace the v2 system prompt with this file (experiments only)")
    ap.add_argument("--docs", nargs="*", help="only these doc ids")
    a = ap.parse_args()
    run(a.label, a.change, a.prompt, a.ctx, a.system_file, a.docs)
