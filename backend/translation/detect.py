"""Offline language detection for RFP text: German vs English by stopword ratio. No dependencies.

    python -m backend.translation.detect some.pdf   ->   {"language":"de","confidence":0.97}
"""

import json
import re
import sys

# Function words that are common in one language and (almost) absent in the other.
# Words that exist in both ("in", "an", "was", "man", "also", "will") are left out on purpose.
_DE = set(
    "der die das und ist nicht mit für von den dem des ein eine einer eines einen auf im zu auch als bei "
    "nach oder werden wird sind wurde sich aus über durch zum zur dass diese dieser sowie gemäß mindestens "
    "bzw aber wenn noch nur kann können müssen sein ihre ihr unter vom".split()
)
_EN = set(
    "the and of to is that for with on be are by this or from it not shall must which have has any all may "
    "their its such other than these".split()
)
MIN_WORDS = 30  # below this there is too little text to decide
MIN_RATE = 0.08  # stopwords are about a quarter of ordinary prose; far below that it is another language
MIN_CONFIDENCE = 0.6


def detect_language(text: str) -> dict:
    words = re.findall(r"[a-zäöüß]+", text[:200_000].lower())
    if len(words) < MIN_WORDS:
        return {"language": "unknown", "confidence": 0.0}
    de = sum(w in _DE for w in words)
    en = sum(w in _EN for w in words)
    if max(de, en) / len(words) < MIN_RATE:
        return {"language": "unknown", "confidence": 0.0}
    lang, hits = ("de", de) if de > en else ("en", en)
    confidence = round(hits / (de + en), 2)
    if confidence < MIN_CONFIDENCE:
        return {"language": "unknown", "confidence": confidence}
    return {"language": lang, "confidence": confidence}


def detect_pages(pages: list[dict]) -> dict:
    return detect_language("\n".join(p["text"] for p in pages))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m backend.translation.detect <pdf>")
    from backend.documents.pdf_extractor import extract_pdf_pages

    print(json.dumps(detect_pages(extract_pdf_pages(sys.argv[1]))))
