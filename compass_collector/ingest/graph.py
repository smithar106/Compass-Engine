"""Neo4j Evidence Graph — schema, upserts, and queries.

Connects to a Neo4j database to store and query the evidence graph.
All operations are idempotent — reprocessing the same source never
creates duplicate nodes or relationships.
"""

import logging
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from compass_collector.ingest import (
    EvidenceClaim, EvidenceRelationshipRecord, EvidenceRelationship,
    NormalizedEntity, Organization, Intervention, Problem, Metric,
)

logger = logging.getLogger(__name__)

# Environment variables for Neo4j connection
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")


def _get_driver():
    """Create a Neo4j driver. Returns None if neo4j is not installed."""
    try:
        from neo4j import GraphDatabase
        if not NEO4J_PASSWORD:
            logger.warning("NEO4J_PASSWORD not set. Graph operations disabled.")
            return None
        return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    except ImportError:
        logger.warning("neo4j package not installed. Install with: pip install neo4j")
        return None
    except Exception as e:
        logger.warning(f"Neo4j connection failed: {e}")
        return None


def upsert_organization(tx, org: Organization) -> str:
    """Create or update an Organization node. Returns the node ID."""
    name = org.normalized_name or org.name
    query = """
    MERGE (o:Organization {name: $name})
    ON CREATE SET
        o.id = randomUUID(),
        o.original_name = $original_name,
        o.industry = $industry,
        o.employee_count = $employee_count,
        o.created_at = $now
    ON MATCH SET
        o.industry = CASE WHEN $industry <> [] THEN $industry ELSE o.industry END,
        o.last_seen_at = $now
    RETURN o.id AS node_id
    """
    result = tx.run(query, name=name, original_name=org.name,
                    industry=org.industry, employee_count=org.employee_count or 0,
                    now=datetime.now(timezone.utc).isoformat())
    return result.single()["node_id"]


def upsert_intervention(tx, intervention: Intervention) -> str:
    """Create or update an Intervention node."""
    name = intervention.normalized_name or intervention.name
    query = """
    MERGE (i:Intervention {name: $name})
    ON CREATE SET
        i.id = randomUUID(),
        i.original_name = $original_name,
        i.intervention_type = $intervention_type,
        i.vendors = $vendors,
        i.created_at = $now
    ON MATCH SET
        i.last_seen_at = $now
    RETURN i.id AS node_id
    """
    result = tx.run(query, name=name, original_name=intervention.name,
                    intervention_type=intervention.intervention_type.value,
                    vendors=intervention.vendors,
                    now=datetime.now(timezone.utc).isoformat())
    return result.single()["node_id"]


def upsert_problem(tx, problem: Problem) -> str:
    """Create or update a Problem node."""
    name = problem.normalized_name or problem.name
    query = """
    MERGE (p:Problem {name: $name})
    ON CREATE SET
        p.id = randomUUID(),
        p.description = $description,
        p.business_function = $business_function,
        p.created_at = $now
    ON MATCH SET
        p.last_seen_at = $now
    RETURN p.id AS node_id
    """
    result = tx.run(query, name=name, description=problem.description,
                    business_function=problem.business_function,
                    now=datetime.now(timezone.utc).isoformat())
    return result.single()["node_id"]


def upsert_document(tx, source_url: str, title: str) -> str:
    """Create or update a Document node."""
    query = """
    MERGE (d:Document {source_url: $url})
    ON CREATE SET
        d.id = randomUUID(),
        d.title = $title,
        d.ingested_at = $now
    ON MATCH SET
        d.last_seen_at = $now
    RETURN d.id AS node_id
    """
    result = tx.run(query, url=source_url, title=title,
                    now=datetime.now(timezone.utc).isoformat())
    return result.single()["node_id"]


def upsert_claim(tx, claim: EvidenceClaim, document_node_id: str) -> str:
    """Create or update a Claim node and link it to the document."""
    query = """
    MERGE (c:Claim {claim_id: $claim_id})
    ON CREATE SET
        c.claim_text = $claim_text,
        c.claim_type = $claim_type,
        c.supporting_excerpt = $supporting_excerpt,
        c.extraction_confidence = $extraction_confidence,
        c.review_status = $review_status,
        c.created_at = $now
    ON MATCH SET
        c.last_seen_at = $now
    WITH c
    MATCH (d:Document {id: $document_id})
    MERGE (d)-[:DOCUMENT_CONTAINS_CLAIM]->(c)
    RETURN c.id AS node_id
    """
    result = tx.run(query, claim_id=claim.claim_id,
                    claim_text=claim.claim_text[:2000],
                    claim_type=claim.claim_type.value,
                    supporting_excerpt=claim.supporting_excerpt[:500],
                    extraction_confidence=claim.extraction_confidence,
                    review_status=claim.review_status.value,
                    document_id=document_node_id,
                    now=datetime.now(timezone.utc).isoformat())
    return result.single()["node_id"]


