"""Enumeration, refusal, and the reason given for a refusal."""

import unittest

import catalogue
import ccd
import request as request_parser
from ccd import CCDType
from synthesis import (
    Dataset,
    build_chain,
    enumerate_workflows,
    why_rejected,
)

NOISE = Dataset("noise", CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT))
DISTRICT = Dataset(
    "district", CCDType(ccd.OBJECT, ccd.NOMINAL, ccd.REGION_SUPPORT)
)
SOURCES = (NOISE, DISTRICT)

AMSTERDAM = "proportion of area where noise >= 70 dB for each district"
INTENDED = "Proportion(Coverage(Constrain(noise), district))"


class TestEnumeration(unittest.TestCase):
    def test_the_amsterdam_workflow_is_found(self):
        query = request_parser.parse(AMSTERDAM)
        workflows = enumerate_workflows(
            SOURCES,
            query.target,
            max_depth=3,
            must_use=query.required_transformations(),
        )
        self.assertIn(INTENDED, [item.expression() for item in workflows])

    def test_enumeration_returns_more_than_one_valid_path(self):
        query = request_parser.parse(AMSTERDAM)
        workflows = enumerate_workflows(SOURCES, query.target, max_depth=3)
        self.assertGreater(len(workflows), 1)
        expressions = [item.expression() for item in workflows]
        self.assertEqual(len(expressions), len(set(expressions)))

    def test_every_returned_workflow_actually_reaches_the_target(self):
        query = request_parser.parse(AMSTERDAM)
        for workflow in enumerate_workflows(SOURCES, query.target, max_depth=3):
            self.assertTrue(query.target.subsumes(workflow.result.type))

    def test_every_returned_workflow_type_checks_step_by_step(self):
        # The guarantee that matters: nothing that fails unification is ever
        # returned, however it was reached.
        query = request_parser.parse(AMSTERDAM)
        for workflow in enumerate_workflows(SOURCES, query.target, max_depth=4):
            for step in workflow.steps:
                transformation = catalogue.get(step.transformation)
                types = [
                    workflow.dataset(reference).type
                    for reference in step.inputs
                ]
                self.assertTrue(
                    transformation.accepts(types),
                    "{0} in {1}".format(step.transformation, workflow.expression()),
                )

    def test_a_constraint_narrows_the_set(self):
        query = request_parser.parse(AMSTERDAM)
        unfiltered = enumerate_workflows(SOURCES, query.target, max_depth=3)
        filtered = enumerate_workflows(
            SOURCES,
            query.target,
            max_depth=3,
            must_use=query.required_transformations(),
        )
        self.assertLess(len(filtered), len(unfiltered))
        for workflow in filtered:
            self.assertIn("Constrain", workflow.transformations_used())

    def test_the_depth_bound_is_respected(self):
        query = request_parser.parse(AMSTERDAM)
        for depth in (1, 2, 3):
            for workflow in enumerate_workflows(
                SOURCES, query.target, max_depth=depth
            ):
                self.assertLessEqual(workflow.depth, depth)

    def test_an_unreachable_target_yields_nothing(self):
        target = CCDType(ccd.NETWORK, ccd.COUNT, ccd.REGION_SUPPORT)
        self.assertEqual(
            enumerate_workflows(SOURCES, target, max_depth=4), []
        )

    def test_the_cap_is_honoured(self):
        query = request_parser.parse(AMSTERDAM)
        capped = enumerate_workflows(
            SOURCES, query.target, max_depth=4, max_workflows=5
        )
        self.assertLessEqual(len(capped), 5)

    def test_sources_consumed_are_recorded(self):
        query = request_parser.parse(AMSTERDAM)
        workflow = build_chain(
            (
                ("Constrain", ("noise",)),
                ("Coverage", ("$0", "district")),
                ("Proportion", ("$1",)),
            ),
            SOURCES,
        )
        self.assertEqual(
            sorted(item.name for item in workflow.sources_consumed()),
            ["district", "noise"],
        )
        self.assertTrue(query.target.subsumes(workflow.result.type))


class TestRefusal(unittest.TestCase):
    def test_a_valid_chain_is_not_rejected(self):
        chain = (
            ("Constrain", ("noise",)),
            ("Coverage", ("$0", "district")),
            ("Proportion", ("$1",)),
        )
        self.assertIsNone(why_rejected(chain, SOURCES))

    def test_a_chain_skipping_the_field_to_object_step_is_refused(self):
        chain = (("Constrain", ("noise",)), ("Proportion", ("$0",)))
        rejection = why_rejected(chain, SOURCES)
        self.assertIsNotNone(rejection)
        self.assertEqual(rejection.kind, "type")

    def test_the_reason_names_the_failing_step_and_axes(self):
        chain = (("Constrain", ("noise",)), ("Proportion", ("$0",)))
        rejection = why_rejected(chain, SOURCES)
        self.assertEqual(rejection.step_index, 1)
        self.assertEqual(rejection.transformation, "Proportion")
        self.assertEqual(rejection.slot, 0)
        axes = {item.axis for item in rejection.axis_mismatches}
        self.assertEqual(axes, {"core concept", "quality"})
        explanation = rejection.explain()
        self.assertIn("Step 2 of the chain, Proportion", explanation)
        self.assertIn("Object required, Field given", explanation)
        self.assertIn("Coverage", explanation)

    def test_a_support_failure_is_reported_on_the_support_axis(self):
        rejection = why_rejected((("Interpolate", ("noise",)),), SOURCES)
        self.assertEqual(
            [item.axis for item in rejection.axis_mismatches], ["support"]
        )
        self.assertIn("PointSupport required", rejection.explain())

    def test_an_unknown_source_is_reported(self):
        rejection = why_rejected((("Constrain", ("traffic",)),), SOURCES)
        self.assertEqual(rejection.kind, "unknown_input")
        self.assertIn("traffic", rejection.explain())

    def test_a_malformed_step_reference_is_reported(self):
        rejection = why_rejected((
            ("Constrain", ("$-1",)),
        ), SOURCES)
        self.assertEqual(rejection.kind, "unknown_input")
        self.assertIn("non-negative step index", rejection.explain())

    def test_overlay_reports_a_cross_slot_support_failure(self):
        point_field = Dataset(
            "points", CCDType(ccd.FIELD, ccd.NOMINAL, ccd.POINT_SUPPORT)
        )
        rejection = why_rejected(
            (("Overlay", ("noise", "points")),),
            SOURCES + (point_field,),
        )
        self.assertEqual(rejection.kind, "cross_slot")
        self.assertIn("must agree on support", rejection.explain())

    def test_an_unknown_transformation_is_reported(self):
        rejection = why_rejected((("Kriging", ("noise",)),), SOURCES)
        self.assertEqual(rejection.kind, "unknown_transformation")

    def test_wrong_arity_is_reported(self):
        rejection = why_rejected(
            (("Coverage", ("noise",)),), SOURCES
        )
        self.assertEqual(rejection.kind, "arity")
        self.assertIn("takes 2 input(s)", rejection.explain())

    def test_build_chain_refuses_to_construct_a_rejected_chain(self):
        chain = (("Constrain", ("noise",)), ("Proportion", ("$0",)))
        with self.assertRaises(TypeError) as caught:
            build_chain(chain, SOURCES)
        self.assertIn("Proportion", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
