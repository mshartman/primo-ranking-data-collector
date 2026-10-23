from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import sys
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PACKAGE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


collector = load_module("collector_for_test", "collect_queries.py")
aggregator = load_module("aggregator_for_test", "aggregate_runs.py")


class CollectionAndAggregationTests(unittest.TestCase):
    def test_flatten_doc_preserves_score_and_context(self) -> None:
        doc = {
            "context": "L",
            "@id": "https://example.test/doc/synthetic-001",
            "pnx": {
                "control": {
                    "recordid": ["synthetic-001"],
                    "sourcerecordid": ["synthetic-001"],
                    "score": ["123.5"],
                },
                "display": {"title": ["Synthetic Book"], "type": ["book"]},
                "sort": {"creationdate": ["2024"]},
            },
        }
        row = collector.flatten_doc(
            doc,
            run_id="SYNTHETIC_RUN",
            config_id="SYNTHETIC_CONFIG",
            captured_at="2030-01-01T12:00:00+00:00",
            profile_name="local",
            profile={"tab": "LOCAL_TAB", "scope": "LOCAL_SCOPE"},
            query={
                "query_id": "Q001",
                "query": "synthetic sample topic",
                "raw_query": "",
                "query_source": "constructed",
                "query_intent": "topical",
                "variant_group": "",
                "field": "any",
                "precision": "contains",
                "test_focus": "topical",
                "expected_record_id": "synthetic-001",
                "dataset_partition": "development",
                "notes": "",
            },
            rank=1,
            offset=0,
            page_rank=1,
        )
        self.assertEqual(row["record_key"], "L:synthetic-001")
        self.assertEqual(row["score"], 123.5)
        self.assertEqual(row["context"], "L")
        self.assertEqual(row["publication_year"], "2024")

    def test_aggregate_builds_inventory_and_record_index(self) -> None:
        runs_root = Path(__file__).parent / "fixtures" / "runs"
        output_root = PACKAGE_DIR / "test_outputs"
        output = output_root / "aggregate"
        if output_root.exists():
            shutil.rmtree(output_root)
        output_root.mkdir()
        try:
            manifest = aggregator.aggregate(
                aggregator.discover_runs(runs_root), output
            )
            self.assertEqual(manifest["source_run_count"], 2)
            self.assertEqual(manifest["record_observation_count"], 4)
            self.assertEqual(manifest["distinct_record_count"], 3)

            with (output / "records.csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                records = {row["record_key"]: row for row in csv.DictReader(handle)}
            self.assertEqual(records["L:synthetic-001"]["observation_count"], "2")
            self.assertEqual(records["L:synthetic-001"]["run_count"], "2")

            configurations = [
                json.loads(line)
                for line in (output / "configurations.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual({item["config_id"] for item in configurations}, {
                "CONFIG_A",
                "CONFIG_B",
            })
        finally:
            shutil.rmtree(output_root)


if __name__ == "__main__":
    unittest.main()

