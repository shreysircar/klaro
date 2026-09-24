"""
Unit and Integration tests for Workflow Orchestrator (backend/workflow/run_rfp.py)
"""

import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.workflow.run_rfp import run_pipeline, calculate_file_hash


class TestWorkflowOrchestrator(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Create dummy PDF file
        self.dummy_pdf = self.temp_path / "sample_test.pdf"
        self.dummy_pdf.write_bytes(b"%PDF-1.4 Dummy PDF Content for Testing")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_invalid_input_path(self):
        non_existent = self.temp_path / "non_existent.pdf"
        res = run_pipeline(non_existent, output_dir=self.temp_path)
        self.assertEqual(res, 1)

    def test_non_pdf_input(self):
        txt_file = self.temp_path / "sample.txt"
        txt_file.write_text("Not a pdf")
        res = run_pipeline(txt_file, output_dir=self.temp_path)
        self.assertEqual(res, 1)

    def test_file_hash_calculation(self):
        file_hash = calculate_file_hash(self.dummy_pdf)
        self.assertIsInstance(file_hash, str)
        self.assertEqual(len(file_hash), 64)  # SHA-256 length

    @patch("backend.workflow.run_rfp.render_summary_files")
    @patch("backend.workflow.run_rfp.run_evaluation")
    @patch("backend.workflow.run_rfp.run_executive_summary_agent")
    @patch("backend.workflow.run_rfp.aggregate_document")
    @patch("backend.workflow.run_rfp.process_chunks_file")
    @patch("backend.workflow.run_rfp.create_chunks")
    @patch("backend.workflow.run_rfp.extract_pdf_pages")
    def test_orchestration_mocked_pipeline(
        self,
        mock_extract_pdf,
        mock_create_chunks,
        mock_process_chunks,
        mock_aggregate,
        mock_summary_agent,
        mock_evaluate,
        mock_render,
    ):
        # Setup mocks
        mock_extract_pdf.return_value = [{"page": 1, "text": "Sample RFP Text"}]
        mock_create_chunks.return_value = [{"chunk_id": 1, "section": "Start", "pages": [1], "word_count": 3, "text": "Sample RFP Text"}]

        mock_doc_analysis = MagicMock()
        mock_doc_analysis.total_chunks = 1
        mock_process_chunks.return_value = mock_doc_analysis

        mock_aggregate.return_value = {"overview": []}
        
        mock_agent_out = MagicMock()
        mock_agent_out.model_dump_json.return_value = "{}"
        mock_summary_agent.return_value = mock_agent_out

        mock_evaluate.return_value = {
            "structural_validity": {"passed": True},
            "grounding": {"grounding_percentage": 100.0},
            "traceability": {"traceability_percentage": 100.0},
            "coverage": {"coverage_percentage": 100.0},
        }

        mock_render.return_value = (
            self.temp_path / "executive_summary.md",
            self.temp_path / "executive_summary.html"
        )

        res = run_pipeline(self.dummy_pdf, output_dir=self.temp_path, run_id="test_run_001")
        self.assertEqual(res, 0)

        run_dir = self.temp_path / "test_run_001"
        self.assertTrue(run_dir.exists())
        self.assertTrue((run_dir / "input" / "sample_test.pdf").exists())
        self.assertTrue((run_dir / "extracted" / "sample_test.json").exists())
        self.assertTrue((run_dir / "chunks" / "sample_test.json").exists())
        self.assertTrue((run_dir / "run_metadata.json").exists())

        metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["run_id"], "test_run_001")
        self.assertEqual(metadata["status"], "completed")
        self.assertIn("pdf_extraction", metadata["stages"])
        self.assertIn("chunking", metadata["stages"])
        self.assertIn("chunk_analysis", metadata["stages"])
        self.assertIn("aggregation", metadata["stages"])
        self.assertIn("summary_agent", metadata["stages"])
        self.assertIn("evaluation", metadata["stages"])
        self.assertIn("rendering", metadata["stages"])


if __name__ == "__main__":
    unittest.main()
