"""The conceptual transformation graph, and its round trip through JSON."""

import json
import unittest

import ccd
import provenance
from ccd import CCDType
from synthesis import Dataset, build_chain

SOURCES = (
    Dataset("noise", CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT)),
    Dataset("district", CCDType(ccd.OBJECT, ccd.NOMINAL, ccd.REGION_SUPPORT)),
    Dataset("stations", CCDType(ccd.OBJECT, ccd.NOMINAL, ccd.POINT_SUPPORT)),
)

CHAIN = (
    ("Constrain", ("noise",)),
    ("Coverage", ("$0", "district")),
    ("Proportion", ("$1",)),
)

QUESTION = "proportion of area where noise >= 70 dB for each district"


def build_graph():
    return provenance.from_workflow(build_chain(CHAIN, SOURCES), QUESTION)


class TestGraphContent(unittest.TestCase):
    def test_nodes_are_types_and_edges_are_transformations(self):
        graph = build_graph()
        self.assertEqual(
            [edge.transformation for edge in graph.edges],
            ["Constrain", "Coverage", "Proportion"],
        )
        self.assertEqual(
            graph.node(graph.result).type,
            CCDType(ccd.OBJECT, ccd.INTENSIVE, ccd.REGION_SUPPORT),
        )

    def test_only_the_consumed_sources_are_recorded(self):
        graph = build_graph()
        self.assertEqual(
            sorted(graph.sources_consumed), ["district", "noise"]
        )
        self.assertNotIn("stations", graph.sources_consumed)

    def test_the_question_travels_with_the_graph(self):
        self.assertEqual(build_graph().question, QUESTION)

    def test_every_edge_carries_its_description(self):
        for edge in build_graph().edges:
            self.assertTrue(edge.description.strip())

    def test_the_text_tree_reads_from_the_answer_backwards(self):
        lines = build_graph().to_text_tree().splitlines()
        self.assertIn("Proportion", lines[0])
        self.assertIn("IntensiveQuantity", lines[0])
        self.assertIn("source: noise", lines[-2])
        self.assertIn("source: district", lines[-1])

    def test_the_extensive_step_is_visible_in_the_tree(self):
        tree = build_graph().to_text_tree()
        self.assertIn("ExtensiveQuantity", tree)
        self.assertIn("Coverage", tree)


class TestSerialisation(unittest.TestCase):
    def test_round_trip_through_json(self):
        graph = build_graph()
        restored = provenance.ConceptualTransformationGraph.from_json(
            graph.to_json()
        )
        self.assertEqual(restored, graph)

    def test_round_trip_preserves_the_text_tree(self):
        graph = build_graph()
        restored = provenance.ConceptualTransformationGraph.from_json(
            graph.to_json()
        )
        self.assertEqual(restored.to_text_tree(), graph.to_text_tree())

    def test_the_json_is_plain_data(self):
        payload = json.loads(build_graph().to_json())
        self.assertEqual(payload["format"], provenance.FORMAT_VERSION)
        self.assertEqual(payload["sources_consumed"], ["noise", "district"])

    def test_an_unknown_format_is_refused(self):
        payload = json.loads(build_graph().to_json())
        payload["format"] = "ctg/99"
        with self.assertRaises(ValueError):
            provenance.ConceptualTransformationGraph.from_dict(payload)

    def test_prov_json_has_entities_activities_and_relations(self):
        payload = build_graph().to_prov_json()
        self.assertEqual(len(payload["entity"]), 5)
        self.assertEqual(len(payload["activity"]), 3)
        self.assertEqual(len(payload["wasGeneratedBy"]), 3)
        self.assertEqual(len(payload["used"]), 4)
        self.assertEqual(payload["activity"][0]["transformation"], "Constrain")

    def test_prov_turtle_contains_the_core_prov_relations(self):
        turtle = build_graph().to_prov_turtle()
        self.assertIn("prov:Entity", turtle)
        self.assertIn("prov:Activity", turtle)
        self.assertIn("prov:wasGeneratedBy", turtle)
        self.assertIn("prov:used", turtle)
        self.assertIn('"Constrain"', turtle)


if __name__ == "__main__":
    unittest.main()
