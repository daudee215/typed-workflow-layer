"""The worked example, and the toy arithmetic underneath it."""

import contextlib
import io
import unittest

import demo


class TestToyGeometry(unittest.TestCase):
    def test_intersection_of_disjoint_rectangles_is_zero(self):
        self.assertEqual(
            demo.intersection_area((0, 0, 5, 5), (10, 10, 20, 20)), 0
        )

    def test_touching_rectangles_do_not_overlap(self):
        self.assertEqual(
            demo.intersection_area((0, 0, 10, 10), (10, 0, 20, 10)), 0
        )

    def test_the_worked_example_proportions(self):
        kept = demo.toy_constrain(demo.NOISE_CONTOURS, ">=", 70)
        covered = demo.toy_coverage(kept, demo.DISTRICTS)
        self.assertEqual(covered, {"Centrum": 30, "Zuid": 40, "Noord": 36})
        shares = demo.toy_proportion(covered, demo.DISTRICTS)
        self.assertAlmostEqual(shares["Centrum"], 0.30)
        self.assertAlmostEqual(shares["Zuid"], 0.40)
        self.assertAlmostEqual(shares["Noord"], 0.18)

    def test_the_toy_executor_refuses_what_it_does_not_implement(self):
        with self.assertRaises(NotImplementedError):
            demo.toy_constrain(demo.NOISE_CONTOURS, "<", 70)


class TestTheDemoRuns(unittest.TestCase):
    def test_main_completes_and_reports_the_intended_workflow(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            demo.main()
        output = buffer.getvalue()
        self.assertIn(
            "Proportion(Coverage(Constrain(noise), district))", output
        )
        self.assertIn("in the enumerated set: True", output)
        self.assertIn("round trips through JSON unchanged: True", output)

    def test_the_output_is_plain_ascii(self):
        # The demo output is written material and is held to the same rule as
        # the prose it ships with: hyphens only, no em or en dashes. Dashes are
        # named by code point so that this file stays ASCII itself.
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            demo.main()
        output = buffer.getvalue()
        for code_point in (0x2013, 0x2014):
            self.assertNotIn(chr(code_point), output)
        self.assertEqual(output.encode("ascii", "ignore").decode(), output)


if __name__ == "__main__":
    unittest.main()
