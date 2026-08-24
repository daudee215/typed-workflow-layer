"""Ordering, explanation, and the evaluation of the ordering itself.

The agreement tests matter more than the ranking tests. A ranking that cannot
be checked against a human ordering is an opinion with arithmetic attached, and
these are what make it falsifiable.
"""

import unittest

import ccd
import ranking
import request as request_parser
from ccd import CCDType
from cost import CostModel, SourceProfile, Weights
from synthesis import Dataset, build_chain, enumerate_workflows

NOISE = Dataset("noise", CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT))
DISTRICT = Dataset("district", CCDType(ccd.OBJECT, ccd.NOMINAL, ccd.REGION_SUPPORT))
SOURCES = (NOISE, DISTRICT)
QUESTION = "proportion of area where noise >= 70 dB for each district"


def constrained_workflows(depth=4):
    query = request_parser.parse(QUESTION)
    return enumerate_workflows(
        SOURCES,
        query.target,
        max_depth=depth,
        must_use=query.required_transformations(),
    )


class TestRank(unittest.TestCase):
    def test_the_twenty_four_are_ordered(self):
        workflows = constrained_workflows()
        self.assertEqual(len(workflows), 24)
        scored = ranking.rank(workflows)
        self.assertEqual(len(scored), 24)
        totals = [item.total for item in scored]
        self.assertEqual(totals, sorted(totals))

    def test_ordering_is_reproducible(self):
        workflows = constrained_workflows()
        first = [item.expression for item in ranking.rank(workflows)]
        second = [item.expression for item in ranking.rank(list(reversed(workflows)))]
        self.assertEqual(first, second)

    def test_ties_share_a_rank_and_the_next_rank_skips(self):
        """Competition ranking. Reporting the workflow after a two-way tie as
        rank 2 would hide that the model failed to separate the first two."""
        scored = ranking.rank(constrained_workflows())
        by_rank = {}
        for item in scored:
            by_rank.setdefault(item.rank, []).append(item)
        for rank_value, items in by_rank.items():
            if len(items) > 1:
                self.assertEqual(len({round(i.total, 6) for i in items}), 1)
                self.assertNotIn(rank_value + 1, by_rank)
                break
        else:
            self.skipTest("no ties in this catalogue, nothing to assert")

    def test_the_winner_delays_the_lossy_step(self):
        """A result about the workflows, not about the code: the cheapest
        workflow should not throw away the interval scale before it has to."""
        scored = ranking.rank(constrained_workflows())
        winner = scored[0].workflow
        first_step = winner.steps[0].transformation
        self.assertNotEqual(first_step, "Constrain")


class TestExplain(unittest.TestCase):
    def test_every_component_appears(self):
        scored = ranking.rank(constrained_workflows())
        text = ranking.explain(scored[0].workflow, scored[-1].workflow)
        for component in Weights().as_dict():
            self.assertIn(component.replace("_", " "), text)

    def test_the_decisive_component_is_named(self):
        scored = ranking.rank(constrained_workflows())
        text = ranking.explain(scored[0].workflow, scored[-1].workflow)
        self.assertIn("wins mainly on", text)

    def test_a_tie_is_reported_as_a_tie(self):
        scored = ranking.rank(constrained_workflows())
        tied = [i for i in scored if i.rank == scored[0].rank]
        if len(tied) < 2:
            self.skipTest("no tie available")
        text = ranking.explain(tied[0].workflow, tied[1].workflow)
        self.assertIn("Tied", text)

    def test_arguments_the_wrong_way_round_are_caught(self):
        scored = ranking.rank(constrained_workflows())
        text = ranking.explain(scored[-1].workflow, scored[0].workflow)
        self.assertIn("B is the cheaper", text)


