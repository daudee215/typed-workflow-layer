"""Reference comparisons that separate execution from correctness."""

import unittest

from evaluation import compare


class TestEvaluation(unittest.TestCase):
    def test_exact_reference_passes(self):
        report = compare({"A": 0.3, "B": 0.4}, {"A": 0.3, "B": 0.4})
        self.assertTrue(report.passed)
        self.assertEqual(report.compared, 2)

    def test_small_numeric_noise_can_be_tolerated(self):
        report = compare({"A": 0.3}, {"A": 0.3000000001})
        self.assertTrue(report.passed)
        self.assertGreater(report.max_absolute_error, 0.0)

    def test_missing_and_wrong_values_are_reported(self):
        report = compare({"A": 0.3, "B": 0.4}, {"A": 0.5, "C": 0.4})
        self.assertFalse(report.passed)
        self.assertEqual(
            {item.path for item in report.mismatches}, {"'A'", "'B'", "'C'"}
        )

    def test_negative_tolerance_is_refused(self):
        with self.assertRaises(ValueError):
            compare(1, 1, absolute_tolerance=-1)


if __name__ == "__main__":
    unittest.main()
