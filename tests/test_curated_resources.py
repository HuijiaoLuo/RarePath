"""Curated studies and patient groups become sourced graph links; unknown diseases are skipped, never guessed."""

import csv
import unittest
from pathlib import Path

from pipelines.sync_curated_resources import build

CURATED = Path(__file__).resolve().parents[1] / "data" / "curated" / "family_resources.csv"


class CuratedResourceTests(unittest.TestCase):
    def test_study_and_org_links(self):
        rows = [
            {"resource_id": "NCT:NCT0001", "kind": "Study", "label": "A study", "short_name": "AS", "url": "https://x",
             "disease_ids": "OMIM:100; MONDO:9", "checked_on": "2026-10-04", "checked_via": "https://y", "claim": "c"},
            {"resource_id": "ORG:A", "kind": "Organization", "label": "Org A", "short_name": "A", "url": "https://a",
             "disease_ids": "OMIM:999", "checked_on": "2026-10-04", "checked_via": "", "claim": ""},
        ]
        nodes, edges, problems = build(rows, {"OMIM:100": "MONDO:1"}, {"MONDO:1", "MONDO:9"})
        self.assertEqual({(e["source_id"], e["edge_type"], e["target_id"]) for e in edges},
                         {("NCT:NCT0001", "STUDIES", "MONDO:1"), ("NCT:NCT0001", "STUDIES", "MONDO:9")})
        self.assertEqual(problems, ["ORG:A: disease OMIM:999 is not in the graph"])
        self.assertTrue(all(e["evidence_id"].startswith("CUR-") for e in edges))
        study = next(n for n in nodes if n["node_id"] == "NCT:NCT0001")
        self.assertIn('"study"', study["properties_json"])

    def test_committed_file_is_complete(self):
        with CURATED.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            self.assertTrue(row["url"].startswith("https://"), row["resource_id"])
            self.assertTrue(row["checked_on"] and row["checked_via"].startswith("https://"), row["resource_id"])
            self.assertTrue(row["disease_ids"].strip(), row["resource_id"])
            if row["kind"] == "Study":
                self.assertRegex(row["resource_id"], r"^NCT:NCT\d{8}$")
                self.assertTrue(row["overall_status"], row["resource_id"])


if __name__ == "__main__":
    unittest.main()