class TestAgreement(unittest.TestCase):
    def test_identical_ordering_gives_tau_one(self):
        scored = ranking.rank(constrained_workflows())
        reference = [item.expression for item in scored]
        self.assertEqual(ranking.agreement(scored, reference)["tau"], 1.0)

    def test_reversed_ordering_gives_tau_minus_one(self):
        scored = ranking.rank(constrained_workflows())
        reference = list(reversed([item.expression for item in scored]))
        self.assertEqual(ranking.agreement(scored, reference)["tau"], -1.0)

    def test_a_partial_reference_is_usable(self):
        scored = ranking.rank(constrained_workflows())
        reference = [item.expression for item in scored[:5]]
        result = ranking.agreement(scored, reference)
        self.assertEqual(result["n"], 5)
        self.assertEqual(result["pairs"], 10)

    def test_unknown_expressions_are_ignored_not_fatal(self):
        scored = ranking.rank(constrained_workflows())
        reference = ["NotAWorkflow(x)"] + [i.expression for i in scored[:3]]
        result = ranking.agreement(scored, reference)
        self.assertEqual(result["n"], 3)

    def test_too_few_shared_items_returns_none_rather_than_zero(self):
        """Zero would read as no agreement. None says the question was not
        answerable, which is a different statement."""
        scored = ranking.rank(constrained_workflows())
        result = ranking.agreement(scored, [scored[0].expression])
        self.assertIsNone(result["tau"])


class TestDisagreements(unittest.TestCase):
    def test_none_when_the_model_agrees(self):
        scored = ranking.rank(constrained_workflows())
        reference = [item.expression for item in scored]
        self.assertEqual(ranking.disagreements(scored, reference), ())

    def test_every_flipped_pair_is_named(self):
        scored = ranking.rank(constrained_workflows())
        reference = list(reversed([item.expression for item in scored[:5]]))
        rows = ranking.disagreements(scored, reference)
        self.assertEqual(len(rows), 10)
        for row in rows:
            self.assertIn("reference_prefers", row)
            self.assertIn("model_prefers", row)


class TestStability(unittest.TestCase):
    def test_the_winner_survives_doubling_and_halving_every_weight(self):
        workflows = constrained_workflows()
        result = ranking.stability(workflows, CostModel())
        self.assertEqual(result["variants"], 2 * len(Weights().as_dict()))
        self.assertTrue(
            result["stable"],
            "winner changed under {0}".format(result["alternatives"]),
        )

    def test_an_empty_set_does_not_raise(self):
        self.assertIsNone(ranking.stability([])["winner"])


class TestPlan(unittest.TestCase):
    def test_a_shared_intermediate_is_written_once(self):
        """The reason plan() exists. The nested expression prints a shared
        intermediate once per consumer, so the workflow reads as doing the work
        twice when it does it once."""
        workflows = constrained_workflows()
        shared = [
            w for w in workflows
            if w.expression().count("Clip(noise, district)") > 1
        ]
        self.assertTrue(shared)
        text = ranking.plan(shared[0])
        self.assertEqual(text.count("= Clip("), 1)

    def test_every_step_is_bound_and_the_result_is_named(self):
        workflow = build_chain(
            (("Constrain", ("noise",)), ("Coverage", ("$0", "district")),
             ("Proportion", ("$1",))),
            SOURCES,
        )
        text = ranking.plan(workflow)
        self.assertIn("a = Constrain(noise)", text)
        self.assertIn("b = Coverage(a, district)", text)
        self.assertIn("c = Proportion(b)", text)
        self.assertIn("result: c", text)

    def test_sharing_counts_consumers_not_occurrences(self):
        workflows = constrained_workflows()
        shared = [w for w in workflows if ranking.sharing(w)["count"] > 0]
        self.assertTrue(shared)
        for workflow in shared:
            for _name, count in ranking.sharing(workflow)["shared"]:
                self.assertGreater(count, 1)


class TestWithProfiles(unittest.TestCase):
    def test_a_worse_source_moves_a_workflow_down(self):
        workflows = constrained_workflows()
        clean = ranking.rank(workflows, CostModel())
        penalised = ranking.rank(
            workflows,
            CostModel(profiles=[SourceProfile("noise", resolution_m=320.0, year=2004)]),
        )
        self.assertGreater(penalised[0].total, clean[0].total)


if __name__ == "__main__":
    unittest.main()
