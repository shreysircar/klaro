"""Print a doc's extracted pages with the same --- [PAGE n] --- markers the app uses.

    python -m scripts.golden_pages <doc_id> 12-18
    python -m scripts.golden_pages <doc_id> 7
"""

import sys

from scripts.golden_lib import load_pages

doc_id, rng = sys.argv[1], sys.argv[2]
lo, _, hi = rng.partition("-")
pages = load_pages(doc_id)
for p in range(int(lo), int(hi or lo) + 1):
    if p in pages:
        print(f"--- [PAGE {p}] ---\n{pages[p]}\n")
