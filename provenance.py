"""Self-describing conceptual transformation graphs.

A synthesised workflow is turned into a graph whose nodes are conceptual types
and whose edges are transformations, together with the list of sources it
consumed. The graph is self-describing: it documents the provenance of
anything the workflow produces, so a reader who is handed only the output can
still recover which sources it came from, what each intermediate quantity was,
and which transformation introduced it.

Design note on the format. Serialisation is a plain dictionary rather than
PROV-O or RDF. The graph carries the same three facts a PROV record would, an
entity, an activity and a derivation, and it round trips through JSON without a
dependency. Moving to PROV-O is a swap of the writer, not of the model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from ccd import CCDType

FORMAT_VERSION = "ctg/1"


@dataclass(frozen=True)
class Node:
    """A typed dataset in the graph. kind is source or derived."""

    id: str
    type: CCDType
    kind: str
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.serialise(),
            "kind": self.kind,
            "label": self.label,
        }

    @staticmethod
    def from_dict(payload: dict) -> "Node":
        return Node(
            payload["id"],
            CCDType.parse(payload["type"]),
            payload["kind"],
            payload.get("label", ""),
        )


@dataclass(frozen=True)
class Edge:
    """A transformation consuming one or more nodes and producing one node."""

    transformation: str
    inputs: tuple
    output: str
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "transformation": self.transformation,
            "inputs": list(self.inputs),
            "output": self.output,
            "description": self.description,
        }

    @staticmethod
    def from_dict(payload: dict) -> "Edge":
        return Edge(
            payload["transformation"],
            tuple(payload["inputs"]),
            payload["output"],
            payload.get("description", ""),
        )


@dataclass(frozen=True)
class ConceptualTransformationGraph:
    """The provenance of one workflow, in conceptual rather than file terms."""

    nodes: tuple
    edges: tuple
    sources_consumed: tuple
    result: str
    question: str = ""

    def node(self, node_id: str) -> Node:
        for candidate in self.nodes:
            if candidate.id == node_id:
                return candidate
        raise KeyError("no node {0!r}".format(node_id))

    def producer(self, node_id: str) -> Optional[Edge]:
        for edge in self.edges:
            if edge.output == node_id:
                return edge
        return None

    def to_dict(self) -> dict:
        return {
            "format": FORMAT_VERSION,
            "question": self.question,
            "result": self.result,
            "sources_consumed": list(self.sources_consumed),
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @staticmethod
    def from_dict(payload: dict) -> "ConceptualTransformationGraph":
        if payload.get("format") != FORMAT_VERSION:
            raise ValueError(
                "unsupported graph format: {0!r}".format(payload.get("format"))
            )
        return ConceptualTransformationGraph(
            tuple(Node.from_dict(item) for item in payload["nodes"]),
            tuple(Edge.from_dict(item) for item in payload["edges"]),
            tuple(payload["sources_consumed"]),
            payload["result"],
            payload.get("question", ""),
        )

    @staticmethod
    def from_json(text: str) -> "ConceptualTransformationGraph":
        return ConceptualTransformationGraph.from_dict(json.loads(text))

    def to_text_tree(self, indent: str = "  ") -> str:
        """The graph read backwards from the result, which is how it is read.

        A reader wants to know where an answer came from, so the tree starts at
        the answer and descends into what produced it.
        """
        lines = []

        def walk(node_id: str, level: int) -> None:
            node = self.node(node_id)
            edge = self.producer(node_id)
            prefix = indent * level
            if edge is None:
                lines.append(
                    "{0}{1}   [source: {2}]".format(prefix, node.type, node.label)
                )
                return
            lines.append(
                "{0}{1}   <- {2}".format(prefix, node.type, edge.transformation)
            )
            for reference in edge.inputs:
                walk(reference, level + 1)

        walk(self.result, 0)
        return "\n".join(lines)


def from_workflow(workflow, question: str = "") -> ConceptualTransformationGraph:
    """Build the conceptual transformation graph of a synthesised workflow."""
    from catalogue import get

    consumed = workflow.sources_consumed()
    nodes = [
        Node(source.name, source.type, "source", source.name)
        for source in consumed
    ]
    edges = []
    for step in workflow.steps:
        nodes.append(
            Node(step.output, step.output_type, "derived", step.transformation)
        )
        edges.append(
            Edge(
                step.transformation,
                tuple(step.inputs),
                step.output,
                get(step.transformation).description,
            )
        )
    return ConceptualTransformationGraph(
        tuple(nodes),
        tuple(edges),
        tuple(source.name for source in consumed),
        workflow.result.name,
        question,
    )
