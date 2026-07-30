"""Ingestion pipeline orchestrator.

Coordinates the full flow: document parsing → LLM extraction → 
entity normalization → Neo4j upsert.
"""

import json
import logging
import uuid
from typing import Optional, List
from pathlib import Path
from datetime import datetime, timezone

from compass_collector.ingest import (
    InputDocument, EvidenceClaim, ExtractionResult, IngestionRun,
    ReviewStatus, EvidenceRelationshipRecord,
)
from compass_collector.ingest.parser import parse_document, extract_source_locator
from compass_collector.ingest.extractor import extract_claims
from compass_collector.ingest.graph import upsert_claims_batch, get_evidence_relationships

logger = logging.getLogger(__name__)


def ingest_document(
    path_or_url: str,
    api_key: str,
    persist: bool = False,
) -> IngestionRun:
    """Ingest a single document: parse → extract → (optional) graph upsert."""
    run = IngestionRun(
        run_id=str(uuid.uuid4()),
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    # Step 1: Parse
    logger.info(f"Parsing: {path_or_url}")
    document = parse_document(path_or_url)
    if not document:
        run.status = "failed"
        run.errors.append(f"Failed to parse: {path_or_url}")
        run.completed_at = datetime.now(timezone.utc).isoformat()
        return run

    run.documents_downloaded = 1
    run.documents_parsed = 1

    # Step 2: Extract claims
    logger.info(f"Extracting claims from {document.document_id}")
    result = extract_claims(document, api_key)
    run.claims_created = len(result.claims)
    run.total_tokens = result.token_usage
    run.total_cost = result.cost
    run.extraction_failures = len(result.errors)

    if result.errors:
        for e in result.errors:
            logger.warning(f"Extraction issue: {e}")

    if not result.claims:
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc).isoformat()
        return run

    # Step 3: Add source locators
    for claim in result.claims:
        claim.source_locator = extract_source_locator(document.sections, claim.claim_text)

    # Step 4: Detect duplicates and contradictions (in-memory)
    relationships = get_evidence_relationships(result.claims)
    run.contradictions_detected = sum(
        1 for r in relationships if r.relationship.value == "CONTRADICTS"
    )

    # Step 5: Auto-approval based on confidence
    for claim in result.claims:
        if claim.evidence_quality.overall_score() >= 0.7 and claim.extraction_confidence >= 0.7:
            claim.review_status = ReviewStatus.AUTO_APPROVED
        else:
            claim.review_status = ReviewStatus.PENDING_REVIEW

    # Step 6: Optional Neo4j persistence
    if persist:
        graph_stats = upsert_claims_batch(result.claims)
        run.graph_nodes_created = graph_stats.get("nodes_created", 0)
        run.graph_nodes_updated = graph_stats.get("nodes_updated", 0)

    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc).isoformat()

    # Print summary
    print(f"\n{'='*60}")
    print(f"Ingestion complete: {run.run_id[:8]}")
    print(f"{'='*60}")
    print(f"  Document:     {document.title[:60]}")
    print(f"  Sections:     {len(document.sections)}")
    print(f"  Claims:       {len(result.claims)}")
    print(f"  Auto-approved:{sum(1 for c in result.claims if c.review_status == ReviewStatus.AUTO_APPROVED)}")
    print(f"  Pending:      {sum(1 for c in result.claims if c.review_status == ReviewStatus.PENDING_REVIEW)}")
    print(f"  Contradictions:{run.contradictions_detected}")
    print(f"  Tokens:       {run.total_tokens}")
    print(f"  Cost:         ${run.total_cost:.6f}")
    if persist:
        print(f"  Graph nodes:  {run.graph_nodes_created}")
    print(f"{'='*60}\n")

    return run
