"""English -> German copy of a finished run's summary, made on demand (never during the analysis run).

    python -m backend.translation.translate_summary <run_dir> --target de [--progress-json]

Reads  <run_dir>/summary/executive_summary.json
Writes <run_dir>/summary/executive_summary_de.{json,md,html} (same names as the opt-in --german-summary) and
       executive_summary_de.meta.json (flags, timing). Only text values are translated: keys, bullet order, page
cites and the issuer's name stay as they are, so bullet ids (`<section>-<i>`, as in evidence.json) are identical
in both languages. Output appears only when everything is done: a cancelled run leaves nothing half-written.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from backend.llm.executive_summary.render_summary import render_summary_files
from backend.translation.evidence import SECTIONS
from backend.translation.segments import _NUMBER, _cap, _digits

SRC, TGT = "en", "de"
SUMMARY = "executive_summary.json"
# Seconds per segment for the UI estimate. Measured 0.05 with the de->en model as a proxy (Apple silicon, CPU, batches of 8); kept 3x higher to be safe.
DEFAULT_SECONDS_PER_SEGMENT = 0.15

_ABBREVIATIONS = {
    "e.g", "i.e", "etc", "no", "nos", "vs", "approx", "inc", "ltd", "pvt", "co", "rs", "dr", "mr", "mrs", "ms", "st",
    "sr", "jr", "art", "sec", "cl", "fig", "para", "viz", "incl", "min", "max", "est", "dept", "govt", "ref", "sl",
}
_SENTENCE_GAP = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_CURRENCY = re.compile(r"[₹$€£]|\b(?:INR|EUR|USD|GBP|Rs)\b")


def split_sentences(text: str) -> list[str]:
    """Sentences of one bullet, each at most 600 characters. Abbreviations like "e.g." and "No." do not end one."""
    out: list[str] = []
    for piece in _SENTENCE_GAP.split(text.strip()):
        last = out[-1].split()[-1].rstrip(".").lower() if out else ""
        if out and (last in _ABBREVIATIONS or (len(last) == 1 and last.isalpha())):
            out[-1] += " " + piece
        else:
            out.append(piece)
    return [part for sentence in out for part in _cap(sentence)]


def slots(data: dict) -> Iterator[tuple[str, dict | list, str | int]]:
    """(bullet id, container, key) for every non-empty text, in the order the renderer shows them.
    The ids are the ones evidence.json and the summary iframe use."""
    for section in SECTIONS:
        val = data.get(section)
        if isinstance(val, str) and val.strip():
            yield f"{section}-0", data, section
            continue
        entries = [val] if isinstance(val, dict) else val if isinstance(val, list) else []
        n = 0
        for i, e in enumerate(entries):
            if isinstance(e, dict) and isinstance(e.get("text"), str) and e["text"].strip():
                yield f"{section}-{n}", e, "text"
            elif isinstance(e, str) and e.strip():
                yield f"{section}-{n}", entries, i
            else:
                continue  # the renderer skips these too
            n += 1


def count_segments(data: dict) -> int:
    return len({s for _, box, key in slots(data) for s in split_sentences(box[key])})


def fidelity_flags(en: str, de: str) -> list[str]:
    """Every number, date and amount of the English bullet must be in the German one. Separators do not matter
    (1,000.00 equals 1.000,00), and a numeric date may be written whole or by its parts (12/12/2026, 12.12.2026)."""
    have = set()
    for token in _NUMBER.findall(de):
        have.add(_digits(token))
        have.update(_digits(p) for p in re.split(r"[.,'’]", token))
    flags = []
    for token in _NUMBER.findall(en):
        whole = _digits(token)
        parts = [_digits(p) for p in re.split(r"[.,'’]", token) if _digits(p)]
        if whole and whole not in have and not (parts and all(p in have for p in parts)):
            flags.append(f"number_mismatch:{token}")
    flags += [f"currency_missing:{c}" for c in sorted(set(_CURRENCY.findall(en))) if c not in de]
    return flags


def translate_summary_data(
    data: dict, translate: Callable[[list[str], Callable[[int, int], None] | None], dict[str, str]],
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[dict, list[dict]]:
    """-> (German copy, flags [{id, flags}]). `translate(texts, on_progress)` maps each text to its translation."""
    out = json.loads(json.dumps(data, ensure_ascii=False))
    items = [(i, box, key, split_sentences(box[key])) for i, box, key in slots(out)]
    done = translate([s for *_, parts in items for s in parts], on_progress)
    flagged = []
    for item_id, box, key, parts in items:
        english = box[key]
        german = " ".join(done[s] for s in parts).strip()
        flags = fidelity_flags(english, german) if german else ["empty_translation"]
        box[key] = german or english  # never leave a bullet blank: keep the English and say so
        if flags:
            flagged.append({"id": item_id, "flags": flags})
    return out, flagged


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def translate_run(run_dir: Path, on_progress: Callable[[int, int], None] | None = None) -> dict:
    """Translate and render the run's summary. Returns the meta dict. Raises with a readable message on failure."""
    from backend.translation.translator import check, translate_texts

    summary_dir = run_dir / "summary"
    source = summary_dir / SUMMARY
    if not source.is_file():
        raise FileNotFoundError(f"No summary to translate at {source}.")
    error = check(SRC, TGT)
    if error:
        raise RuntimeError(error)
    data = json.loads(source.read_text(encoding="utf-8-sig"))

    started = time.time()
    german, flagged = translate_summary_data(data, lambda texts, cb: translate_texts(texts, SRC, TGT, cb), on_progress)
    seconds = time.time() - started
    segments = count_segments(data)

    de_json = summary_dir / "executive_summary_de.json"
    staging = summary_dir / ".staging_de"
    staging.mkdir(exist_ok=True)
    try:
        _write(staging / "executive_summary_de.json", json.dumps(german, ensure_ascii=False, indent=2))
        render_summary_files(staging / "executive_summary_de.json", staging, language="de")
        for f in ("md", "html"):
            os.replace(staging / f"executive_summary_de.{f}", summary_dir / f"executive_summary_de.{f}")
        meta = {
            "created_at": datetime.now().isoformat(timespec="seconds"), "model": f"opus-mt-{SRC}-{TGT}",
            "segments": segments, "seconds": round(seconds, 1),
            "seconds_per_segment": round(seconds / segments, 3) if segments else None,
            "flagged_bullets": len(flagged), "flags": flagged,
        }
        _write(summary_dir / "executive_summary_de.meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        os.replace(staging / "executive_summary_de.json", de_json)  # last: its presence means "done"
    finally:
        for f in staging.glob("*"):
            f.unlink(missing_ok=True)
        staging.rmdir()
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Translate a finished run's summary into German (local OPUS-MT).")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--target", choices=["de"], default="de")
    ap.add_argument("--progress-json", action="store_true", help="JSON progress lines on stdout")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    def emit(event: str, **fields) -> None:
        if args.progress_json:
            print(json.dumps({"event": event, **fields}), flush=True)

    try:
        meta = translate_run(args.run_dir, lambda done, total: emit("translate", done=done, total=total))
    except Exception as e:  # surfaces as the job's error message
        emit("error", stage="translate_summary", error=str(e))
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    emit("done", flagged_bullets=meta["flagged_bullets"])
    print(f"Translated {meta['segments']} segments in {meta['seconds']}s; {meta['flagged_bullets']} bullets flagged.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
