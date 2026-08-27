"""The signatures, especially the ones the rest of the package leans on."""

import unittest

import catalogue
import ccd
from ccd import CCDType

FIELD_INTERVAL_REGION = CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT)
FIELD_NOMINAL_REGION = CCDType(ccd.FIELD, ccd.NOMINAL, ccd.REGION_SUPPORT)
DISTRICTS = CCDType(ccd.OBJECT, ccd.NOMINAL, ccd.REGION_SUPPORT)


class TestSignatures(unittest.TestCase):
    def test_coverage_produces_an_extensive_quantity_on_an_object(self):
        coverage = catalogue.get("Coverage")
        output = coverage.output_type([FIELD_NOMINAL_REGION, DISTRICTS])
        self.assertEqual(output.concept, ccd.OBJECT)
        self.assertEqual(output.quality, ccd.EXTENSIVE)

    def test_zonal_statistics_produces_an_intensive_quantity(self):
        zonal = catalogue.get("ZonalStatistics")
        output = zonal.output_type([FIELD_INTERVAL_REGION, DISTRICTS])
        self.assertEqual(output.quality, ccd.INTENSIVE)

    def test_aggregate_refuses_an_intensive_quantity(self):
        aggregate = catalogue.get("Aggregate")
        intensive = CCDType(ccd.OBJECT, ccd.INTENSIVE, ccd.REGION_SUPPORT)
        self.assertFalse(aggregate.accepts([intensive]))
        self.assertTrue(
            aggregate.accepts(
                [CCDType(ccd.OBJECT, ccd.EXTENSIVE, ccd.REGION_SUPPORT)]
            )
        )

    def test_constrain_keeps_the_support_of_its_input(self):
        constrain = catalogue.get("Constrain")
        for support in (ccd.REGION_SUPPORT, ccd.LATTICE_SUPPORT):
            output = constrain.output_type(
                [CCDType(ccd.FIELD, ccd.INTERVAL, support)]
            )
            self.assertEqual(output.support, support)
            self.assertEqual(output.quality, ccd.NOMINAL)

    def test_clip_keeps_both_the_quality_and_the_support(self):
        clip = catalogue.get("Clip")
        output = clip.output_type([FIELD_INTERVAL_REGION, DISTRICTS])
        self.assertEqual(output, FIELD_INTERVAL_REGION)

    def test_interpolate_needs_point_support(self):
        interpolate = catalogue.get("Interpolate")
        self.assertFalse(interpolate.accepts([FIELD_INTERVAL_REGION]))
        self.assertTrue(
            interpolate.accepts(
                [CCDType(ccd.FIELD, ccd.INTERVAL, ccd.POINT_SUPPORT)]
            )
        )

    def test_a_nominal_slot_accepts_a_ratio_field(self):
        # Not an accident: the extra structure of a finer scale can always be
        # ignored, which is why the scale hierarchy runs this way round.
        coverage = catalogue.get("Coverage")
        self.assertTrue(
            coverage.accepts(
                [CCDType(ccd.FIELD, ccd.RATIO, ccd.REGION_SUPPORT), DISTRICTS]
            )
        )

    def test_every_entry_has_a_description_and_a_readable_signature(self):
        for name, entry in catalogue.CATALOGUE.items():
            self.assertTrue(entry.description.strip(), name)
            self.assertIn("->", entry.signature())
            self.assertEqual(entry.name, name)

    def test_overlay_rejects_fields_on_different_supports(self):
        overlay = catalogue.get("Overlay")
        failures = overlay.check([
            CCDType(ccd.FIELD, ccd.NOMINAL, ccd.REGION_SUPPORT),
            CCDType(ccd.FIELD, ccd.NOMINAL, ccd.POINT_SUPPORT),
        ])
        self.assertEqual(len(failures), 1)
        self.assertIn("must agree on support", str(failures[0]))

    def test_direct_check_reports_wrong_arity_clearly(self):
        with self.assertRaises(ValueError) as caught:
            catalogue.get("Coverage").check([FIELD_NOMINAL_REGION])
        self.assertIn("expects 2 input(s)", str(caught.exception))


class TestRepairSuggestions(unittest.TestCase):
    def test_only_coverage_reaches_an_object_from_a_nominal_field(self):
        self.assertEqual(
            catalogue.producing(CCDType(ccd.OBJECT), FIELD_NOMINAL_REGION),
            ("Coverage",),
        )

    def test_an_interval_field_can_also_be_summarised(self):
        self.assertIn(
            "ZonalStatistics",
            catalogue.producing(CCDType(ccd.OBJECT), FIELD_INTERVAL_REGION),
        )

    def test_nothing_turns_a_region_field_into_a_point_field(self):
        # The suggestion has to answer on the axis that failed. Every field to
        # field entry preserves or fixes the support, so there is no advice to
        # give here and the honest answer is an empty tuple.
        self.assertEqual(
            catalogue.producing(
                CCDType(ccd.FIELD, ccd.INTERVAL, ccd.POINT_SUPPORT),
                FIELD_INTERVAL_REGION,
            ),
            (),
        )

    def test_a_suggestion_accounts_for_an_inherited_axis(self):
        # Constrain declares its output support as the top term and fixes it
        # only from its input, so a check that compared declared outputs would
        # miss it.
        self.assertIn(
            "Constrain",
            catalogue.producing(FIELD_NOMINAL_REGION, FIELD_INTERVAL_REGION),
        )

    def test_unknown_names_raise_with_the_known_ones_listed(self):
        with self.assertRaises(KeyError) as caught:
            catalogue.get("Kriging")
        self.assertIn("Coverage", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
