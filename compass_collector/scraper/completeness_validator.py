from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord, MetricRecord


class CompletenessValidator:

    REQUIRED_FIELDS = {
        "organization_context": ["organization_name", "organization_industry"],
        "baseline": ["has_baseline"],
        "intervention_details": ["intervention_title", "intervention_description"],
        "implementation_timeline": ["intervention_implementation_time_value", "intervention_implementation_time_unit"],
        "measured_outcomes": ["has_post_measurement"],
        "source_linked_evidence": ["document_id"],
    }

    def validate_all(self) -> dict:
        session = get_session()
        try:
            total = session.query(InterventionRecord).count()
            complete = 0
            results = []

            for inv in session.query(InterventionRecord).all():
                check = self.validate_record(inv, session)
                results.append(check)
                if check["completeness_score"] >= 0.9:
                    complete += 1

            pct = (complete / total * 100) if total > 0 else 0
            return {
                "total_records": total,
                "complete_records": complete,
                "completeness_percentage": round(pct, 1),
                "target_90_percent": "YES" if pct >= 90 else "NO",
                "results": results
            }
        finally:
            session.close()

    def validate_record(self, inv: InterventionRecord, session) -> dict:
        checks = {}
        for dimension, fields in self.REQUIRED_FIELDS.items():
            filled = 0
            for f in fields:
                val = getattr(inv, f, None)
                if val is not None and val != "" and val != []:
                    filled += 1
            checks[dimension] = {
                "filled": filled,
                "total": len(fields),
                "complete": filled == len(fields)
            }

        metrics_count = session.query(MetricRecord).filter_by(intervention_id=inv.id).count()
        checks["measured_outcomes"]["has_metrics"] = metrics_count > 0
        checks["measured_outcomes"]["metrics_count"] = metrics_count

        total_dims = len(checks)
        complete_dims = sum(1 for c in checks.values() if c["complete"])
        score = complete_dims / total_dims if total_dims > 0 else 0

        return {
            "record_id": inv.id,
            "title": inv.intervention_title,
            "checks": checks,
            "completeness_score": round(score, 2),
            "is_complete": score >= 0.9,
            "missing_dimensions": [k for k, v in checks.items() if not v["complete"]]
        }

    def report(self) -> str:
        data = self.validate_all()
        lines = [
            f"=== Completeness Report ===",
            f"Total records: {data['total_records']}",
            f"Complete records (≥90%): {data['complete_records']}",
            f"Completeness: {data['completeness_percentage']}%",
            f"Target 90%: {data['target_90_percent']}",
            "",
            "Missing dimensions across all records:",
        ]
        dim_counts = {}
        for r in data["results"]:
            for dim in r["missing_dimensions"]:
                dim_counts[dim] = dim_counts.get(dim, 0) + 1
        for dim, count in sorted(dim_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {dim}: {count} records missing")
        return "\n".join(lines)
