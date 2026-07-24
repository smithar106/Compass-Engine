import json
import os
import csv
from pathlib import Path
from datetime import datetime

from compass_collector.database import get_session, init_db
from compass_collector.models.document import Document
from compass_collector.models.intervention import InterventionRecord
from compass_collector.extraction_llm.relevance_filter import RelevanceFilter
from compass_collector.extraction_llm.llm_extractor import LLMExtractor
from compass_collector.extraction_llm.validator import ExtractionValidator


class ExtractionOrchestrator:

    def __init__(self, output_dir: str = None):
        self.filter = RelevanceFilter()
        self.validator = ExtractionValidator()
        self.extractor = None
        self.output_dir = Path(output_dir) if output_dir else Path.home() / "compass-collector" / "data" / "extraction"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def set_api_key(self, api_key: str):
        self.extractor = LLMExtractor(api_key=api_key)

    def load_documents(self, max_docs: int = None) -> list[dict]:
        init_db()
        session = get_session()
        try:
            docs = session.query(Document).filter(Document.url.startswith("http")).order_by(Document.id).all()
            if max_docs:
                docs = docs[:max_docs]

            result = []
            for doc in docs:
                result.append({
                    "id": doc.id,
                    "title": doc.title or "",
                    "url": doc.url or "",
                    "text": doc.cleaned_text or "",
                    "source_type": "web",
                })

            return result
        finally:
            session.close()

    def run_relevance_filter(self, documents: list[dict]) -> list[dict]:
        results = self.filter.classify_all(documents)
        with open(self.output_dir / "document_relevance.jsonl", "w") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")

        counts = {"high_relevance": 0, "possible_relevance": 0, "not_relevant": 0}
        for r in results:
            counts[r["classification"]] += 1
        return results, counts

    def run_extraction(self, documents: list[dict], max_text_length: int = 8000,
                       batch_size: int = 5) -> list[dict]:
        if not self.extractor:
            raise ValueError("API key not set. Call set_api_key() first.")

        results = self.extractor.extract_batch(documents, batch_size, max_text_length)

        with open(self.output_dir / "extraction_attempts.jsonl", "a") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")
                f.flush()

        return results

    def validate_extractions(self, extractions: list[dict]) -> dict:
        validated = self.validator.validate_batch(extractions)
        accepted = []
        quarantined = []
        rejected = []

        for v in validated:
            if v["validation"] == "accept":
                accepted.append(v)
            elif v["validation"] == "quarantine":
                quarantined.append(v)
            else:
                rejected.append(v)

        with open(self.output_dir / "accepted_interventions.jsonl", "w") as f:
            for v in accepted:
                f.write(json.dumps(v) + "\n")

        with open(self.output_dir / "quarantined_interventions.jsonl", "w") as f:
            for v in quarantined:
                f.write(json.dumps(v) + "\n")

        self._export_metrics(accepted, extractions)
        self._export_source_passages(accepted, extractions)
        self._export_quality_flags(accepted, quarantined, rejected)

        return {"accepted": accepted, "quarantined": quarantined, "rejected": rejected,
                "total_processed": len(extractions)}

    def _export_metrics(self, accepted: list, extractions: list):
        metrics = []
        extraction_map = {e["document_id"]: e for e in extractions}
        for v in accepted:
            doc_id = v["document_id"]
            e = extraction_map.get(doc_id, {})
            for outcome in e.get("extraction", {}).get("outcomes", []):
                metrics.append({
                    "document_id": doc_id,
                    "title": v["title"],
                    "metric_name": outcome.get("metric_name"),
                    "baseline_value": outcome.get("baseline_value"),
                    "post_value": outcome.get("post_value"),
                    "absolute_change": outcome.get("absolute_change"),
                    "percentage_change": outcome.get("percentage_change"),
                    "unit": outcome.get("unit"),
                    "value_type": outcome.get("value_type"),
                    "source_passage": outcome.get("source_passage", ""),
                })

        with open(self.output_dir / "metrics.jsonl", "w") as f:
            for m in metrics:
                f.write(json.dumps(m) + "\n")

    def _export_source_passages(self, accepted: list, extractions: list):
        passages = []
        extraction_map = {e["document_id"]: e for e in extractions}
        for v in accepted:
            doc_id = v["document_id"]
            e = extraction_map.get(doc_id, {})
            for sp in e.get("extraction", {}).get("source_passages", []):
                passages.append({
                    "document_id": doc_id,
                    "title": v["title"],
                    "field": sp.get("field", ""),
                    "passage": sp.get("passage", ""),
                })

        with open(self.output_dir / "source_passages.jsonl", "w") as f:
            for p in passages:
                f.write(json.dumps(p) + "\n")

    def _export_quality_flags(self, accepted: list, quarantined: list, rejected: list):
        flags = []
        for v in accepted:
            flags.append({
                "document_id": v["document_id"], "flag": "accepted",
                "details": v.get("reason", "")
            })
        for v in quarantined:
            flags.append({
                "document_id": v["document_id"], "flag": "quarantined",
                "details": v.get("reason", "")
            })
        for v in rejected:
            flags.append({
                "document_id": v["document_id"], "flag": "rejected",
                "details": v.get("reason", "")
            })

        with open(self.output_dir / "quality_flags.jsonl", "w") as f:
            for fl in flags:
                f.write(json.dumps(fl) + "\n")

    def generate_extraction_report(self, counts: dict, validation_results: dict,
                                   extractions: list, documents_count: int) -> str:
        total_tokens = (self.extractor.stats["total_input_tokens"] +
                        self.extractor.stats["total_output_tokens"])
        total_cost = self.extractor.stats["total_cost"]

        report = f"""# Extraction Run Report

Generated: {datetime.utcnow().isoformat()}

## Document Volume

- Total documents loaded: {documents_count}
- High relevance: {counts.get('high_relevance', 0)}
- Possible relevance: {counts.get('possible_relevance', 0)}
- Not relevant: {counts.get('not_relevant', 0)}
- Sent for extraction: {len(extractions)}

## Extraction Results

- Accepted: {len(validation_results.get('accepted', []))}
- Quarantined: {len(validation_results.get('quarantined', []))}
- Rejected: {len(validation_results.get('rejected', []))}
- Total processed: {validation_results.get('total_processed', 0)}

## API Usage

- Total API calls: {self.extractor.stats['total_calls']}
- Input tokens: {self.extractor.stats['total_input_tokens']:,}
- Output tokens: {self.extractor.stats['total_output_tokens']:,}
- Total tokens: {total_tokens:,}
- Total cost: ${total_cost:.4f}
- Errors: {self.extractor.stats['errors']}

## Acceptance Rate

- Acceptance rate: {(len(validation_results.get('accepted', [])) / max(len(extractions), 1)) * 100:.1f}%
- Cost per accepted record: ${(total_cost / max(len(validation_results.get('accepted', [])), 1)):.4f}
"""
        path = self.output_dir / "extraction_run_report.md"
        path.write_text(report)
        return report

    def export_manual_review_sample(self, accepted: list, extractions: list, n: int = 20):
        sample = accepted[:n]
        rows = []
        extraction_map = {e["document_id"]: e for e in extractions}
        for v in sample:
            doc_id = v["document_id"]
            e = extraction_map.get(doc_id, {})
            extraction = e.get("extraction", {})
            rows.append({
                "document_id": doc_id,
                "title": v["title"],
                "has_org": v.get("details", {}).get("viability", {}).get("has_org", ""),
                "has_problem": v.get("details", {}).get("viability", {}).get("has_problem", ""),
                "has_intervention": v.get("details", {}).get("viability", {}).get("has_intervention", ""),
                "has_outcomes": v.get("details", {}).get("viability", {}).get("has_outcome", ""),
                "outcome_count": len(extraction.get("outcomes", [])),
                "result_status": extraction.get("result_status", ""),
                "intervention_families": "; ".join(extraction.get("intervention_families", [])),
                "is_vendor_reported": extraction.get("is_vendor_reported", ""),
                "implementation_cost": extraction.get("implementation_cost", {}).get("value", "") if extraction.get("implementation_cost") else "",
                "implementation_duration": extraction.get("implementation_duration", {}).get("value", "") if extraction.get("implementation_duration") else "",
                "reviewer_notes": "",
                "review_decision": "",
            })

        path = self.output_dir / "manual_review_sample.csv"
        with open(path, "w", newline="") as f:
            if rows:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

    def full_run(self, max_docs: int = None) -> dict:
        documents = self.load_documents(max_docs)
        print(f"Loaded {len(documents)} documents")

        print("Running relevance filter...")
        relevance_results, counts = self.run_relevance_filter(documents)
        print(f"  High: {counts['high_relevance']}, Possible: {counts['possible_relevance']}, Not: {counts['not_relevant']}")

        relevant_ids = {r["record_id"] for r in relevance_results
                        if r["classification"] in ("high_relevance", "possible_relevance")}
        relevant_docs = [d for d in documents if d["id"] in relevant_ids]
        total = len(relevant_docs)
        print(f"  Sending {total} documents to extraction")

        if not self.extractor:
            raise ValueError("API key not set. Call set_api_key() first.")

        print("Running LLM extraction...")
        import time
        t0 = time.time()
        extractions = []
        for i, doc in enumerate(relevant_docs):
            text = doc.get("text", doc.get("cleaned_text", ""))
            if not text and doc.get("title"):
                text = doc["title"]
            if not text or len(text.strip()) < 100:
                extractions.append({
                    "document_id": doc.get("id"),
                    "title": doc.get("title", "")[:100],
                    "url": doc.get("url", ""),
                    "extraction": {"has_intervention": False,
                                   "extraction_notes": "Insufficient source text (<100 chars)"}
                })
                continue
            result = self.extractor.extract(text, doc.get("title"), doc.get("url"))
            e_result = {
                "document_id": doc.get("id"),
                "title": doc.get("title", "")[:100],
                "url": doc.get("url", ""),
                "extraction": result,
            }
            extractions.append(e_result)
            with open(self.output_dir / "extraction_attempts.jsonl", "a") as f:
                f.write(json.dumps(e_result) + "\n")
                f.flush()
            if (i + 1) % 25 == 0:
                elapsed = time.time() - t0
                pct = (i + 1) / total * 100
                rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
                print(f"  {i+1}/{total} ({pct:.0f}%) — {rate:.0f} docs/min — cost so far: ${self.extractor.stats['total_cost']:.4f}")

        print(f"  Completed {len(extractions)} extractions")

        print("Validating extractions...")
        validation = self.validate_extractions(extractions)
        print(f"  Accepted: {len(validation['accepted'])}, Quarantined: {len(validation['quarantined'])}, Rejected: {len(validation['rejected'])}")

        report = self.generate_extraction_report(counts, validation, extractions, len(documents))
        self.export_manual_review_sample(validation.get("accepted", []), extractions)

        cost_report = f"""Document ID,Input Tokens,Output Tokens,Cost
"""
        extraction_map = {e["document_id"]: e for e in extractions}
        for v in validation.get("accepted", []) + validation.get("quarantined", []):
            e = extraction_map.get(v["document_id"], {})
            meta = e.get("extraction", {}).get("_meta", {})
            cost_report += f"{v['document_id']},{meta.get('input_tokens', 0)},{meta.get('output_tokens', 0)},{meta.get('cost', 0)}\n"
        (self.output_dir / "extraction_cost_report.csv").write_text(cost_report)

        return {
            "documents_loaded": len(documents),
            "relevance": counts,
            "extractions": len(extractions),
            "validation": {k: len(v) if isinstance(v, list) else v for k, v in validation.items()},
            "cost": self.extractor.stats["total_cost"] if self.extractor else 0,
            "report": report,
        }
