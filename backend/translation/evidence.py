"""evidence.json: for each summary bullet, the passages on its cited pages it was most likely built from.

The pipeline carries no quote from a fact to its source (facts have only `text` and `page`), so the
passages are found afterwards: segments on the cited pages are picked greedily by how many of the bullet's
words they add. If together they cover less than MATCH_THRESHOLD of the bullet, no passage is claimed
(quote_* null, passages empty). Nothing is guessed.
"""

import json
import re
from pathlib import Path

from backend.translation.segments import segment_page

SECTIONS = [
    "overview", "scope", "key_requirements", "eligibility", "important_dates",
    "commercial_requirements", "project_duration", "important_conditions",
]
MATCH_THRESHOLD = 0.6
MAX_PASSAGES = 4  # segments one bullet may be traced to
MIN_GAIN = 0.15  # share of the bullet's words a further segment must add


def _tokens(text: str) -> set[str]:
    # 5-letter prefixes make "submitted"/"submission" match; numbers of any length count.
    return {w[:5] for w in re.findall(r"\w+", text.lower()) if len(w) >= 4 or w.isdigit()}


def cover(bullet: str, candidates: list[dict]) -> tuple[float, list[dict]]:
    """Greedy cover of the bullet's words by segments: each pick adds the most not-yet-covered words.
    -> (share of the bullet's words covered 0..1, picked segments in reading order)."""
    want = _tokens(bullet)
    if len(want) < 3:
        return 0.0, []
    own = [(s, _tokens(s["en"]) & want) for s in candidates]
    min_gain = max(2, round(MIN_GAIN * len(want)))  # a segment must add real content, not "shall"/"provide"
    covered: set[str] = set()
    picked: list[dict] = []
    while len(picked) < MAX_PASSAGES:
        seg, hit = max(own, key=lambda p: len(p[1] - covered), default=(None, set()))
        if seg is None or len(hit - covered) < min_gain:
            break
        picked.append(seg)
        covered |= hit
    picked.sort(key=lambda s: candidates.index(s))
    return len(covered) / len(want), picked


def _items(summary: dict):
    for section in SECTIONS:
        val = summary.get(section)
        entries = [val] if isinstance(val, dict) else val if isinstance(val, list) else []
        i = 0
        for e in entries:
            text = (e.get("text") if isinstance(e, dict) else e) or ""
            if not str(text).strip():
                continue  # the renderer skips these too, so ids match the rendered order
            pages = [p for p in (e.get("pages", []) if isinstance(e, dict) else []) if isinstance(p, int)]
            yield f"{section}-{i}", section, str(text).strip(), pages
            i += 1


def build_evidence(run_dir: Path, source_lang: str, segments: list[dict] | None, pages_en: list[dict]) -> Path:
    """`segments` is the translation's segment list (German runs); None for English runs."""
    summary = json.loads((run_dir / "summary" / "executive_summary.json").read_text(encoding="utf-8"))
    if segments is None:
        segments = [{"page": p["page"], "src": s, "en": s} for p in pages_en for s in segment_page(p["text"])]
    for n, seg in enumerate(segments):
        seg.setdefault("id", f"p{seg['page']}-{n}")  # English runs have no translation ids
    by_page: dict[int, list[dict]] = {}
    for seg in segments:
        by_page.setdefault(seg["page"], []).append(seg)

    items = []
    for item_id, section, bullet, pages in _items(summary):
        candidates = [seg for p in sorted(set(pages)) for seg in by_page.get(p, [])]
        score, picked = cover(bullet, candidates)
        found = score >= MATCH_THRESHOLD
        picked = picked if found else []
        passages = [
            {"page": p, "segment_ids": [s["id"] for s in picked if s["page"] == p],
             "quote_en": "\n".join(s["en"] for s in picked if s["page"] == p),
             "quote_src": "\n".join(s["src"] for s in picked if s["page"] == p)}
            for p in sorted({s["page"] for s in picked})
        ]
        items.append({
            "id": item_id, "section": section, "bullet": bullet,
            "page": passages[0]["page"] if passages else (pages[0] if pages else None),
            "quote_en": passages[0]["quote_en"] if passages else None,
            "quote_src": passages[0]["quote_src"] if passages else None,
            "segment_ids": [i for p in passages for i in p["segment_ids"]],
            "passages": passages,  # every page the bullet draws on; quote_* above are the first page's
            "match_score": round(score, 2),
        })
    out = {
        "source_lang": source_lang,
        "flagged_segments": sum(bool(s.get("flags")) for s in segments) if source_lang != "en" else 0,
        "items": items,
    }
    path = run_dir / "evidence.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    # Rebuild evidence.json for a finished auto/de run: python -m backend.translation.evidence <run dir>
    import sys

    run = Path(sys.argv[1])
    meta = json.loads((run / "run_metadata.json").read_text(encoding="utf-8"))
    lang = meta.get("source_language", "en")
    seg_file = run / "translation" / "segments.json"
    segs = json.loads(seg_file.read_text(encoding="utf-8")) if seg_file.is_file() else None
    pages = json.loads(next((run / "extracted").glob("*.json")).read_text(encoding="utf-8"))
    print(build_evidence(run, lang, segs, pages))
