"""Split page text into translatable segments and check that numbers survive translation."""

import re

MAX_SEGMENT_CHARS = 600  # keeps every segment far below the model's 512-token input limit

# German abbreviations that end in a dot without ending the sentence (compared lowercase, without dots).
_ABBREVIATIONS = {
    "z", "b", "d", "h", "u", "a", "bzw", "ca", "nr", "abs", "art", "inkl", "ggf", "gem", "vgl", "evtl", "usw",
    "str", "tel", "sog", "max", "min", "mio", "mrd", "dr", "prof", "zzgl", "etc", "ff", "o", "ä", "i", "v", "e",
}
_ITEM_START = re.compile(r"^(?:[•▪●\-–*]\s|\(?[a-z0-9]{1,3}[.)]\s)")
_SENTENCE_GAP = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9„\"(•])")


def _ends_sentence(piece: str) -> bool:
    last = piece.split()[-1].rstrip(".").lower()
    return not (last in _ABBREVIATIONS or (last.isdigit() and len(last) <= 2))  # "12. Mai" continues; "2026." ends


def _split_sentences(text: str) -> list[str]:
    pieces = _SENTENCE_GAP.split(text)
    out: list[str] = []
    for piece in pieces:
        if out and not _ends_sentence(out[-1]):
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out


def _cap(segment: str) -> list[str]:
    """Break an over-long segment at ';' first, then at spaces."""
    if len(segment) <= MAX_SEGMENT_CHARS:
        return [segment]
    out: list[str] = []
    for part in re.split(r"(?<=;)\s+", segment):
        while len(part) > MAX_SEGMENT_CHARS:
            cut = part.rfind(" ", 0, MAX_SEGMENT_CHARS)
            cut = cut if cut > 0 else MAX_SEGMENT_CHARS
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            out.append(part)
    return out


def _is_heading(line: str, next_line: str | None) -> bool:
    # ponytail: short unpunctuated line followed by a capitalised/numbered line; misses wrapped headings.
    return (
        len(line.split()) <= 8
        and line[-1] not in ".,;:!?"
        and (line[0].isupper() or line[0].isdigit())
        and (next_line is None or not next_line[:1].islower())
    )


def segment_page(text: str) -> list[str]:
    """Sentences and headings of one page, in reading order. The page's physical page number is the caller's."""
    text = re.sub(r"(?<=[A-Za-zÄÖÜäöüß])-\n(?=[a-zäöüß])", "", text)  # undo line-break hyphenation
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            for sentence in _split_sentences(" ".join(buf)):
                out.extend(_cap(sentence))
            buf.clear()

    for i, line in enumerate(lines):
        if not line:
            flush()
            continue
        nxt = next((ln for ln in lines[i + 1:] if ln), None)
        if buf and _ITEM_START.match(line):
            flush()
        if not buf and _is_heading(line, nxt):
            out.append(line)
            continue
        buf.append(line)
        if line[-1] in ".!?:;" and _ends_sentence(line):
            flush()
    flush()
    return out


_NUMBER = re.compile(r"\d[\d.,'’]*\d|\d")
_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b")
_MONTHS = (
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec"
).split()


def _digits(token: str) -> str:
    return re.sub(r"\D", "", token).lstrip("0")  # "1.000,00" and "1,000.00" both become "100000"


def number_flags(src: str, en: str) -> list[str]:
    """Every number, amount and date in `src` must be in `en`. Returns one flag per missing token."""
    en_digits = {_digits(t) for t in _NUMBER.findall(en)}
    en_lower = en.lower()
    flags = []
    for day, month, year in _DATE.findall(src):
        has_month = _digits(month) in en_digits or any(re.search(rf"\b{m}", en_lower) for m in _MONTHS)
        if not (_digits(day) in en_digits and _digits(year) in en_digits and has_month):
            flags.append(f"number_mismatch:{day}.{month}.{year}")
    for token in _NUMBER.findall(_DATE.sub(" ", src)):
        d = _digits(token)
        if d and d not in en_digits:
            flags.append(f"number_mismatch:{token}")
    return flags
