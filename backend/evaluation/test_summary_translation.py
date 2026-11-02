"""Tests for the on-demand German view: sentence splitting, id/order preservation, fidelity flags, atomic output.
A stub replaces the translation model, so no model is loaded."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.translation import evidence, translate_summary as ts

SUMMARY = {
    "overview": {"text": "A framework agreement for portals. Bids are due 12 December 2026.", "pages": [1]},
    "issuing_organization": "Federal Ministry of Education",
    "issuing_organization_pages": [1],
    "scope": [
        {"text": "Operate the portal e.g. for audits. No. 5 applies.", "pages": [3, 4]},
        {"text": "   ", "pages": [3]},
        {"text": "Apps are tested within 10 working days.", "pages": [18]},
    ],
    "key_requirements": [],
    "eligibility": ["Legacy string bullet."],
    "important_dates": [{"text": "Submission deadline: 12.12.2026", "pages": [2]}],
    "commercial_requirements": [{"text": "Bid security of INR 1,000.00 is required.", "pages": [9]}],
    "project_duration": [],
    "important_conditions": [{"text": "Not specified", "pages": []}],
}


def stub(texts, on_progress=None):
    out = {t: "DE " + t for t in texts}
    if on_progress:
        on_progress(len(out), len(out))
    return out


class SplitSentences(unittest.TestCase):
    def test_abbreviations_do_not_end_a_sentence(self):
        text = "The bidder shall submit e.g. a guarantee. No. 5 applies. Payment is due. 12 items are required."
        self.assertEqual(ts.split_sentences(text), [
            "The bidder shall submit e.g. a guarantee.", "No. 5 applies.", "Payment is due.", "12 items are required."])

    def test_long_sentence_is_capped(self):
        parts = ts.split_sentences("word " * 400)
        self.assertTrue(all(len(p) <= 600 for p in parts) and len(parts) > 1)


class Structure(unittest.TestCase):
    def test_ids_match_evidence_ids(self):
        mine = [i for i, _, _ in ts.slots(SUMMARY)]
        theirs = [i for i, *_ in evidence._items(SUMMARY)]
        self.assertEqual([i for i in mine if not i.startswith("overview")], [i for i in theirs if not i.startswith("overview")])

    def test_keys_order_pages_and_issuer_survive(self):
        german, _ = ts.translate_summary_data(SUMMARY, stub)
        self.assertEqual(list(german), list(SUMMARY))
        self.assertEqual(german["issuing_organization"], SUMMARY["issuing_organization"])
        self.assertEqual([e["pages"] for e in german["scope"]], [e["pages"] for e in SUMMARY["scope"]])
        self.assertEqual(len(german["scope"]), 3)
        self.assertEqual(german["scope"][1]["text"], "   ")  # empty bullets are left alone
        self.assertEqual(german["eligibility"], ["DE Legacy string bullet."])
        self.assertTrue(german["scope"][0]["text"].startswith("DE Operate the portal e.g. for audits."))
        self.assertEqual(SUMMARY["overview"]["text"][:1], "A")  # input not mutated

    def test_count_segments_is_unique_sentences(self):
        self.assertEqual(ts.count_segments(SUMMARY), 9)


class Fidelity(unittest.TestCase):
    def test_separator_styles_are_equal(self):
        self.assertEqual(ts.fidelity_flags("Fee of INR 1,000.00", "Gebühr von INR 1.000,00"), [])
        self.assertEqual(ts.fidelity_flags("Due 12 December 2026 at 15:00", "Fällig am 12. Dezember 2026 um 15:00"), [])
        self.assertEqual(ts.fidelity_flags("Due 12.12.2026", "Fällig am 12.12.2026"), [])

    def test_missing_number_and_currency_are_flagged(self):
        self.assertEqual(ts.fidelity_flags("Within 30 days", "Innerhalb von Tagen"), ["number_mismatch:30"])
        self.assertEqual(ts.fidelity_flags("Fee of ₹500", "Gebühr von 500"), ["currency_missing:₹"])

    def test_flags_are_stored_never_fixed(self):
        bad = lambda texts, cb=None: {t: t.replace("30", "") for t in texts}
        german, flagged = ts.translate_summary_data({"scope": [{"text": "Within 30 days", "pages": [1]}]}, bad)
        self.assertEqual(flagged, [{"id": "scope-0", "flags": ["number_mismatch:30"]}])
        self.assertEqual(german["scope"][0]["text"], "Within  days")


class RunOutput(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        (self.run / "summary").mkdir()
        (self.run / "summary" / ts.SUMMARY).write_text(json.dumps(SUMMARY), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_json_html_md_meta_and_leaves_no_staging(self):
        progress = []
        with mock.patch("backend.translation.translator.check", return_value=None), \
             mock.patch("backend.translation.translator.translate_texts", lambda t, s, g, cb=None: stub(t, cb)):
            meta = ts.translate_run(self.run, lambda d, t: progress.append((d, t)))
        names = sorted(p.name for p in (self.run / "summary").iterdir())
        self.assertEqual(names, ["executive_summary.json", "executive_summary_de.html", "executive_summary_de.json",
                                 "executive_summary_de.md", "executive_summary_de.meta.json"])
        html = (self.run / "summary" / "executive_summary_de.html").read_text(encoding="utf-8")
        self.assertIn("Wichtige Termine", html)
        self.assertIn("DE Submission deadline: 12.12.2026", html)
        self.assertEqual(meta["flagged_bullets"], 0)
        self.assertEqual(progress[-1][0], progress[-1][1])

    def test_failure_leaves_no_german_files(self):
        def boom(*_):
            raise RuntimeError("model exploded")
        with mock.patch("backend.translation.translator.check", return_value=None), \
             mock.patch("backend.translation.translator.translate_texts", boom):
            with self.assertRaisesRegex(RuntimeError, "model exploded"):
                ts.translate_run(self.run)
        self.assertEqual([p.name for p in (self.run / "summary").iterdir()], ["executive_summary.json"])

    def test_missing_model_is_a_readable_error(self):
        with mock.patch("backend.translation.translator.check", return_value="The en->de translation model is not installed"):
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                ts.translate_run(self.run)


if __name__ == "__main__":
    unittest.main()


class Api(unittest.TestCase):
    """Routes and the one-job rule, without starting the worker or loading a model."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from backend.api import app as api_app, jobs

        self.jobs = jobs
        self.tmp = tempfile.TemporaryDirectory()
        runs = Path(self.tmp.name).resolve() / "runs"
        (runs / "run_a" / "summary").mkdir(parents=True)
        (runs / "run_a" / "summary" / ts.SUMMARY).write_text(json.dumps(SUMMARY), encoding="utf-8")
        self.patches = [mock.patch.object(jobs, "RUNS_DIR", runs), mock.patch.object(jobs, "start")]
        for p in self.patches:
            p.start()
        self.client = TestClient(api_app.app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.jobs._tjobs.clear()
        self.jobs._jobs.clear()
        self.tmp.cleanup()

    def test_status_before_translation(self):
        r = self.client.get("/runs/run_a/translation").json()
        self.assertEqual((r["status"], r["available"]), ("none", False))
        self.assertEqual(r["segments"], 9)
        self.assertEqual(self.client.get("/runs/nope/translation").status_code, 404)
        self.assertEqual(self.client.get("/runs/run_a/summary?lang=de").status_code, 404)
        self.assertEqual(self.client.get("/runs/run_a/summary?lang=fr").status_code, 400)

    def test_missing_model_blocks_with_the_fix(self):
        with mock.patch("backend.translation.translator.installed", return_value=False):
            r = self.client.post("/runs/run_a/translation")
        self.assertEqual(r.status_code, 503)
        self.assertIn("npm run setup", r.json()["detail"])

    def test_a_running_analysis_blocks_translation(self):
        self.jobs._jobs["run_b"] = {"status": "running"}
        with mock.patch("backend.translation.translator.installed", return_value=True):
            self.assertEqual(self.client.post("/runs/run_a/translation").status_code, 409)

    def test_translation_is_queued_and_cancel_clears_it(self):
        with mock.patch("backend.translation.translator.installed", return_value=True):
            self.assertEqual(self.client.post("/runs/run_a/translation").json()["status"], "queued")
            self.assertTrue(self.client.get("/runs/run_a/translation").json()["busy"] is False)
            self.assertEqual(self.client.delete("/runs/run_a/translation").status_code, 204)
        self.assertEqual(self.client.get("/runs/run_a/translation").json()["status"], "cancelled")
        while not self.jobs._queue.empty():
            self.jobs._queue.get_nowait()
