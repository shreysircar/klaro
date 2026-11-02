"""Protected spans (numbers, amounts, dates, ...) for the translation A/B harness: find them, mask them with
placeholders before translating, restore them afterwards, and score how many survived."""

import re

_MONTH = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
          r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)")
_CUR = r"(?:INR|EUR|USD|GBP|Rs\.?|₹|\$|€|£)"
# (category, regex). Earlier categories win overlaps. Textual dates ("12 December 2026") are NOT masked whole: the
# month name has to be translated, so only their digits are protected (by "number").
PATTERNS = [
    ("url", r"https?://[^\s)]+|www\.[^\s)]+"),
    ("email", r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    ("cite", r"\b(?:pp?\.|[Pp]ages?|Seiten?)\s*\d+(?:\s*[-–,]\s*\d+)*"),
    ("date", r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"),
    ("amount", rf"{_CUR}\s?\d[\d.,]*(?:\s?(?:lakh|crore|million|billion|mn|bn|cr)\b)?|\d[\d.,]*\s?{_CUR}(?!\w)"),
    ("percent", r"\d+(?:[.,]\d+)?\s?%"),
    ("reference", r"\b[A-Z0-9]{2,}(?:[/_-][A-Z0-9]+){1,}\b"),
    ("acronym", r"\b[A-Z][A-Z0-9]{1,}\b"),
    ("number", r"\d[\d.,']*\d|\d"),
]
_COMBINED = [(c, re.compile(p)) for c, p in PATTERNS]

# Placeholder styles to try. {} is the index. Which one survives Marian's tokenizer is measured, not assumed.
STYLES = {
    "brackets": "[{}]", "braces": "{{{}}}", "angle": "<{}>", "xtag": "<x{}>", "section": "§{}§",
    "hash": "#{}#", "word": "ZQ{}ZQ", "paren": "({})",
}


def spans(text: str, extra: dict[str, str] | None = None, only: tuple[str, ...] | None = None) -> list[tuple[int, int, str]]:
    """Non-overlapping (start, end, category) of every protected span, in text order.
    `extra` is a reviewed glossary {term: replacement}; its spans are category "glossary" and win overlaps.
    `only` limits the categories (so a glossary-only variant masks nothing else)."""
    taken: list[tuple[int, int, str]] = []
    if extra:
        rx = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t) for t in sorted(extra, key=len, reverse=True)) + r")(?!\w)", re.I)
        taken += [(*m.span(), "glossary") for m in rx.finditer(text)]
    for cat, rx in _COMBINED:
        if only is not None and cat not in only:
            continue
        for m in rx.finditer(text):
            a, b = m.span()
            if not any(a < e and b > s for s, e, _ in taken):
                taken.append((a, b, cat))
    return sorted(taken)


def tokens(text: str) -> list[tuple[str, str]]:
    return [(cat, text[a:b]) for a, b, cat in spans(text)]


def mask(text: str, style: str, extra: dict[str, str] | None = None, only: tuple[str, ...] | None = None) -> tuple[str, list[str]]:
    """-> (masked text, what to put back by index). Placeholders count from 1. Glossary spans put back the
    glossary's replacement, every other span puts back the original text."""
    fmt, out, last, originals = STYLES[style], [], 0, []
    lower = {k.lower(): v for k, v in (extra or {}).items()}
    for a, b, cat in spans(text, extra, only):
        originals.append(lower[text[a:b].lower()] if cat == "glossary" else text[a:b])
        out += [text[last:a], fmt.format(len(originals))]
        last = b
    out.append(text[last:])
    return "".join(out), originals


def survived(raw: str, originals: list[str], style: str) -> int:
    """How many placeholders appear exactly once in the raw translation."""
    return sum(raw.count(STYLES[style].format(i)) == 1 for i in range(1, len(originals) + 1))


def unmask(raw: str, originals: list[str], style: str) -> str:
    for i, original in enumerate(originals, start=1):
        raw = raw.replace(STYLES[style].format(i), original)
    return raw


def _canon(token: str) -> str:
    return re.sub(r"\D", "", token).lstrip("0")


def preserved(en: str, de: str) -> tuple[int, int]:
    """(protected tokens of the English text that are in the German one, total). Numbers, dates, amounts and
    percentages match by their digits (1,000.00 = 1.000,00); the rest must appear verbatim."""
    digits_in_de = {_canon(t) for t in re.findall(r"\d[\d.,']*\d|\d", de)}
    parts_in_de = {_canon(p) for t in re.findall(r"\d[\d.,']*\d|\d", de) for p in re.split(r"[.,']", t)}
    ok = total = 0
    for cat, tok in tokens(en):
        total += 1
        if cat in ("number", "date", "amount", "percent", "cite"):
            digs = _canon(tok)
            parts = [_canon(p) for p in re.split(r"\D+", tok) if _canon(p)]
            ok += bool(digs in digits_in_de or (parts and all(p in parts_in_de for p in parts)))
        else:
            ok += tok in de
    return ok, total
