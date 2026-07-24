import unittest
import json
import tempfile
from pathlib import Path

from compass_collector.export.formats import ExportEngine
from compass_collector.models.intervention import InterventionRecord, MetricRecord, QualityFlag


class TestExport(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.exporter = ExportEngine(str(self.tmpdir))

    def test_export_jsonl(self):
        records = [
            InterventionRecord(
                id="test-1",
                source_id="src-1",
                intervention_title="Test Intervention",
                result_status="successful"
            )
        ]
        self.exporter.export_jsonl("interventions", records, "test.jsonl")
        path = self.tmpdir / "test.jsonl"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["id"], "test-1")
        self.assertEqual(data["result_status"], "successful")

    def test_export_csv(self):
        records = [
            MetricRecord(
                id="m-1",
                metric_name="cost_savings",
                absolute_change=500000.0,
                unit="USD"
            )
        ]
        self.exporter.export_csv("metrics", records, "test.csv")
        path = self.tmpdir / "test.csv"
        self.assertTrue(path.exists())
        content = path.read_text()
        self.assertIn("metric_name", content)
        self.assertIn("cost_savings", content)

    def test_export_empty(self):
        self.exporter.export_csv("empty", [], "empty.csv")
        path = self.tmpdir / "empty.csv"
        self.assertFalse(path.exists())

    def test_export_all_formats(self):
        records = [
            InterventionRecord(
                id="test-2",
                source_id="src-2",
                intervention_title="Test",
                result_status="failed"
            )
        ]
        self.exporter.export_jsonl("interventions", records, "test.jsonl")
        self.exporter.export_csv("interventions", records, "test.csv")
        self.assertTrue((self.tmpdir / "test.jsonl").exists())
        self.assertTrue((self.tmpdir / "test.csv").exists())


if __name__ == "__main__":
    unittest.main()
