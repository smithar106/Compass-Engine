import uuid
import hashlib
from pathlib import Path
from collections import defaultdict

from compass_collector.models.document import Document
from compass_collector.models.intervention import DuplicateRelationship, InterventionRecord
from compass_collector.database import get_session


class DeduplicationEngine:

    def deduplicate_documents(self) -> list[DuplicateRelationship]:
        session = get_session()
        try:
            docs = session.query(Document).filter_by(crawl_status="success").all()
            rels = []

            by_hash = defaultdict(list)
            for doc in docs:
                by_hash[doc.content_hash].append(doc)

            for h, group in by_hash.items():
                if len(group) > 1:
                    for i in range(1, len(group)):
                        rel = DuplicateRelationship(
                            id=str(uuid.uuid4()),
                            source_a_id=group[0].id,
                            source_b_id=group[i].id,
                            relationship_type="exact_duplicate",
                            notes=f"Content hash match: {h[:16]}"
                        )
                        session.add(rel)
                        rels.append(rel)

            session.commit()
            return rels
        finally:
            session.close()

    def detect_near_duplicates(self, threshold: float = 0.85) -> list[DuplicateRelationship]:
        session = get_session()
        try:
            docs = session.query(Document).filter(
                Document.crawl_status == "success",
                Document.clean_text_path != "",
                Document.clean_text_path.isnot(None)
            ).all()

            rels = []
            texts = []
            for doc in docs:
                try:
                    text = Path(doc.clean_text_path).read_text()[:5000]
                    texts.append((doc.id, text))
                except Exception:
                    continue

            for i in range(len(texts)):
                for j in range(i + 1, len(texts)):
                    sim = self._similarity(texts[i][1], texts[j][1])
                    if sim >= threshold:
                        rel = DuplicateRelationship(
                            id=str(uuid.uuid4()),
                            source_a_id=texts[i][0],
                            source_b_id=texts[j][0],
                            relationship_type="near_duplicate",
                            confidence=sim,
                            notes=f"Text similarity: {sim:.2%}"
                        )
                        session.add(rel)
                        rels.append(rel)

            session.commit()
            return rels
        finally:
            session.close()

    def detect_same_case_study(self) -> list[DuplicateRelationship]:
        session = get_session()
        try:
            interventions = session.query(InterventionRecord).all()
            rels = []

            org_groups = defaultdict(list)
            for inv in interventions:
                if inv.organization_name:
                    org_groups[inv.organization_name.lower()].append(inv)

            for org, group in org_groups.items():
                if len(group) > 1:
                    for i in range(1, len(group)):
                        rel = DuplicateRelationship(
                            id=str(uuid.uuid4()),
                            source_a_id=group[0].id,
                            source_b_id=group[i].id,
                            relationship_type="same_underlying_case_study",
                            notes=f"Same organization: {org}"
                        )
                        session.add(rel)
                        rels.append(rel)

            session.commit()
            return rels
        finally:
            session.close()

    def _similarity(self, a: str, b: str) -> float:
        a_words = set(a.lower().split())
        b_words = set(b.lower().split())
        if not a_words or not b_words:
            return 0.0
        intersection = a_words & b_words
        return len(intersection) / max(len(a_words), len(b_words))
