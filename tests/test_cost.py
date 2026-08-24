"""The cost model: what it measures, and the claims it is making.

Several of these tests exist because the model was wrong when it was first
written and the output said so. The ordering test and the sharing test are both
of that kind, and they are named so that a later change that reintroduces the
error fails here rather than in a ranking a reviewer reads.
"""

import unittest

import ccd
import request as request_parser
from ccd import CCDType
from cost import (
    QUALITY_DEPTH,
    CostModel,
    SourceProfile,
    Weights,
    _position_weight,
    _redundancy,
    _scale_loss,
    _support_loss,
)
from synthesis import Dataset, build_chain, enumerate_workflows
from tests import subexpressions

NOISE = Dataset("noise", CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT))
DISTRICT = Dataset("district", CCDType(ccd.OBJECT, ccd.NOMINAL, ccd.REGION_SUPPORT))
SOURCES = (NOISE, DISTRICT)
QUESTION = "proportion of area where noise >= 70 dB for each district"


class TestQualityLattice(unittest.TestCase):
    def test_stevens_order_is_respected(self):
        self.assertLess(QUALITY_DEPTH[ccd.NOMINAL], QUALITY_DEPTH[ccd.ORDINAL])
        self.assertLess(QUALITY_DEPTH[ccd.ORDINAL], QUALITY_DEPTH[ccd.INTERVAL])
        self.assertLess(QUALITY_DEPTH[ccd.INTERVAL], QUALITY_DEPTH[ccd.RATIO])

    def test_count_is_deeper_than_extensive(self):
        self.assertGreater(QUALITY_DEPTH[ccd.COUNT], QUALITY_DEPTH[ccd.EXTENSIVE])


class TestScaleLoss(unittest.TestCase):
    def test_descent_costs(self):
        before = CCDType(ccd.FIELD, ccd.INTERVAL)
        after = CCDType(ccd.FIELD, ccd.NOMINAL)
        self.assertEqual(_scale_loss(before, after), 2.0)

    def test_ascent_is_free(self):
        """Interpolating a surface from points asserts structure rather than
        inventing information, and charging for it would penalise a legitimate
        modelling step."""
        before = CCDType(ccd.FIELD, ccd.NOMINAL)
        after = CCDType(ccd.FIELD, ccd.INTERVAL)
        self.assertEqual(_scale_loss(before, after), 0.0)

    def test_wildcard_axes_are_not_charged(self):
        before = CCDType(ccd.FIELD, ccd.ANY_QUALITY)
        after = CCDType(ccd.FIELD, ccd.NOMINAL)
        self.assertEqual(_scale_loss(before, after), 0.0)


class TestSupportLoss(unittest.TestCase):
    def test_point_to_region_is_coarsening(self):
        before = CCDType(ccd.FIELD, ccd.INTERVAL, ccd.POINT_SUPPORT)
        after = CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT)
        self.assertGreater(_support_loss(before, after), 0.0)

    def test_region_to_point_is_not_charged(self):
        before = CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT)
        after = CCDType(ccd.FIELD, ccd.INTERVAL, ccd.POINT_SUPPORT)
        self.assertEqual(_support_loss(before, after), 0.0)


class TestPositionWeighting(unittest.TestCase):
    def test_earlier_steps_weigh_more(self):
        self.assertGreater(_position_weight(0, 4), _position_weight(3, 4))

    def test_single_step_workflow_is_unweighted(self):
        self.assertEqual(_position_weight(0, 1), 1.0)

    def test_the_ordering_claim_holds_on_real_workflows(self):
        """The central claim of the model.

        Constraining to classes and then taking zonal statistics loses the
        values the statistics would have seen. Taking the statistics first does
        not. Both type check, both reach the target, and the model must
        separate them or it is measuring nothing.
        """
        early_loss = build_chain(
            (("Constrain", ("noise",)), ("Coverage", ("$0", "district")),
             ("Proportion", ("$1",))),
            SOURCES,
        )
        late_loss = build_chain(
            (("Clip", ("noise", "district")), ("Constrain", ("$0",)),
             ("Coverage", ("$1", "district")), ("Proportion", ("$2",))),
            SOURCES,
        )
        model = CostModel()
        self.assertLess(model.total(late_loss), model.total(early_loss))


