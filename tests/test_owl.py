"""The ontology reader, and the ontology it reads.

Two kinds of test here. The first kind exercises the Turtle subset directly on
small inputs, including the malformed ones the reader has to refuse. The second
kind parses the real `ontology/ccd.ttl` with rdflib and asserts that the
dependency-free reader produced exactly the same set of triples. That second
test is the one that matters: a hand-written parser agreeing with itself proves
nothing, and the whole reason the lattice moved into OWL is that a reasoner can
read it too.
"""

import os
import unittest

import ccd
import owl


class TurtleSubset(unittest.TestCase):
    def test_a_prefixed_name_expands_against_its_declaration(self):
        triples = owl.parse_turtle(
            '@prefix ex: <http://example.org/> .\n'
            'ex:A ex:knows ex:B .\n')
        self.assertEqual(
            triples,
            [("http://example.org/A", "http://example.org/knows",
              "http://example.org/B")])

    def test_the_a_keyword_is_rdf_type(self):
        triples = owl.parse_turtle(
            '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
            '@prefix ex: <http://example.org/> .\n'
            'ex:A a owl:Class .\n')
        self.assertEqual(triples[0][1], owl.RDF_TYPE)
        self.assertEqual(triples[0][2], owl.OWL_CLASS)

    def test_a_semicolon_repeats_the_subject(self):
        triples = owl.parse_turtle(
            '@prefix ex: <http://example.org/> .\n'
            'ex:A ex:p ex:B ;\n'
            '     ex:q ex:C .\n')
        self.assertEqual([t[0] for t in triples],
                         ["http://example.org/A"] * 2)
        self.assertEqual([t[1] for t in triples],
                         ["http://example.org/p", "http://example.org/q"])

    def test_a_comma_repeats_the_subject_and_the_predicate(self):
        triples = owl.parse_turtle(
            '@prefix ex: <http://example.org/> .\n'
            'ex:A ex:p ex:B , ex:C .\n')
        self.assertEqual(len(triples), 2)
        self.assertEqual({t[2] for t in triples},
                         {"http://example.org/B", "http://example.org/C"})

    def test_literals_come_back_quoted_so_they_cannot_pass_as_iris(self):
        triples = owl.parse_turtle(
            '@prefix ex: <http://example.org/> .\n'
            'ex:A ex:label "a thing" .\n')
        self.assertEqual(triples[0][2], '"a thing"')

    def test_a_comment_is_not_a_triple(self):
        triples = owl.parse_turtle(
            '# ex:A ex:p ex:B .\n'
            '@prefix ex: <http://example.org/> .\n'
            'ex:A ex:p ex:C .  # trailing\n')
        self.assertEqual(len(triples), 1)
        self.assertEqual(triples[0][2], "http://example.org/C")

    def test_an_undeclared_prefix_is_refused_rather_than_guessed(self):
        with self.assertRaises(owl.OntologyError) as caught:
            owl.parse_turtle("ex:A ex:p ex:B .\n")
        self.assertIn("undeclared prefix", str(caught.exception))

    def test_a_missing_final_stop_is_refused(self):
        # Without this the last statement of a truncated file is dropped, and a
        # dropped statement is a missing subclass axiom.
        with self.assertRaises(owl.OntologyError):
            owl.parse_turtle(
                '@prefix ex: <http://example.org/> .\n'
                'ex:A ex:p ex:B\n')

    def test_a_character_outside_the_subset_is_refused(self):
        with self.assertRaises(owl.OntologyError) as caught:
            owl.parse_turtle(
                '@prefix ex: <http://example.org/> .\n'
                'ex:A ex:p [ ex:q ex:r ] .\n')
        self.assertIn("cannot read", str(caught.exception))


class Hierarchy(unittest.TestCase):
    def test_a_subclass_cycle_is_refused_at_load(self):
        # A cycle would make the ancestor walk in ccd.py loop forever.
        with self.assertRaises(owl.OntologyError) as caught:
            owl.Ontology(owl.parse_turtle(
                '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
                '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
                '@prefix ex: <http://example.org/> .\n'
                'ex:A a owl:Class ; rdfs:subClassOf ex:B .\n'
                'ex:B a owl:Class ; rdfs:subClassOf ex:A .\n'))
        self.assertIn("cycle", str(caught.exception))

    def test_an_undeclared_superclass_is_refused(self):
        with self.assertRaises(owl.OntologyError) as caught:
            owl.Ontology(owl.parse_turtle(
                '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
                '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
                '@prefix ex: <http://example.org/> .\n'
                'ex:A a owl:Class ; rdfs:subClassOf ex:Missing .\n'))
        self.assertIn("never declared", str(caught.exception))

    def test_two_superclasses_are_refused_because_an_axis_is_a_chain(self):
        # The componentwise checker walks one chain per axis. A diamond would
        # change what subsumes what without changing any code.
        ontology = owl.Ontology(owl.parse_turtle(
            '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
            '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
            '@prefix ex: <http://example.org/> .\n'
            'ex:Top a owl:Class .\n'
            'ex:Left a owl:Class ; rdfs:subClassOf ex:Top .\n'
            'ex:Right a owl:Class ; rdfs:subClassOf ex:Top .\n'
            'ex:Both a owl:Class ; rdfs:subClassOf ex:Left , ex:Right .\n'))
        with self.assertRaises(owl.OntologyError) as caught:
            ontology.single_parent_map("http://example.org/Top")
        self.assertIn("2 superclasses", str(caught.exception))

    def test_ancestors_are_nearest_first(self):
        self.assertEqual(
            [owl.local_name(name) for name in
             ccd.ONTOLOGY.ancestors("https://daudee.com/ns/ccd#Count")],
            ["ExtensiveQuantity", "Ratio", "Interval", "Ordinal", "Nominal",
             "AnyQuality"])


