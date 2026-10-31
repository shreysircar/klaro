"""Stage 3 must fail the run when more than half the chunks fail, and tolerate fewer."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.llm.executive_summary.chunk_analyzer import process_chunks_file
from backend.llm.executive_summary.schema import PassAInformation, PassBInformation


def fake_pass(info_cls, failing_chunks):
    def run(page_text, chunk_id, pages):
        if chunk_id in failing_chunks:
            return info_cls(), 0.0, False, "Ollama timed out"
        return info_cls(), 0.0, True, None
    return run


class TestChunkFailures(unittest.TestCase):
    def run_with(self, failing):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            chunks = [{"chunk_id": i, "pages": [i], "word_count": 1, "text": "x"} for i in range(1, 5)]
            (d / "c.json").write_text(json.dumps(chunks), encoding="utf-8")
            (d / "e.json").write_text(json.dumps([{"page": i, "text": "x"} for i in range(1, 5)]), encoding="utf-8")
            progress = []
            with patch("backend.llm.executive_summary.chunk_analyzer.run_pass_a", fake_pass(PassAInformation, failing)), \
                 patch("backend.llm.executive_summary.chunk_analyzer.run_pass_b", fake_pass(PassBInformation, set())):
                res = process_chunks_file(d / "c.json", d / "out.json", d / "e.json", lambda a, b: progress.append((a, b)))
            return res, progress

    def test_half_failed_is_tolerated(self):
        res, progress = self.run_with({1, 2})
        self.assertEqual(res.total_chunks, 4)
        self.assertEqual(progress, [(0, 4), (1, 4), (2, 4), (3, 4), (4, 4)])

    def test_more_than_half_failed_raises(self):
        with self.assertRaisesRegex(RuntimeError, "3 of 4 chunks.*Ollama timed out"):
            self.run_with({1, 2, 3})


if __name__ == "__main__":
    unittest.main()
