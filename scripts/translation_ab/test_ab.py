"""Pure-logic tests for the harness (no model): python -m unittest discover scripts/translation_ab"""
import unittest

import chrf
import protect


class Protect(unittest.TestCase):
    TEXT = "Bid security of INR 1,000.00 (5%) by 12.12.2026 per GEM/2025/B/6828132, see p. 18 or mail a@b.com; EMD applies in 12 December 2026."

    def test_categories(self):
        cats = dict((t, c) for c, t in protect.tokens(self.TEXT))
        self.assertEqual(cats["INR 1,000.00"], "amount")
        self.assertEqual(cats["5%"], "percent")
        self.assertEqual(cats["12.12.2026"], "date")
        self.assertEqual(cats["GEM/2025/B/6828132"], "reference")
        self.assertEqual(cats["p. 18"], "cite")
        self.assertEqual(cats["a@b.com"], "email")
        self.assertEqual(cats["EMD"], "acronym")
        self.assertNotIn("December", cats)  # month names are translated, only their digits are protected

    def test_mask_roundtrip_every_style(self):
        for style in protect.STYLES:
            masked, originals = protect.mask(self.TEXT, style)
            self.assertNotIn("1,000.00", masked)
            self.assertEqual(protect.unmask(masked, originals, style), self.TEXT)
            self.assertEqual(protect.survived(masked, originals, style), len(originals))

    def test_preserved_ignores_separators(self):
        ok, total = protect.preserved("Fee INR 1,000.00 due 12 December 2026 (EMD)", "Gebühr INR 1.000,00 fällig 12. Dezember 2026 (EMD)")
        self.assertEqual((ok, total), (total, total))
        ok, total = protect.preserved("Fee 30 days EMD", "Gebühr Tage")
        self.assertLess(ok, total)


class Glossary(unittest.TestCase):
    def test_reviewed_terms_are_replaced_after_translation(self):
        masked, back = protect.mask("The performance security is due.", "xtag", {"performance security": "Erfüllungsbürgschaft"}, ("glossary",))
        self.assertEqual(masked, "The <x1> is due.")
        self.assertEqual(protect.unmask("Die <x1> ist fällig.", back, "xtag"), "Die Erfüllungsbürgschaft ist fällig.")


class Chrf(unittest.TestCase):
    def test_identity_and_difference(self):
        self.assertAlmostEqual(chrf.chrf("the bid is due", "the bid is due"), 100.0)
        self.assertLess(chrf.chrf("the bid is late", "the bid is due"), 100.0)
        self.assertEqual(chrf.chrf("", "abc"), 0.0)


if __name__ == "__main__":
    unittest.main()
