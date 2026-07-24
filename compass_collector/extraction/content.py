import re
import uuid
from datetime import datetime
from pathlib import Path

from compass_collector.models.document import Document
from compass_collector.models.intervention import (
    InterventionRecord, MetricRecord, PassageRecord, QualityFlag
)
from compass_collector.database import get_session


class ContentExtractor:

    def extract_text(self, doc: Document) -> str:
        if doc.clean_text_path:
            path = Path(doc.clean_text_path)
            if path.exists():
                return path.read_text()
        if doc.raw_file_path:
            path = Path(doc.raw_file_path)
            if path.exists() and doc.document_type == "html":
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(path.read_bytes(), "html.parser")
                return soup.get_text(separator="\n", strip=True)
        return ""

    def extract_metadata(self, doc: Document) -> dict:
        text = self.extract_text(doc)
        meta = {
            "word_count": len(text.split()),
            "has_numbers": bool(re.search(r"\d+", text)),
            "has_percentages": bool(re.search(r"\d+%", text)),
            "has_currency": bool(re.search(r"[$£€¥]", text)),
            "estimated_reading_time_minutes": max(1, len(text.split()) // 250),
        }
        return meta

    def detect_tables(self, doc: Document) -> list[dict]:
        tables = []
        if doc.raw_file_path and doc.document_type == "html":
            from bs4 import BeautifulSoup
            path = Path(doc.raw_file_path)
            if path.exists():
                soup = BeautifulSoup(path.read_bytes(), "html.parser")
                for i, table_tag in enumerate(soup.find_all("table")):
                    rows = []
                    for tr in table_tag.find_all("tr"):
                        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                        rows.append(cells)
                    caption = table_tag.find("caption")
                    tables.append({
                        "table_index": i,
                        "caption": caption.get_text(strip=True) if caption else "",
                        "rows": rows,
                        "row_count": len(rows)
                    })
        return tables


class InterventionDetector:

    def __init__(self):
        self.intervention_keywords = {
            "process_redesign": ["redesign", "reengineer", "restructure", "reorganization"],
            "workflow_simplification": ["simplif", "streamline", "lean", "eliminate step"],
            "existing_software_optimization": ["optimize", "upgrade", "migrate", "configuration"],
            "new_software_implementation": ["implemented", "deployed", "rolled out", "new system"],
            "rules_based_automation": ["rules", "if-then", "workflow automation", "decision tree"],
            "robotic_process_automation": ["rpa", "robot", "bot", "automation", "software robot"],
            "predictive_ai": ["predictive", "forecast", "ml model", "prediction"],
            "generative_ai": ["generative", "llm", "gpt", "large language model", "gen ai"],
            "ai_assisted_work": ["ai assist", "copilot", "ai-powered", "intelligent assist"],
            "autonomous_ai": ["autonomous", "self-driving", "fully automated", "unattended"],
            "human_in_the_loop_ai": ["human in the loop", "human review", "supervised ai", "human oversight"],
            "staffing_increases": ["hired", "staff", "headcount", "team expand", "recruit"],
            "staffing_reallocation": ["reallocate", "reassign", "shift", "redeploy"],
            "outsourcing": ["outsource", "offshore", "third party", "managed service"],
            "managed_services": ["managed service", "msa", "sla-based"],
            "training": ["training", "upskill", "workshop", "certification", "learn"],
            "governance": ["governance", "policy", "compliance", "oversight", "steering"],
            "organizational_restructuring": ["restructure", "reorg", "new department", "center of excellence"],
            "policy_changes": ["policy change", "new policy", "regulation", "compliance update"],
            "better_measurement_reporting": ["dashboard", "reporting", "analytics", "kpi", "measurement"],
            "no_intervention": ["no change", "status quo", "no intervention", "do nothing"],
            "further_investigation": ["pilot", "proof of concept", "feasibility", "assessment"],
            "hybrid_combination": ["hybrid", "combination", "integrated approach", "multi-pronged"]
        }

        self.outcome_keywords = {
            "successful": ["success", "improved", "exceeded", "achieved", "positive"],
                "failed": ["failed", "unsuccessful", "did not meet", "worse"],
            "partial": ["partial", "mixed", "some improvement", "limited"],
            "neutral": ["no change", "no impact", "similar", "comparable"],
            "abandoned": ["abandoned", "cancelled", "terminated", "stopped", "scrapped"]
        }

    def detect(self, doc: Document, text: str = None) -> list[InterventionRecord]:
        if text is None:
            from compass_collector.extraction.content import ContentExtractor
            text = ContentExtractor().extract_text(doc)

        text_lower = text.lower().replace("-", " ").replace("–", " ")
        interventions = []

        detected_families = []
        for family, keywords in self.intervention_keywords.items():
            for kw in keywords:
                if kw in text_lower:
                    detected_families.append(family)
                    break

        if not detected_families:
            return interventions

        result_status = "unknown"
        for status, keywords in self.outcome_keywords.items():
            for kw in keywords:
                if kw in text_lower:
                    result_status = status
                    break

        session = get_session()
        try:
            record = InterventionRecord(
                id=str(uuid.uuid4()),
                source_id=doc.source_registry_id or "",
                document_id=doc.id,
                intervention_title=doc.title,
                intervention_families=detected_families,
                intervention_description=text[:2000],
                result_status=result_status,
                extractor="content_extractor_v1"
            )
            session.add(record)
            session.flush()

            quality_flags = self._generate_quality_flags(text)
            for flag in quality_flags:
                qf = QualityFlag(
                    id=str(uuid.uuid4()),
                    intervention_id=record.id,
                    flag_name=flag
                )
                session.add(qf)

            session.commit()
            interventions.append(record)
            return interventions
        finally:
            session.close()

    def _generate_quality_flags(self, text: str) -> list[str]:
        flags = []
        if "no baseline" in text.lower() or not re.search(r"baseline|before|pre-implementation", text.lower()):
            flags.append("no_baseline")
        if not re.search(r"\d+%", text):
            flags.append("no_percentage_change")
        if re.search(r"projected|expected|estimated to", text.lower()):
            flags.append("projected_rather_than_observed")
        if re.search(r"marketing|leader in|industry-first", text.lower()):
            flags.append("marketing_claim")
        if not re.search(r"sample|n=|participants|organization", text.lower()):
            flags.append("no_sample_size")
        if re.search(r"vendor|partner|sponsored", text.lower()):
            flags.append("vendor_reported")
        return flags


class MetricExtractor:

    METRIC_PATTERNS = {
        "cost_savings": [
            r"([$][\d,]+(?:\.\d+)?)\s*(?:million|billion|k)?\s+(?:\w+\s+){0,3}(?:savings|saved)",
            r"sav(?:ed|ings)\s*(?:of\s*)?[$]?([\d,]+(?:\.\d+)?)\s*(?:million|billion|k)?",
        ],
        "hours_saved": [
            r"(\d[\d,]*)\s*(?:hours?|hrs?)\s*(?:saved|reduced|freed)",
            r"sav(?:ed|ings)\s*(?:of\s*)?(\d[\d,]*)\s*(?:hours?|hrs?)",
        ],
        "percentage_change": [
            r"(\d+\.?\d*)\s*%\s*(?:improvement|reduction|increase|decrease)",
            r"(?:improved|reduced|increased|decreased)\s*(?:by\s*)?(\d+\.?\d*)\s*%",
        ],
        "cycle_time": [
            r"(?:cycle|response|resolution|processing)\s*(?:time\s*)?(?:reduced|decreased|improved)\s*(?:from\s*)?([\d.]+\s*\w+)\s*(?:to\s*)?([\d.]+\s*\w+)?",
        ],
        "revenue": [
            r"([$][\d,]+(?:\.\d+)?)\s*(?:million|billion|k)?\s+(?:\w+\s+){0,3}(?:revenue|income)",
            r"revenue\s*(?:increased|grew|rose)\s*(?:by\s*)?(\d+\.?\d*)\s*%",
        ],
        "customer_satisfaction": [
            r"(?:csat|nps|customer satisfaction)\s*(?:score\s*)?(?:improved|increased|rose)\s*(?:from\s*)?([\d.]+)\s*(?:to\s*)?([\d.]+)?",
        ],
        "error_rate": [
            r"(?:error|mistake|defect)\s*(?:rate\s*)?(?:reduced|decreased|dropped)\s*(?:from\s*)?([\d.]+%?)\s*(?:to\s*)?([\d.]+%?)?",
        ],
        "headcount": [
            r"(\d[\d,]*)\s*(?:employees?|people|staff|headcount|fte)",
            r"(?:team|staff|workforce)\s*(?:of\s*)?(\d[\d,]*)",
        ],
    }

    def extract(self, doc: Document, text: str = None,
                intervention_id: str = None) -> list[MetricRecord]:
        if text is None:
            from compass_collector.extraction.content import ContentExtractor
            text = ContentExtractor().extract_text(doc)

        metrics = []
        for category, patterns in self.METRIC_PATTERNS.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    reported = match.group(0).strip()
                    metric = MetricRecord(
                        id=str(uuid.uuid4()),
                        intervention_id=intervention_id or "",
                        source_id=doc.source_registry_id or "",
                        metric_name=category,
                        metric_category=category,
                        reported_text=reported,
                        value_type="reported"
                    )

                    if category == "percentage_change":
                        val = match.group(1).replace(",", "")
                        metric.percentage_change = float(val)

                    if category in ("cost_savings", "revenue"):
                        val_str = match.group(1).replace(",", "").replace("$", "")
                        try:
                            metric.absolute_change = float(val_str)
                        except ValueError:
                            pass

                    if category == "hours_saved":
                        val_str = match.group(1).replace(",", "")
                        try:
                            metric.absolute_change = float(val_str)
                            metric.unit = "hours"
                        except ValueError:
                            pass

                    metrics.append(metric)
                    break

        session = get_session()
        try:
            for m in metrics:
                session.add(m)
            session.commit()
        finally:
            session.close()

        return metrics
