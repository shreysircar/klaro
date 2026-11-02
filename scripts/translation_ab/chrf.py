"""chrF (character n-gram F-score, beta 2, n = 1..6, spaces ignored), 0-100. Own implementation: no new dependency."""

from collections import Counter


def _grams(text: str, n: int) -> Counter:
    s = "".join(text.split())
    return Counter(s[i:i + n] for i in range(len(s) - n + 1))


def chrf(hyp: str, ref: str, max_n: int = 6, beta: float = 2.0) -> float:
    precisions, recalls = [], []
    for n in range(1, max_n + 1):
        h, r = _grams(hyp, n), _grams(ref, n)
        if not h or not r:
            continue
        match = sum((h & r).values())
        precisions.append(match / sum(h.values()))
        recalls.append(match / sum(r.values()))
    if not precisions:
        return 0.0
    p, r = sum(precisions) / len(precisions), sum(recalls) / len(recalls)
    return 0.0 if p + r == 0 else 100 * (1 + beta**2) * p * r / (beta**2 * p + r)
