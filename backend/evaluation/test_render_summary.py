"""
Unit tests for Executive Summary Renderer (render_summary.py)
"""

import json
import unittest
import tempfile
from pathlib import Path
from backend.llm.executive_summary.render_summary import (
    render_markdown,
    render_html,
    render_summary_files,
    SECTION_TITLES,
)


class TestRenderSummary(unittest.TestCase):

    def setUp(self):
        self.sample_summary_full = {
            "overview": {
                "text": "Empanelment RFP for Application Software and Website Development.",
                "pages": [9, 30]
            },
            "issuing_organization": "National Informatics Centre Services Inc. (NICSI)",
            "scope": [
                {"text": "Design, Development, Implementation and Maintenance of Application Software.", "pages": [30, 34]}
            ],
            "key_requirements": [
                {"text": "Bidder must submit Bid Securing Declaration.", "pages": 84}
            ],
            "eligibility": [
                {"text": "Bidder must possess valid CMMI Level-3 or Level-5 certification.", "pages": [83]}
            ],
            "important_dates": [
                {"text": "Bids valid for 120 days from submission deadline.", "pages": [31]}
            ],
            "commercial_requirements": [
                {"text": "Billing on Time & Material basis.", "pages": [45]}
            ],
            "project_duration": [],
            "important_conditions": [
                {"text": "Confidentiality obligations apply.", "pages": [56]}
            ]
        }

    def test_render_markdown_full(self):
        md = render_markdown(self.sample_summary_full)

        # Check all section headers exist
        for _, title in SECTION_TITLES:
            self.assertIn(f"## {title}", md)

        # Check content & page formatting
        self.assertIn("Empanelment RFP for Application Software", md)
        self.assertIn("*(Pages 9, 30)*", md)
        self.assertIn("National Informatics Centre Services Inc. (NICSI)", md)
        self.assertIn("- Design, Development, Implementation and Maintenance of Application Software. *(Pages 30, 34)*", md)
        self.assertIn("- Bidder must submit Bid Securing Declaration. *(Page 84)*", md)
        self.assertIn("## Project Duration\n\n_No information available._", md)

    def test_render_html_full(self):
        html_out = render_html(self.sample_summary_full)

        # Check HTML tags and escaping
        self.assertIn("<!DOCTYPE html>", html_out)
        self.assertIn("<h1>Executive Summary</h1>", html_out)
        for _, title in SECTION_TITLES:
            self.assertIn(f"<h2>{title}</h2>", html_out)

        # Check page tags
        self.assertIn('<span class="page-tag">Pages 9, 30</span>', html_out)
        self.assertIn('<span class="page-tag">Page 84</span>', html_out)

        # Check empty section handling
        self.assertIn('<p class="empty-notice"><em>No information available.</em></p>', html_out)

    def test_empty_fields(self):
        empty_summary = {
            "overview": "",
            "issuing_organization": "",
            "scope": [],
            "key_requirements": [],
            "eligibility": [],
            "important_dates": [],
            "commercial_requirements": [],
            "project_duration": [],
            "important_conditions": []
        }
        md = render_markdown(empty_summary)
        html_out = render_html(empty_summary)

        for _, title in SECTION_TITLES:
            self.assertIn(f"## {title}", md)

        self.assertEqual(md.count("_No information available._"), 9)
        self.assertEqual(html_out.count("<em>No information available.</em>"), 9)

    def test_string_valued_facts(self):
        string_summary = {
            "overview": "Overview as plain string text.",
            "issuing_organization": "NICSI",
            "scope": ["Scope item 1 as string", "Scope item 2 as string"],
            "key_requirements": [],
            "eligibility": [],
            "important_dates": [],
            "commercial_requirements": [],
            "project_duration": "12 Months",
            "important_conditions": []
        }
        md = render_markdown(string_summary)
        html_out = render_html(string_summary)

        self.assertIn("Overview as plain string text.", md)
        self.assertIn("- Scope item 1 as string", md)
        self.assertIn("- Scope item 2 as string", md)
        self.assertIn("12 Months", md)
        self.assertIn("<p>12 Months</p>", html_out)

    def test_special_html_character_escaping(self):
        special_summary = {
            "overview": "Testing <script>alert('xss')</script> & \"quotes\" in overview.",
            "issuing_organization": "Company & Co <Inc>",
            "scope": [
                {"text": "Requirement where A > B & C < D.", "pages": [10]}
            ],
            "key_requirements": [],
            "eligibility": [],
            "important_dates": [],
            "commercial_requirements": [],
            "project_duration": [],
            "important_conditions": []
        }
        html_out = render_html(special_summary)

        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)
        self.assertIn("Company &amp; Co &lt;Inc&gt;", html_out)
        self.assertIn("A &gt; B &amp; C &lt; D.", html_out)

    def test_file_generation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            json_file = tmp_path / "test_summary.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(self.sample_summary_full, f)

            out_md, out_html = render_summary_files(json_file, tmp_path)

            self.assertTrue(out_md.exists())
            self.assertTrue(out_html.exists())
            self.assertEqual(out_md.name, "test_summary.md")
            self.assertEqual(out_html.name, "test_summary.html")

            md_text = out_md.read_text(encoding="utf-8")
            self.assertIn("Empanelment RFP for Application Software", md_text)


if __name__ == "__main__":
    unittest.main()
