"""The controlled phrasings, and what they refuse."""

import unittest

import ccd
import request as request_parser


class TestParsing(unittest.TestCase):
    def test_a_proportion_is_intensive(self):
        query = request_parser.parse(
            "proportion of area where noise >= 70 dB for each district"
        )
        self.assertEqual(query.target.concept, ccd.OBJECT)
        self.assertEqual(query.target.quality, ccd.INTENSIVE)
        self.assertEqual(query.target.support, ccd.REGION_SUPPORT)

    def test_a_total_area_is_extensive(self):
        query = request_parser.parse(
            "total area where noise >= 70 dB for each district"
        )
        self.assertEqual(query.target.quality, ccd.EXTENSIVE)

    def test_a_mean_is_intensive_and_carries_no_constraint(self):
        query = request_parser.parse("mean noise for each district")
        self.assertEqual(query.target.quality, ccd.INTENSIVE)
        self.assertEqual(query.constraints, ())
        self.assertEqual(query.required_transformations(), frozenset())

    def test_the_terms_are_recovered(self):
        query = request_parser.parse(
            "proportion of area where noise >= 70 dB for each district"
        )
        self.assertEqual(query.field_term, "noise")
        self.assertEqual(query.object_term, "district")

    def test_the_constraint_is_recovered(self):
        query = request_parser.parse(
            "proportion of area where noise >= 70 dB for each district"
        )
        constraint = query.constraints[0]
        self.assertEqual(constraint.operator, ">=")
        self.assertEqual(constraint.value, 70.0)
        self.assertEqual(constraint.unit, "dB")
        self.assertEqual(str(constraint), "noise >= 70 dB")

    def test_a_threshold_forces_a_constrain_step(self):
        query = request_parser.parse(
            "total area where slope > 15 for each parcel"
        )
        self.assertEqual(
            query.required_transformations(), frozenset({"Constrain"})
        )

    def test_the_unit_is_optional(self):
        query = request_parser.parse(
            "proportion of area where slope >= 15 for each parcel"
        )
        self.assertEqual(query.constraints[0].unit, "")

    def test_whitespace_and_a_question_mark_are_tolerated(self):
        query = request_parser.parse(
            "  proportion of area  where noise >= 70 dB for each district ? "
        )
        self.assertEqual(query.field_term, "noise")

    def test_describe_mentions_the_implied_step(self):
        query = request_parser.parse(
            "proportion of area where noise >= 70 dB for each district"
        )
        self.assertIn("Constrain", query.describe())


class TestRefusal(unittest.TestCase):
    def test_a_question_in_english_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            request_parser.parse(
                "What is the proportion of area covered by >= 70 dB noise "
                "for each district in Amsterdam?"
            )
        # The refusal has to show the grammar, because the whole point of a
        # parser this small is that its limits are visible.
        self.assertIn("proportion of area where", str(caught.exception))

    def test_an_unsupported_aggregate_is_refused(self):
        with self.assertRaises(ValueError):
            request_parser.parse("median noise for each district")

    def test_a_missing_grouping_is_refused(self):
        with self.assertRaises(ValueError):
            request_parser.parse("mean noise")


class TestEnglishSurface(unittest.TestCase):
    def test_english_threshold_question_maps_to_the_same_ir(self):
        query = request_parser.parse_question(
            "What is the proportion of area covered by >= 70 dB noise "
            "for each district in Amsterdam?"
        )
        self.assertEqual(query.target.quality, ccd.INTENSIVE)
        self.assertEqual(query.required_transformations(), frozenset({"Constrain"}))
        self.assertEqual(str(query.constraints[0]), "noise >= 70 dB")

    def test_at_least_wording_is_normalised(self):
        query = request_parser.parse_question(
            "What proportion of each district is covered by noise at least 70 dB?"
        )
        self.assertEqual(query.constraints[0].operator, ">=")

    def test_average_wording_maps_to_mean(self):
        query = request_parser.parse_question(
            "What is the average noise for each district?"
        )
        self.assertEqual(query.target.quality, ccd.INTENSIVE)
        self.assertEqual(query.constraints, ())

    def test_unsupported_english_is_refused_with_its_own_grammar(self):
        with self.assertRaises(ValueError) as caught:
            request_parser.parse_question("Which districts are noisy?")
        self.assertIn("what is the proportion", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
