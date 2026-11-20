import csv
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from examples.benchmark_study import compare_orders, evaluate_export, ranking_order, study_definition
from examples.workflow_benchmark import QUESTIONS, run_benchmark


@unittest.skipUnless(
    all(importlib.util.find_spec(name) for name in ("numpy", "rasterio", "shapely")),
    "requires the optional GIS dependencies",
)
class WorkflowBenchmarkTest(unittest.TestCase):
    def test_scorecard_distinguishes_wrong_answers_and_refusals(self):
        report = run_benchmark()
        self.assertEqual(report["summary"], {
            "questions": 10, "candidates": 21, "type_admitted": 19,
            "numeric_candidates": 18, "numeric_answers": 17, "numeric_matches": 9,
            "admitted_wrong_answers": 8, "requested_refusals": 3,
            "correct_refusals": 3, "expected_outcomes": 21,
        })
        rows = {(row["question"], row["candidate"]): row for row in report["candidates"]}
        self.assertTrue(rows["amsterdam-70", "D"]["type_admitted"])
        self.assertEqual(rows["amsterdam-70", "D"]["outcome"], "wrong")
        self.assertEqual(rows["region-as-points", "A"]["outcome"], "type_refusal")
        self.assertIn("whole-zone share is undefined", rows["missing-valid-area", "A"]["diagnostic"])


class BenchmarkStudyTest(unittest.TestCase):
    def test_packet_matches_frozen_tasks_and_preserves_model_ties(self):
        tasks, model = study_definition()
        self.assertEqual(tasks, json.loads(QUESTIONS.with_name("study_tasks.json").read_bytes()))
        self.assertEqual(model["amsterdam-70"]["A"], model["amsterdam-70"]["D"])
        self.assertNotIn("model_ranks", json.dumps(tasks))
        with self.assertRaisesRegex(ValueError, "exactly once"):
            ranking_order('[["A", "A"], ["B"]]', "AB")

    def test_tie_aware_agreement_and_reversed_preferences(self):
        tied = compare_orders({"A": 0, "B": 0, "C": 1}, {"A": 0, "B": 1, "C": 2})
        self.assertAlmostEqual(tied["tau_b"], 2 / (6 ** 0.5))
        self.assertEqual(tied["tied_first_only"], 1)
        reversed_pair = compare_orders({"A": 0, "B": 1}, {"A": 1, "B": 0})
        self.assertEqual(reversed_pair["tau_b"], -1)
        self.assertEqual(reversed_pair["disagreements"], [{"first_prefers": "A", "second_prefers": "B"}])
        self.assertIsNone(compare_orders({"A": 0, "B": 0}, {"A": 0, "B": 1})["tau_b"])

    def test_export_groups_complete_ballots_and_omits_participant_codes(self):
        tasks, model = study_definition()
        with TemporaryDirectory() as root:
            directory = Path(root)
            (directory / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
            with (directory / "responses.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["participant", "task_id", "answer"])
                for task in model:
                    writer.writerow(["one_private_id", task, '[["A"], ["B", "C"], ["D"]]'])
                    writer.writerow(["two_private_id", task, '[["D"], ["B", "C"], ["A"]]'])
                writer.writerow(["incomplete_private_id", next(iter(model)), '[["A", "B", "C", "D"]]'])
            report = evaluate_export(directory)
        self.assertEqual(report["complete_ballots"], 2)
        self.assertEqual(report["incomplete_ballots"], 1)
        self.assertNotIn("_private_id", json.dumps(report))
        self.assertEqual(len(report["tasks"]["amsterdam-70"]["analyst_pairs"]), 1)


if __name__ == "__main__":
    unittest.main()
