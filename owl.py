"""Reading the core concept ontology from OWL, with no dependencies.

`ontology/ccd.ttl` is the authority for the type lattice. This module reads it
and hands `ccd.py` a subsumption relation. The point is that the hierarchy is
data a reasoner can also read, rather than a Python dict that only this package
understands.

Scope of the reader. Turtle is a large grammar and this parses the subset the
ontology uses: `@prefix` directives, prefixed names, IRI references, the `a`
keyword, plain and language-tagged string literals, and the `;` and `,` list
forms. It does not implement blank nodes, collections, numeric or boolean
literals, long triple-quoted strings, or `@base`. Anything outside the subset
raises rather than being skipped, because a reader that silently ignores what it
cannot parse turns a typo in the ontology into a missing subclass axiom, and a
missing subclass axiom is a workflow that type checks when it should not.

Why not rdflib. The package claims to run from a bare interpreter, and that
claim is worth more than the few hundred lines below. rdflib is used instead as
a cross-check: `tests/test_owl.py` parses the same file with rdflib when it is
installed and asserts the two agree triple for triple, and a CI job installs it
so the comparison cannot quietly skip.
"""

from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"

RDF_TYPE = RDF + "type"
RDFS_SUBCLASS_OF = RDFS + "subClassOf"
RDFS_LABEL = RDFS + "label"
RDFS_COMMENT = RDFS + "comment"
OWL_CLASS = OWL + "Class"

ONTOLOGY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "ontology", "ccd.ttl")

_TOKEN = re.compile(
    r"""
      (?P<comment> \#[^\n]* )
    | (?P<iri>     <[^<>"{}|^`\\]*> )
    | (?P<literal> "(?:[^"\\]|\\.)*"(?:@[A-Za-z]+(?:-[A-Za-z0-9]+)*)? )
    | (?P<prefix>  @prefix\b )
    | (?P<pname>   [A-Za-z_][\w-]*:(?:[A-Za-z_][\w-]*)? )
    | (?P<a>       \ba\b )
    | (?P<punct>   [.;,] )
    | (?P<space>   \s+ )
    """,
    re.VERBOSE,
)


class OntologyError(ValueError):
    """The ontology could not be read, or says something the model forbids."""


def _tokenise(text: str) -> List[Tuple[str, str]]:
    tokens: List[Tuple[str, str]] = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            line = text.count("\n", 0, position) + 1
            snippet = text[position:position + 30].split("\n")[0]
            raise OntologyError(
                "line {0}: cannot read {1!r}".format(line, snippet))
        kind = match.lastgroup
        if kind not in ("space", "comment"):
            tokens.append((kind, match.group()))
        position = match.end()
    return tokens


def parse_turtle(text: str) -> List[Tuple[str, str, str]]:
    """Triples as (subject, predicate, object) with every name fully expanded.

    Literals come back quoted, so a literal and an IRI can never be mistaken
    for each other by a caller comparing strings.
    """
    prefixes: Dict[str, str] = {}
    triples: List[Tuple[str, str, str]] = []
    tokens = _tokenise(text)
    index = 0

    def expand(kind: str, value: str) -> str:
        if kind == "iri":
            return value[1:-1]
        if kind == "literal":
            return value
        if kind == "a":
            return RDF_TYPE
        head, _, tail = value.partition(":")
        if head not in prefixes:
            raise OntologyError("undeclared prefix {0!r}".format(head + ":"))
        return prefixes[head] + tail

    subject: Optional[str] = None
    predicate: Optional[str] = None

    while index < len(tokens):
        kind, value = tokens[index]

        if kind == "prefix":
            try:
                name_kind, name = tokens[index + 1]
                iri_kind, iri = tokens[index + 2]
                stop_kind, stop = tokens[index + 3]
            except IndexError:
                raise OntologyError("truncated @prefix directive")
            if name_kind != "pname" or iri_kind != "iri" or stop != ".":
                raise OntologyError("malformed @prefix directive")
            prefixes[name[:-1]] = iri[1:-1]
            index += 4
            subject = predicate = None
            continue

        if value == ".":
            subject = predicate = None
            index += 1
            continue

        if value == ";":
            predicate = None
            index += 1
            continue

        if value == ",":
            index += 1
            continue

        if subject is None:
            subject = expand(kind, value)
            index += 1
            continue

        if predicate is None:
            predicate = expand(kind, value)
            index += 1
            continue

        triples.append((subject, predicate, expand(kind, value)))
        index += 1

    if subject is not None:
        raise OntologyError("the ontology ends without a closing '.'")
    return triples