class TestSourceProfile(unittest.TestCase):
    def test_finer_resolution_is_free(self):
        self.assertEqual(SourceProfile("a", resolution_m=10.0).penalty(2026), 0.0)

    def test_halving_resolution_costs_one_unit(self):
        self.assertAlmostEqual(
            SourceProfile("a", resolution_m=20.0).penalty(2026), 1.0, places=4
        )

    def test_age_costs(self):
        recent = SourceProfile("a", year=2024).penalty(2026)
        old = SourceProfile("a", year=2004).penalty(2026)
        self.assertGreater(old, recent)

    def test_penalty_is_bounded(self):
        awful = SourceProfile("a", resolution_m=100000.0, year=1900)
        self.assertLessEqual(awful.penalty(2026), 5.0)

    def test_unprofiled_sources_are_not_penalised(self):
        model = CostModel(profiles=[])
        workflow = build_chain(
            (("Constrain", ("noise",)), ("Coverage", ("$0", "district")),
             ("Proportion", ("$1",))),
            SOURCES,
        )
        self.assertEqual(model.cost(workflow).source, 0.0)


class TestRedundancy(unittest.TestCase):
    def test_sharing_an_intermediate_is_not_recomputation(self):
        """A workflow that computes one thing and feeds it to two steps is
        efficient. It only looks wasteful because expression() flattens a graph
        into a tree, and charging it would penalise the better workflow."""
        query = request_parser.parse(QUESTION)
        workflows = enumerate_workflows(
            SOURCES, query.target, max_depth=4,
            must_use=query.required_transformations(),
        )
        shared = [
            w for w in workflows
            if w.expression().count("Clip(noise, district)") > 1
        ]
        self.assertTrue(shared, "expected at least one workflow with a shared input")
        for workflow in shared:
            self.assertEqual(_redundancy(workflow), 0.0)

    def test_true_recomputation_is_charged(self):
        """The redundancy term still works, on the input it is actually for.

        This used to enumerate and look for a recomputing workflow among the
        results. That stopped being possible: the enumerator now keeps the
        shortest realisation of an expression, so it cannot emit one. The
        term's real domain was always chains arriving from outside, which is
        what build_chain exists for, and that is what is exercised here.
        """
        wasteful = build_chain(
            (
                ("Clip", ("noise", "district")),
                ("Clip", ("noise", "district")),
                ("Coverage", ("$0", "district")),
                ("Proportion", ("$2",)),
            ),
            SOURCES,
        )
        self.assertEqual(_redundancy(wasteful), 1.0)

    def test_the_enumerator_never_emits_a_recomputing_workflow(self):
        """The invariant the deduplication fix bought.

        Two step lists can render to the same expression, one computing a
        shared subexpression once and one computing it twice. Both are valid
        and one is a step longer. The search used to keep whichever it reached
        first, which was the longer one for 2 of the 176 workflows here, and
        cost.py charges length from len(workflow.steps), so those two were
        ranked worse for steps they did not need.
        """
        query = request_parser.parse(QUESTION)
        for depth in (3, 4):
            workflows = enumerate_workflows(SOURCES, query.target,
                                            max_depth=depth)
            charged = [w for w in workflows if _redundancy(w) > 0]
            self.assertEqual(
                charged, [],
                "depth {0}: enumerator emitted a workflow that recomputes "
                "something it already had".format(depth))

    def test_no_stored_workflow_is_longer_than_its_expression_needs(self):
        """The same invariant, measured structurally rather than through cost.

        A workflow's minimum step count is the number of distinct non-source
        subexpressions in its expression. Storing more steps than that means a
        shorter realisation of the same expression exists and was discarded.
        """
        query = request_parser.parse(QUESTION)
        for workflow in enumerate_workflows(SOURCES, query.target, max_depth=4):
            minimum = len(subexpressions(workflow.expression()))
            self.assertEqual(
                len(workflow.steps), minimum,
                "{0} is stored with {1} steps but needs {2}".format(
                    workflow.expression(), len(workflow.steps), minimum))


class TestWeights(unittest.TestCase):
    def test_every_component_has_a_weight(self):
        vector = CostModel().cost(
            build_chain(
                (("Constrain", ("noise",)), ("Coverage", ("$0", "district")),
                 ("Proportion", ("$1",))),
                SOURCES,
            )
        )
        self.assertEqual(
            set(vector.components(Weights())), set(Weights().as_dict())
        )

    def test_with_weights_does_not_mutate_the_original(self):
        model = CostModel()
        before = model.weights.scale_loss
        variant = model.with_weights(scale_loss=99.0)
        self.assertEqual(model.weights.scale_loss, before)
        self.assertEqual(variant.weights.scale_loss, 99.0)

    def test_zero_weights_collapse_the_ranking(self):
        """A sanity check on the arithmetic: with every weight at zero, every
        workflow costs the same, so any separation the model reports comes from
        the weights and not from somewhere unaccounted for."""
        query = request_parser.parse(QUESTION)
        workflows = enumerate_workflows(
            SOURCES, query.target, max_depth=3,
            must_use=query.required_transformations(),
        )
        flat = CostModel(
            weights=Weights(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        )
        totals = {flat.total(w) for w in workflows}
        self.assertEqual(totals, {0.0})


if __name__ == "__main__":
    unittest.main()
