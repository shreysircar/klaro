"""Issuer fallback: most-named organization in pass A overview facts, with pages. No hardcoded names."""

import unittest

from backend.llm.executive_summary.aggregator import find_issuing_organization, org_key


def facts(*pairs):
    return [{"text": t, "page": p} for t, p in pairs]


class TestIssuingOrganization(unittest.TestCase):
    def test_most_named_org_with_pages(self):
        name, pages = find_issuing_organization(facts(
            ("The RFP is for the Selection of a Technical Service Provider (TSP) for India Post Payments Bank Limited.", 1),
            ("India Post Payments Bank Ltd. proposes to avail services from one eligible vendor.", 7),
            ("The RFP documents are issued by the Assistant General Manager of India Post Payments Bank.", 32),
            ("The document is a Performance Bank Guarantee format issued by India Post Payments Bank (IPPB).", 44),
            ("The issuing organization is India Post Payments Bank Limited (also referred to as BUYER).", 54),
            ("Bidders must hold ASP certification from the National Payments Corporation of India.", 8),
        ))
        self.assertEqual(org_key(name), "india post payments bank")
        self.assertEqual(name, "India Post Payments Bank Limited")
        self.assertEqual(pages, [1, 7, 32, 44, 54])

    def test_other_shapes(self):
        self.assertEqual(find_issuing_organization(facts(
            ("The Riverside Municipal Water Authority (RMWA) invites sealed proposals.", 1)))[0],
            "Riverside Municipal Water Authority")
        self.assertEqual(find_issuing_organization(facts(
            ("Empanelment RFP issued by National Informatics Centre Services Inc. for ICT services.", 9)))[0],
            "National Informatics Centre Services Inc.")
        self.assertEqual(find_issuing_organization(facts(
            ("Tender floated by the Ministry of Finance, Government of India.", 3)))[0], "Ministry of Finance")

    def test_nothing_found(self):
        self.assertEqual(find_issuing_organization(facts(("Bids are due on 30 October.", 4))), ("Not identified", []))
        self.assertEqual(find_issuing_organization([]), ("Not identified", []))


if __name__ == "__main__":
    unittest.main()
