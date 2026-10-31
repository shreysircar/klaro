"""Tests for German->English support: detection, segmentation, number check, translate cache, evidence.
The German text and PDFs below are test fixtures, not demo documents. No model is loaded."""

import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from backend.translation import detect, evidence, segments, translator

DE = (
    "Die Vergabestelle schreibt die Lieferung und den Betrieb eines Systems aus. Das Angebot muss bis zum "
    "12.03.2026 eingereicht werden und alle Unterlagen sind vollständig mit dem Angebot abzugeben. Der Auftrag "
    "hat ein Volumen von 1.000,00 EUR und die Laufzeit beträgt mindestens 24 Monate. Bieter müssen nachweisen, "
    "dass sie über ausreichende Erfahrung verfügen und nicht von der Vergabe ausgeschlossen sind."
)
EN = (
    "The contracting authority is tendering the supply and operation of a system. The bid must be submitted by "
    "12 March 2026 and all documents shall be included with the bid. The contract has a value of EUR 1,000.00 "
    "and the term is at least 24 months. Bidders must demonstrate that they have sufficient experience and are "
    "not excluded from the award."
)


def make_pdf(pages: list[str], path: Path) -> None:
    """Minimal text PDF (Helvetica, text wrapped at 80 characters) for tests; not a real RFP."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", ""]
    kids = []
    for i, text in enumerate(pages):
        page_id, content_id = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{page_id} 0 R")
        esc = lambda t: t.encode("cp1252").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines = " T* ".join(f"({esc(line)}) Tj" for line in textwrap.wrap(text, 80))  # wrapped like a real page
        stream = f"BT /F1 10 Tf 40 780 Td 12 TL {lines} ET"
        objs += [
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content_id} 0 R "
            "/Resources << /Font << /F1 3 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        ]
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    objs.insert(2, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


class TestDetect(unittest.TestCase):
    def test_german(self):
        r = detect.detect_language(DE)
        self.assertEqual(r["language"], "de")
        self.assertGreater(r["confidence"], 0.9)

    def test_english(self):
        self.assertEqual(detect.detect_language(EN)["language"], "en")

    def test_unknown_on_short_text(self):
        self.assertEqual(detect.detect_language("Seite 1")["language"], "unknown")

    def test_unknown_on_other_language(self):
        fr = "Le fournisseur doit présenter une offre complète avant la date limite fixée dans le présent document " * 3
        self.assertEqual(detect.detect_language(fr)["language"], "unknown")

    def test_pdf_roundtrip(self):
        from backend.documents.pdf_extractor import extract_pdf_pages

        with tempfile.TemporaryDirectory() as d:
            make_pdf([DE[:300], DE[300:]], Path(d) / "x.pdf")
            self.assertEqual(detect.detect_pages(extract_pdf_pages(str(Path(d) / "x.pdf")))["language"], "de")


class TestSegments(unittest.TestCase):
    def test_sentences_and_abbreviations(self):
        out = segments.segment_page("Das gilt z. B. für Bieter.\nDie Frist endet am 12. Mai 2026. Danach nicht mehr.")
        self.assertEqual(out, ["Das gilt z. B. für Bieter.", "Die Frist endet am 12. Mai 2026.", "Danach nicht mehr."])

    def test_hyphenation_heading_and_cap(self):
        out = segments.segment_page("3. Leistungsumfang\nDie Ver-\nwaltung prüft alle Angebote.")
        self.assertEqual(out, ["3. Leistungsumfang", "Die Verwaltung prüft alle Angebote."])
        self.assertTrue(all(len(s) <= segments.MAX_SEGMENT_CHARS for s in segments.segment_page("wort " * 400)))

    def test_number_flags(self):
        f = segments.number_flags
        self.assertEqual(f("Betrag 1.000,00 EUR", "Amount EUR 1,000.00"), [])
        self.assertEqual(f("Frist 12.03.2026", "Deadline: 12 March 2026"), [])
        self.assertEqual(f("Frist 12.03.2026", "Deadline: 12/03/2026"), [])
        self.assertEqual(f("Betrag 1.000,00 EUR", "Amount EUR 100"), ["number_mismatch:1.000,00"])
        self.assertEqual(f("Frist 12.03.2026", "Deadline: 13 March 2026"), ["number_mismatch:12.03.2026"])
        self.assertEqual(f("24 Monate, 5 Jahre", "24 months"), ["number_mismatch:5"])


class TestTranslatePages(unittest.TestCase):
    def test_cache_pages_and_flags(self):
        pages = [{"page": 3, "text": "Das Angebot kostet 1.000,00 EUR.\nEs gilt 24 Monate."}, {"page": 4, "text": ""}]
        calls = []

        def fake(texts, src, tgt):
            calls.extend(texts)
            return [t.replace("Das Angebot kostet", "The bid costs").replace("Es gilt 24", "Valid 25") for t in texts]

        with tempfile.TemporaryDirectory() as d, mock.patch.object(translator, "DATA_DIR", Path(d)), \
                mock.patch.object(translator, "_translate_batch", fake):
            segs, en = translator.translate_pages(pages, "de", "en")
            self.assertEqual([s["id"] for s in segs], ["p3-1", "p3-2"])
            self.assertEqual([s["page"] for s in segs], [3, 3])
            self.assertEqual(segs[0]["flags"], [])
            self.assertEqual(segs[1]["flags"], ["number_mismatch:24"])
            self.assertEqual([p["page"] for p in en], [3, 4])
            n = len(calls)
            translator.translate_pages(pages, "de", "en")
            self.assertEqual(len(calls), n, "second run must come from the cache")


class TestEvidence(unittest.TestCase):
    SEGS = [
        {"id": "p2-1", "page": 2, "src": "Allgemeines zur Ausschreibung.", "en": "General notes on the tender."},
        {"id": "p2-2", "page": 2, "src": "Das Angebot muss bis zum 12.03.2026 eingereicht werden.",
         "en": "The bid must be submitted by 12 March 2026."},
        {"id": "p5-1", "page": 5, "src": "Etwas anderes.", "en": "Something else entirely."},
    ]

    def test_cover_and_threshold(self):
        score, win = evidence.cover("Bid must be submitted by 12 March 2026", self.SEGS[:2])
        self.assertGreaterEqual(score, 0.9)
        self.assertEqual([s["id"] for s in win], ["p2-2"])
        score, _ = evidence.cover("Unrelated warranty penalty clauses apply", self.SEGS[:2])
        self.assertLess(score, evidence.MATCH_THRESHOLD)

    def test_cover_spans_segments_and_pages(self):
        segs = self.SEGS + [{"id": "p5-2", "page": 5, "src": "Die Gewährleistung beträgt zwei Jahre.",
                             "en": "The warranty period is two years."}]
        score, picked = evidence.cover("Bid submitted by 12 March 2026 and warranty period two years", segs)
        self.assertEqual([s["id"] for s in picked], ["p2-2", "p5-2"])
        self.assertGreaterEqual(score, evidence.MATCH_THRESHOLD)

    def test_build_evidence_german_and_english(self):
        summary = {
            "overview": {"text": "x", "pages": [2]},
            "important_dates": [
                {"text": "The bid must be submitted by 12 March 2026", "pages": [2, 5]},
                {"text": "Warranty penalty clauses apply to every supplier", "pages": [5]},
            ],
        }
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            (run / "summary").mkdir()
            (run / "summary" / "executive_summary.json").write_text(json.dumps(summary), encoding="utf-8")
            evidence.build_evidence(run, "de", self.SEGS, [])
            items = {i["id"]: i for i in json.loads((run / "evidence.json").read_text(encoding="utf-8"))["items"]}
            hit = items["important_dates-0"]
            self.assertEqual((hit["page"], hit["segment_ids"]), (2, ["p2-2"]))
            self.assertEqual([p["page"] for p in hit["passages"]], [2])
            self.assertIn("12.03.2026", hit["quote_src"])
            miss = items["important_dates-1"]
            self.assertIsNone(miss["quote_src"])
            self.assertEqual(miss["page"], 5)
            self.assertEqual(items["overview-0"]["quote_src"], None)  # "x" is too short to match anything

            evidence.build_evidence(run, "en", None, [{"page": 2, "text": "The bid must be submitted by 12 March 2026."}])
            en = {i["id"]: i for i in json.loads((run / "evidence.json").read_text(encoding="utf-8"))["items"]}
            self.assertEqual(en["important_dates-0"]["quote_src"], en["important_dates-0"]["quote_en"])


class TestIssuerFallback(unittest.TestCase):
    def test_page_text_names_the_issuer_when_overview_does_not(self):
        from backend.llm.executive_summary.aggregator import find_issuing_organization

        pages = [{"text": "General Terms of the Procurement Office of the BMI apply.", "page": 31},
                 {"text": "Offers go to the Procurement Office in Bonn.", "page": 4}]
        self.assertEqual(find_issuing_organization(pages), ("Procurement Office", [4, 31]))
        self.assertEqual(find_issuing_organization([{"text": "nothing here", "page": 1}]), ("Not identified", []))


if __name__ == "__main__":
    unittest.main()
