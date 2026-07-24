import json
import csv
from pathlib import Path
from datetime import datetime

from compass_collector.config.settings import EXPORTS_DIR
from compass_collector.models.document import Document
from compass_collector.models.intervention import (
    InterventionRecord, MetricRecord, PassageRecord, QualityFlag, DuplicateRelationship
)
from compass_collector.database import get_session


class ExportEngine:

    def __init__(self, export_dir: str = None):
        self.export_dir = Path(export_dir) if export_dir else EXPORTS_DIR
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export_jsonl(self, table: str, records: list, filename: str = None):
        if not filename:
            filename = f"{table}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        path = self.export_dir / filename
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(self._serialize(r)) + "\n")
        print(f"Exported {len(records)} records to {path}")

    def export_csv(self, table: str, records: list, filename: str = None):
        if not filename:
            filename = f"{table}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = self.export_dir / filename
        if not records:
            print(f"No records to export for {table}")
            return

        rows = [self._serialize(r) for r in records]
        fieldnames = set()
        for row in rows:
            fieldnames.update(row.keys())

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(fieldnames))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Exported {len(records)} records to {path}")

    def export_all(self, formats: list[str] = None):
        if formats is None:
            formats = ["jsonl"]

        session = get_session()
        try:
            exports = {
                "sources": session.query(Document).all(),
                "interventions": session.query(InterventionRecord).all(),
                "metrics": session.query(MetricRecord).all(),
                "passages": session.query(PassageRecord).all(),
                "quality_flags": session.query(QualityFlag).all(),
                "relationships": session.query(DuplicateRelationship).all(),
            }

            for fmt in formats:
                for table, records in exports.items():
                    fn = f"{table}.{fmt}"
                    if fmt == "jsonl":
                        self.export_jsonl(table, records, fn)
                    elif fmt == "csv":
                        self.export_csv(table, records, fn)

            return exports
        finally:
            session.close()

    def _serialize(self, obj) -> dict:
        if hasattr(obj, "__table__"):
            d = {}
            for col in obj.__table__.columns:
                val = getattr(obj, col.key)
                if isinstance(val, datetime):
                    val = val.isoformat()
                d[col.key] = val
            return d
        if isinstance(obj, dict):
            return obj
        return {"value": str(obj)}