class TheShippedOntology(unittest.TestCase):
    def test_it_declares_exactly_three_roots(self):
        self.assertEqual(
            sorted(owl.local_name(name) for name in ccd.ONTOLOGY.roots()),
            ["AnyConcept", "AnyQuality", "AnySupport"])

    def test_the_lattice_the_checker_uses_came_out_of_the_file(self):
        # The point of the exercise: these are read, not written here.
        self.assertEqual(ccd.QUALITY_PARENT[ccd.COUNT], ccd.EXTENSIVE)
        self.assertEqual(ccd.QUALITY_PARENT[ccd.RATIO], ccd.INTERVAL)
        self.assertIsNone(ccd.CONCEPT_PARENT[ccd.ANY_CONCEPT])

    def test_network_and_event_are_beside_object_not_beneath_it(self):
        self.assertEqual(ccd.CONCEPT_PARENT[ccd.NETWORK], ccd.ANY_CONCEPT)
        self.assertEqual(ccd.CONCEPT_PARENT[ccd.EVENT], ccd.ANY_CONCEPT)
        self.assertFalse(
            ccd.CCDType(concept=ccd.OBJECT)
            .subsumes(ccd.CCDType(concept=ccd.NETWORK)))

    def test_every_class_carries_a_label_or_a_comment(self):
        # An ontology term with no gloss is a term whose meaning lives only in
        # whoever wrote it.
        bare = []
        for name in ccd.ONTOLOGY.classes:
            has_label = (name, owl.RDFS_LABEL) in ccd.ONTOLOGY.annotations
            has_comment = (name, owl.RDFS_COMMENT) in ccd.ONTOLOGY.annotations
            parent = ccd.ONTOLOGY.superclasses[name]
            # A leaf whose parent explains the axis needs no gloss of its own;
            # a root always does.
            if not parent and not (has_label and has_comment):
                bare.append(owl.local_name(name))
        self.assertEqual(bare, [])

    def test_the_ontology_ships_inside_the_package(self):
        self.assertTrue(os.path.exists(owl.ONTOLOGY_PATH))


class AgainstRdflib(unittest.TestCase):
    """The reader against a real RDF implementation, on the real file."""

    def _graph(self):
        try:
            import rdflib
        except ImportError:
            self.skipTest(
                "rdflib is not installed, so the ontology was NOT cross-checked "
                "against a reference RDF parser. Install it with "
                "pip install '.[check]' to run this.")
        graph = rdflib.Graph()
        graph.parse(owl.ONTOLOGY_PATH, format="turtle")
        return graph

    def _rdflib_triples(self, graph):
        import rdflib
        out = set()
        for subject, predicate, obj in graph:
            if isinstance(obj, rdflib.Literal):
                text = '"{0}"'.format(str(obj))
                if obj.language:
                    text += "@" + obj.language
            else:
                text = str(obj)
            out.add((str(subject), str(predicate), text))
        return out

    def test_the_two_parsers_produce_the_same_triples(self):
        graph = self._graph()
        theirs = self._rdflib_triples(graph)
        ours = set(ccd.ONTOLOGY.triples)
        self.assertEqual(
            ours, theirs,
            "only in the dependency-free reader: {0}\nonly in rdflib: {1}"
            .format(sorted(ours - theirs), sorted(theirs - ours)))

    def test_the_subclass_closure_agrees_with_rdflib(self):
        graph = self._graph()
        import rdflib
        from rdflib.namespace import RDFS
        for name in ccd.ONTOLOGY.classes:
            theirs = {
                str(parent) for parent
                in graph.transitive_objects(rdflib.URIRef(name),
                                            RDFS.subClassOf)
            } - {name}
            self.assertEqual(set(ccd.ONTOLOGY.ancestors(name)), theirs,
                             "ancestors disagree for " + owl.local_name(name))


if __name__ == "__main__":
    unittest.main()