def load(path: str = ONTOLOGY_PATH) -> List[Tuple[str, str, str]]:
    with open(path, encoding="utf-8") as handle:
        return parse_turtle(handle.read())


def local_name(iri: str) -> str:
    """The part after the last # or /, which is the term as the code names it."""
    for separator in ("#", "/"):
        if separator in iri:
            return iri.rsplit(separator, 1)[1]
    return iri


class Ontology:
    """The class hierarchy of one OWL file, ready to answer subsumption."""

    def __init__(self, triples: Iterable[Tuple[str, str, str]]) -> None:
        self.triples: Tuple[Tuple[str, str, str], ...] = tuple(triples)
        self.classes: Set[str] = {
            s for s, p, o in self.triples
            if p == RDF_TYPE and o == OWL_CLASS
        }
        self.superclasses: Dict[str, List[str]] = {name: [] for name in self.classes}
        for subject, predicate, obj in self.triples:
            if predicate != RDFS_SUBCLASS_OF:
                continue
            if subject not in self.classes:
                raise OntologyError(
                    "{0} has a superclass but is never declared an owl:Class"
                    .format(local_name(subject)))
            if obj not in self.classes:
                raise OntologyError(
                    "{0} is used as a superclass but is never declared an "
                    "owl:Class".format(local_name(obj)))
            self.superclasses[subject].append(obj)
        self.annotations: Dict[Tuple[str, str], List[str]] = {}
        for subject, predicate, obj in self.triples:
            if predicate in (RDFS_LABEL, RDFS_COMMENT) and obj.startswith('"'):
                self.annotations.setdefault((subject, predicate), []).append(obj)
        self._check_acyclic()

    def _check_acyclic(self) -> None:
        # A cycle would make the ancestor walk in ccd.py run forever. Better to
        # refuse the ontology at import than to hang inside a type check.
        colour: Dict[str, int] = {}

        def visit(node: str) -> None:
            colour[node] = 1
            for parent in self.superclasses.get(node, ()):
                if colour.get(parent) == 1:
                    raise OntologyError(
                        "subclass cycle through {0}".format(local_name(parent)))
                if colour.get(parent) is None:
                    visit(parent)
            colour[node] = 2

        for name in self.classes:
            if colour.get(name) is None:
                visit(name)

    def roots(self) -> Set[str]:
        return {name for name in self.classes if not self.superclasses[name]}

    def ancestors(self, name: str) -> List[str]:
        """Every class above `name`, nearest first, excluding `name` itself."""
        found: List[str] = []
        frontier = list(self.superclasses.get(name, ()))
        while frontier:
            node = frontier.pop(0)
            if node in found:
                continue
            found.append(node)
            frontier.extend(self.superclasses.get(node, ()))
        return found

    def single_parent_map(self, root: str) -> Dict[str, Optional[str]]:
        """The one axis under `root`, as {term: parent or None}.

        Raises when a class under this root declares two superclasses. The
        package compares axes componentwise and walks a single chain to decide
        subsumption, so a diamond here would silently change what subsumes
        what. Refusing is the honest response: the ontology would be saying
        something the type checker cannot express.
        """
        axis: Dict[str, Optional[str]] = {local_name(root): None}
        for name in self.classes:
            if name == root or root not in self.ancestors(name):
                continue
            parents = self.superclasses[name]
            if len(parents) != 1:
                raise OntologyError(
                    "{0} declares {1} superclasses; the componentwise model "
                    "needs exactly one".format(local_name(name), len(parents)))
            axis[local_name(name)] = local_name(parents[0])
        return axis
