"""Evidence graph schema.

Formalizes the Compass evidence model as an explicit graph so the agent and
engine reason about the *structure* of evidence, not just flat records. A
``EvidenceRecord`` is a path through the graph: an Organization facing a
Problem applies an Intervention (via a Technology and an Implementation) and
observes Outcomes backed by Metrics, all attributable to an Evidence Source
with per-field provenance.

Node and edge identifiers are stable strings intended to match the fields the
extraction/model code already produces, so the schema can be layered on without
a migration.

Relationships (source → target):
    Organization -[:IN_INDUSTRY]-> Industry
    Organization -[:HAS_PROBLEM]-> Problem
    Problem     -[:MOTIVATES]->  Intervention
    Intervention-[:_USES_]->    Technology
    Intervention-[::_IMPLEMENTS_VIA]-> Implementation
    Implementation-[_-YIELDS-> Outcome
    Outcome     -[:MEASURED_BY]-> Metric
    Intervention -[:LEADS_TO]->  Outcome
    Evidence    -[:ATTESTS_TO]-> Metric
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class NodeKind(str, Enum):
    ORGANIZATION = "organization"
    INDUSTRY = "industry"
    PROBLEM = "problem"
    INTERVENTION = "intervention"
    TECHNOLOGY = "technology"
    IMPLEMENTATION = "implementation"
    OUTCOME = "outcome"
    METRIC = "metric"
    EVIDENCE = "evidence"


class EdgeKind(str, Enum):
    IN_INDUSTRY = "in_industry"               # org -> industry
    HAS_PROBLEM = "has_problem"               # org -> problem
    MOTIVATES = "motivates"                   # problem -> intervention
    USES = "uses"                             # intervention -> technology
    IMPLEMENTS_VIA = "implements_via"         # intervention -> implementation
    YIELDS = "yields"                         # implementation -> outcome
    MEASURED_BY = "measured_by"               # outcome -> metric
    LEADS_TO = "leads_to"                     # intervention -> outcome
    ATTESTED_BY = "attested_by"               # evidence -> metric
    DERIVED_FROM = "derived_from"             # evidence -> document/source

# Node kinds that are first-class "entities" (dedup targets) vs. supporting
# facts that ride along on a record.
ENTITY_NODES = {
    NodeKind.ORGANIZATION,
    NodeKind.INDUSTRY,
    NodeKind.TECHNOLOGY,
    NodeKind.INTERVENTION,
    NodeKind.PROBLEM,
}


@dataclass
class Node:
    """A graph node. ``id`` is a stable, normalized identifier so the same
    entity (e.g. a canonical organization name, a technology) collapses across
    records."""

    id: str
    kind: NodeKind
    label: str = ""
    properties: dict = field(default_factory=dict)
    # Where this node's values came from: {field: source} with the document url
    # and extraction confidence.
    provenance: dict = field(default_factory=dict)


@dataclass
class Edge:
    """A typed, directed relationship between two nodes, with provenance."""

    source: str  # node id
    target: str   # node id
    kind: EdgeKind
    record_id: str = ""
    confidence: float = 0.5
    provenance: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind.value,
            "record_id": self.record_id,
            "confidence": round(self.confidence, 3),
            "provenance": self.provenance,
        }


@dataclass
class EvidenceGraph:
    """In-memory evidence graph assembled from one or more records."""

    nodes: dict = field(default_factory=dict)      # node id -> Node
    edges: list = field(default_factory=list)     # list[Edge]

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def ensure_node(self, node_id: str, kind: NodeKind, label: str = "", **props):
        if node_id not in self.nodes:
            self.add_node(Node(id=node_id, kind=kind, label=label, properties=get_node_properties(props)))
        return self.nodes[node_id]

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def neighbors(self, node_id: str, rel: Optional[EdgeKind] = None) -> "list[str]":
        """Direct out-neighbors of ``node_id``, optionally filtered by edge kind."""
        out = []
        for e in self.edges:
            if e.source != node_id:
                continue
            if rel is not None and e.kind != rel:
                continue
            out.append(e.target)
        return out


def get_node_properties(props: dict[str, Any]) -> dict[str, Any]:
    """Node properties are stored as plain values; keep types intact but gate
    mutable-dangerous values (none currently)."""
    return dict(props)


def normalize_id(kind: NodeKind, value: str) -> str:
    """Canonical identifier for an entity node: ``{kind}:{normalized-value}``."""
    return f"{kind.value}:{str(value or '').strip().lower()}".replace(" ", "_").replace(":", ":")


__all__ = [
    "Node",
    "Edge",
    "EvidenceGraph",
    "NodeKind",
    "EdgeKind",
    "normalize_id",
]