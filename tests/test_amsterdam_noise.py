import unittest

from examples.amsterdam_noise import run_example


class AmsterdamNoiseTest(unittest.TestCase):
    def test_type_valid_workflows_disagree_when_the_threshold_is_omitted(self):
        report = run_example()
        self.assertEqual(report["threshold_db"], 70)
        self.assertEqual(
            {zone["id"]: zone["above_threshold_pixels"] for zone in report["reference"]},
            {"west": 425, "central": 0, "south": 611},
        )

        correct = report["results"]["thresholded"]
        unfiltered = report["results"]["unfiltered"]
        self.assertTrue(correct["comparison"]["passed"])
        self.assertEqual(correct["comparison"]["max_absolute_error"], 0)
        self.assertEqual(
            correct["trace"]["output"]["type"], unfiltered["trace"]["output"]["type"],
        )
        self.assertFalse(unfiltered["comparison"]["passed"])
        self.assertEqual(unfiltered["shares"], {"west": 1.0, "central": 1.0, "south": 1.0})
        self.assertEqual(len(unfiltered["comparison"]["mismatches"]), 3)


if __name__ == "__main__":
    unittest.main()
