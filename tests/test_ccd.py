"""Subsumption, unification and the immutability of core concept data types."""

import unittest

import ccd
from ccd import CCDType


class TestAxisSubsumption(unittest.TestCase):
    def test_scale_hierarchy_runs_from_nominal_down_to_ratio(self):
        nominal = CCDType(ccd.FIELD, ccd.NOMINAL)
        ratio = CCDType(ccd.FIELD, ccd.RATIO)
        self.assertTrue(nominal.subsumes(ratio))
        self.assertFalse(ratio.subsumes(nominal))

    def test_extensive_and_intensive_are_both_ratios(self):
        ratio = CCDType(ccd.OBJECT, ccd.RATIO)
        self.assertTrue(ratio.subsumes(CCDType(ccd.OBJECT, ccd.EXTENSIVE)))
        self.assertTrue(ratio.subsumes(CCDType(ccd.OBJECT, ccd.INTENSIVE)))

    def test_extensive_and_intensive_do_not_subsume_each_other(self):
        extensive = CCDType(ccd.OBJECT, ccd.EXTENSIVE)
        intensive = CCDType(ccd.OBJECT, ccd.INTENSIVE)
        self.assertFalse(extensive.subsumes(intensive))
        self.assertFalse(intensive.subsumes(extensive))

    def test_count_is_extensive(self):
        self.assertTrue(
            CCDType(ccd.OBJECT, ccd.EXTENSIVE).subsumes(
                CCDType(ccd.OBJECT, ccd.COUNT)
            )
        )

    def test_top_terms_subsume_everything_on_their_axis(self):
        top = CCDType()
        for concept in (ccd.FIELD, ccd.OBJECT, ccd.NETWORK, ccd.EVENT):
            self.assertTrue(top.subsumes(CCDType(concept, ccd.COUNT)))

    def test_core_concepts_are_siblings(self):
        field = CCDType(ccd.FIELD)
        obj = CCDType(ccd.OBJECT)
        self.assertFalse(field.subsumes(obj))
        self.assertFalse(obj.subsumes(field))

    def test_supports_are_siblings(self):
        point = CCDType(ccd.FIELD, ccd.INTERVAL, ccd.POINT_SUPPORT)
        region = CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT)
        self.assertFalse(point.subsumes(region))
        self.assertFalse(region.subsumes(point))


class TestUnification(unittest.TestCase):
    def test_unify_returns_the_more_specific_type(self):
        general = CCDType(ccd.FIELD, ccd.NOMINAL)
        specific = CCDType(ccd.FIELD, ccd.RATIO, ccd.REGION_SUPPORT)
        self.assertEqual(general.unify(specific), specific)
        self.assertEqual(specific.unify(general), specific)

    def test_unify_mixes_axes(self):
        left = CCDType(ccd.FIELD, ccd.RATIO, ccd.ANY_SUPPORT)
        right = CCDType(ccd.ANY_CONCEPT, ccd.NOMINAL, ccd.LATTICE_SUPPORT)
        self.assertEqual(
            left.unify(right),
            CCDType(ccd.FIELD, ccd.RATIO, ccd.LATTICE_SUPPORT),
        )

    def test_unify_fails_across_core_concepts(self):
        self.assertIsNone(CCDType(ccd.FIELD).unify(CCDType(ccd.OBJECT)))

    def test_unify_fails_across_extensive_and_intensive(self):
        self.assertIsNone(
            CCDType(ccd.OBJECT, ccd.EXTENSIVE).unify(
                CCDType(ccd.OBJECT, ccd.INTENSIVE)
            )
        )

    def test_unify_fails_on_support_alone(self):
        self.assertIsNone(
            CCDType(ccd.FIELD, ccd.INTERVAL, ccd.POINT_SUPPORT).unify(
                CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT)
            )
        )


class TestMismatches(unittest.TestCase):
    def test_no_mismatches_when_accepted(self):
        required = CCDType(ccd.FIELD, ccd.NOMINAL)
        self.assertEqual(
            required.mismatches(CCDType(ccd.FIELD, ccd.RATIO)), ()
        )

    def test_every_failing_axis_is_reported(self):
        required = CCDType(ccd.OBJECT, ccd.EXTENSIVE, ccd.POINT_SUPPORT)
        actual = CCDType(ccd.FIELD, ccd.NOMINAL, ccd.REGION_SUPPORT)
        axes = [item.axis for item in required.mismatches(actual)]
        self.assertEqual(axes, ["core concept", "quality", "support"])

    def test_mismatch_reads_as_a_sentence(self):
        required = CCDType(ccd.OBJECT, ccd.EXTENSIVE)
        mismatch = required.mismatches(CCDType(ccd.FIELD, ccd.NOMINAL))[0]
        self.assertIn("Object required, Field given", str(mismatch))


class TestTypeIdentity(unittest.TestCase):
    def test_types_are_immutable(self):
        subject = CCDType(ccd.FIELD, ccd.NOMINAL)
        with self.assertRaises(Exception):
            subject.concept = ccd.OBJECT

    def test_types_are_hashable_and_compare_by_value(self):
        first = CCDType(ccd.FIELD, ccd.NOMINAL, ccd.REGION_SUPPORT)
        second = CCDType(ccd.FIELD, ccd.NOMINAL, ccd.REGION_SUPPORT)
        self.assertEqual(first, second)
        self.assertEqual(len({first, second}), 1)

    def test_unknown_terms_are_refused(self):
        with self.assertRaises(ValueError):
            CCDType("Blancmange")
        with self.assertRaises(ValueError):
            CCDType(ccd.FIELD, "Vibes")

    def test_serialisation_round_trips(self):
        subject = CCDType(ccd.OBJECT, ccd.INTENSIVE, ccd.REGION_SUPPORT)
        self.assertEqual(CCDType.parse(subject.serialise()), subject)

    def test_parse_refuses_rubbish(self):
        with self.assertRaises(ValueError):
            CCDType.parse("Field")


if __name__ == "__main__":
    unittest.main()