def link_claim_organization(tx, claim_node_id: str, org_node_id: str):
    """Link a Claim to an Organization."""
    query = """
    MATCH (c:Claim {id: $claim_id})
    MATCH (o:Organization {id: $org_id})
    MERGE (c)-[:CLAIM_ABOUT_ORGANIZATION]->(o)
    """
    tx.run(query, claim_id=claim_node_id, org_id=org_node_id)


def link_claim_intervention(tx, claim_node_id: str, inv_node_id: str):
    """Link a Claim to an Intervention."""
    query = """
    MATCH (c:Claim {id: $claim_id})
    MATCH (i:Intervention {id: $inv_id})
    MERGE (c)-[:CLAIM_ABOUT_INTERVENTION]->(i)
    """
    tx.run(query, claim_id=claim_node_id, inv_id=inv_node_id)


def link_claim_problem(tx, claim_node_id: str, problem_node_id: str):
    """Link a Claim to a Problem."""
    query = """
    MATCH (c:Claim {id: $claim_id})
    MATCH (p:Problem {id: $problem_id})
    MERGE (c)-[:CLAIM_ABOUT_PROBLEM]->(p)
    """
    tx.run(query, claim_id=claim_node_id, problem_id=problem_node_id)


def create_evidence_relationship(tx, rel: EvidenceRelationshipRecord):
    """Create a SUPPORTS/CONTRADICTS/etc relationship between two claims."""
    query = """
    MATCH (a:Claim {claim_id: $source_id})
    MATCH (b:Claim {claim_id: $target_id})
    MERGE (a)-[r:CLAIM_RELATIONSHIP {type: $rel_type}]->(b)
    ON CREATE SET
        r.confidence = $confidence,
        r.rationale = $rationale,
        r.created_at = $now
    """
    tx.run(query, source_id=rel.source_claim_id, target_id=rel.target_claim_id,
           rel_type=rel.relationship.value, confidence=rel.confidence,
           rationale=rel.rationale, now=datetime.now(timezone.utc).isoformat())


def upsert_claims_batch(claims: List[EvidenceClaim]) -> Dict[str, Any]:
    """Upsert a batch of claims with all their entity relationships."""
    driver = _get_driver()
    if not driver:
        return {"status": "disabled", "nodes_created": 0, "error": "Neo4j not configured"}

    stats = {"nodes_created": 0, "nodes_updated": 0, "relationships": 0}

    with driver.session() as session:
        for claim in claims:
            try:
                session.execute_write(lambda tx: _upsert_single_claim(tx, claim, stats))
            except Exception as e:
                logger.error(f"Failed to upsert claim {claim.claim_id}: {e}")
                stats.setdefault("errors", []).append(str(e))

    driver.close()
    return stats


def _upsert_single_claim(tx, claim: EvidenceClaim, stats: dict):
    """Upsert one claim and all its linked entities."""
    # Upsert entities
    doc_id = upsert_document(tx, claim.source_url, claim.source_document_id)
    org_id = upsert_organization(tx, claim.organization)
    inv_id = upsert_intervention(tx, claim.intervention)
    prob_id = upsert_problem(tx, claim.problem)

    # Upsert the claim
    claim_node_id = upsert_claim(tx, claim, doc_id)

    # Create relationships
    link_claim_organization(tx, claim_node_id, org_id)
    link_claim_intervention(tx, claim_node_id, inv_id)
    link_claim_problem(tx, claim_node_id, prob_id)

    stats["nodes_created"] += 5  # doc + org + inv + prob + claim
    stats["relationships"] += 4


def get_evidence_relationships(claims: List[EvidenceClaim]) -> List[EvidenceRelationshipRecord]:
    """Compare claims to find SUPPORTS/CONTRADICTS relationships.
    This is a simplified version — full implementation would use embeddings."""
    relationships = []
    for i, a in enumerate(claims):
        for b in claims[i + 1:]:
            # Same intervention, similar outcome direction
            if (a.intervention.name and b.intervention.name and
                a.intervention.name.lower() == b.intervention.name.lower()):
                a_dir = a.outcome.metric.direction.value if a.outcome.metric.direction else ""
                b_dir = b.outcome.metric.direction.value if b.outcome.metric.direction else ""
                if a_dir == b_dir and a_dir != "neutral":
                    relationships.append(EvidenceRelationshipRecord(
                        source_claim_id=a.claim_id,
                        target_claim_id=b.claim_id,
                        relationship=EvidenceRelationship.SUPPORTS,
                        confidence=0.7,
                        rationale=f"Both claim {a_dir} outcomes for {a.intervention.name}",
                    ))
                elif a_dir != b_dir and a_dir != "neutral" and b_dir != "neutral":
                    relationships.append(EvidenceRelationshipRecord(
                        source_claim_id=a.claim_id,
                        target_claim_id=b.claim_id,
                        relationship=EvidenceRelationship.CONTRADICTS,
                        confidence=0.5,
                        rationale=f"Conflicting outcome directions for {a.intervention.name}",
                    ))
    return relationships
