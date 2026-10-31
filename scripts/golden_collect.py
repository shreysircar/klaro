"""Phases 1-2 of the golden dataset: fetch PDFs, apply the reject rules, extract with OUR extractor.

Reads data/golden/sources.csv (doc_id, sector, buyer, country, title, source_url, local_path),
writes data/golden/pdfs/, extracted/ and manifest.csv. Rerunnable: existing PDFs are not refetched.

    python -m scripts.golden_collect
"""

import csv
import hashlib
import json
import shutil
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from backend.documents.pdf_extractor import extract_pdf_pages

ROOT = Path("data/golden")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MIN_P1_CHARS, MAX_EMPTY_FRAC, MIN_PAGES, MAX_PAGES = 200, 0.20, 15, 120
FIELDS = ["doc_id", "sector", "buyer", "country", "title", "source_url", "downloaded_at", "pages",
          "sha256", "extracted_chars", "split", "status", "reject_reason"]


def fetch(url: str, out: Path) -> None:
    for attempt in (1, 2):  # retry once
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if not data.startswith(b"%PDF"):
                raise ValueError("response is not a PDF")
            out.write_bytes(data)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


def reject_reason(pages: list[dict]) -> str:
    n = len(pages)
    empty = sum(1 for p in pages if len(p["text"]) < 20)
    if n < MIN_PAGES:
        return f"{n} pages, under {MIN_PAGES}"
    if n > MAX_PAGES:
        return f"{n} pages, over {MAX_PAGES}"
    if len(pages[0]["text"]) < MIN_P1_CHARS:
        return f"page 1 has {len(pages[0]['text'])} chars (scanned?)"
    if empty / n > MAX_EMPTY_FRAC:
        return f"{empty}/{n} pages empty (scanned?)"
    return ""


def main() -> int:
    for d in ("pdfs", "extracted"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    old = {}
    if (ROOT / "manifest.csv").exists():
        with open(ROOT / "manifest.csv", newline="", encoding="utf-8") as f:
            old = {r["doc_id"]: r for r in csv.DictReader(f)}
    with open(ROOT / "sources.csv", newline="", encoding="utf-8") as f:
        sources = list(csv.DictReader(f))

    rows, seen_sha = [], {}
    for s in sources:
        doc_id, pdf = s["doc_id"], ROOT / "pdfs" / f"{s['doc_id']}.pdf"
        prev = old.get(doc_id, {})
        row = {k: s.get(k, "") for k in FIELDS} | {"split": prev.get("split", ""),
                                                   "downloaded_at": prev.get("downloaded_at", "")}
        try:
            if not pdf.exists():
                if s.get("local_path"):
                    shutil.copyfile(Path(s["local_path"]).expanduser(), pdf)
                else:
                    fetch(s["source_url"], pdf)
                row["downloaded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if not row["downloaded_at"]:  # fetched by hand before this script saw it
                mtime = datetime.fromtimestamp(pdf.stat().st_mtime, timezone.utc)
                row["downloaded_at"] = mtime.isoformat(timespec="seconds")
            sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
            pages = extract_pdf_pages(str(pdf))
            reason = reject_reason(pages)
            if not reason and sha in seen_sha:
                reason = f"duplicate of {seen_sha[sha]}"
            seen_sha.setdefault(sha, doc_id)
            row |= {"pages": len(pages), "sha256": sha,
                    "extracted_chars": sum(len(p["text"]) for p in pages)}
            out = ROOT / "extracted" / f"{doc_id}.json"
            if reason:
                out.unlink(missing_ok=True)
            else:
                out.write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            reason = f"fetch/extract failed: {e}"
        row |= {"status": "rejected" if reason else "ok", "reject_reason": reason}
        rows.append(row)
        print(f"{doc_id:32} {row['status']:8} {row['pages'] or '-':>4}p  {reason}", file=sys.stderr)
        time.sleep(1)  # one polite request at a time

    with open(ROOT / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    ok = [r for r in rows if r["status"] == "ok"]
    print(f"\n{len(ok)} ok / {len(rows)} total", file=sys.stderr)
    for sec in sorted({r["sector"] for r in ok}):
        print(f"  {sec:14} {sum(r['sector'] == sec for r in ok)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
