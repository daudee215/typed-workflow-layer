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
from urllib.parse import quote

from ccd import CCDType

FORMAT_VERSION = "ctg/1"
PROV_NS = "http://www.w3.org/ns/prov#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"


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

    def __post_init__(self) -> None:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("provenance node ids must be unique")
        known = set(node_ids)
        source_ids = {node.id for node in self.nodes if node.kind == "source"}
        if any(node.kind not in ("source", "derived") for node in self.nodes):
            raise ValueError("provenance node kind must be source or derived")
        if set(self.sources_consumed) != source_ids:
            raise ValueError(
                "sources_consumed must list exactly the graph's source nodes"
            )
        if self.result not in known:
            raise ValueError("provenance result must reference a known node")
        outputs = [edge.output for edge in self.edges]
        if len(outputs) != len(set(outputs)):
            raise ValueError("each provenance node may have only one producer")
        for edge in self.edges:
            if edge.output not in known:
                raise ValueError("edge output {0!r} is not a known node".format(edge.output))
            if any(item not in known for item in edge.inputs):
                raise ValueError("edge input references an unknown node")

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
    def _prov_id(kind: str, value: str) -> str:
        return "urn:ctg:{0}:{1}".format(kind, quote(str(value), safe="._-"))

    @staticmethod
    def _literal(value: str) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    def to_prov_json(self) -> dict:
        """Return a dependency-free PROV-O shaped JSON document.

        The ordinary CTG JSON remains the stable round-trip format. This
        export adds interoperable entity/activity relations without requiring
        rdflib or a serialisation package, so experiments can archive both the
        compact graph and a standards-facing representation.
        """
        entities = []
        for node in self.nodes:
            entities.append({
                "id": self._prov_id("entity", node.id),
                "type": "prov:Entity",
                "ccd_type": node.type.serialise(),
                "kind": node.kind,
                "label": node.label,
            })
        activities = []
        generated = []
        used = []
        derived = []
        for index, edge in enumerate(self.edges, start=1):
            activity_id = self._prov_id("activity", edge.output)
            output_id = self._prov_id("entity", edge.output)
            activities.append({
                "id": activity_id,
                "type": "prov:Activity",
                "transformation": edge.transformation,
                "description": edge.description,
            })
            generated.append({"entity": output_id, "activity": activity_id})
            for input_id in edge.inputs:
                input_entity = self._prov_id("entity", input_id)
                used.append({"activity": activity_id, "entity": input_entity})
                derived.append({"generatedEntity": output_id,
                                "usedEntity": input_entity})
        return {
            "@context": {
                "prov": PROV_NS,
                "rdfs": RDFS_NS,
                "ccd_type": "urn:ctg:ccd_type",
            },
            "question": self.question,
            "entity": entities,
            "activity": activities,
            "wasGeneratedBy": generated,
            "used": used,
            "wasDerivedFrom": derived,
        }

    def to_prov_turtle(self) -> str:
        """Return deterministic PROV-O/Turtle for the conceptual graph."""
        lines = [
            "@prefix prov: <{0}> .".format(PROV_NS),
            "@prefix rdfs: <{0}> .".format(RDFS_NS),
            "@prefix ccd: <urn:ctg:> .",
            "",
        ]
        for node in self.nodes:
            subject = "<{0}>".format(self._prov_id("entity", node.id))
            lines.append(
                "{0} a prov:Entity ; ccd:ccd_type {1} ; ccd:kind {2} ; "
                "rdfs:label {3} .".format(
                    subject,
                    self._literal(node.type.serialise()),
                    self._literal(node.kind),
                    self._literal(node.label),
                )
            )
        for edge in self.edges:
            activity = "<{0}>".format(self._prov_id("activity", edge.output))
            output = "<{0}>".format(self._prov_id("entity", edge.output))
            lines.append(
                "{0} a prov:Activity ; ccd:transformation {1} ; "
                "rdfs:label {2} .".format(
                    activity,
                    self._literal(edge.transformation),
                    self._literal(edge.description),
                )
            )
            lines.append("{0} prov:wasGeneratedBy {1} .".format(output, activity))
            for input_id in edge.inputs:
                source = "<{0}>".format(self._prov_id("entity", input_id))
                lines.append("{0} prov:used {1} .".format(activity, source))
                lines.append("{0} prov:wasDerivedFrom {1} .".format(output, source))
        return "\n".join(lines) + "\n"

    @staticmethod
    def from_dict(payload: dict) -> "ConceptualTransformationGraph":
        if not isinstance(payload, dict):
            raise ValueError("provenance payload must be a dictionary")
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
