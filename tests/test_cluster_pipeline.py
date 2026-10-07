"""End-to-end check of the cluster layer with format-accurate fixtures and no network.

fetch_cluster_expansion -> compute_disease_similarity -> sync_cluster_to_graph -> load_neo4j.validate
"""

import csv
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

from pipelines import compute_disease_similarity as sim
from pipelines import fetch_cluster_expansion as fetch
from pipelines import sync_cluster_to_graph as sync
from tests._support import make_tmp, needs_networkx, remove_tmp

FIXTURES = Path(__file__).parent / "fixtures" / "cluster"
REPO = Path(__file__).resolve().parents[1]

TEST_PANEL = [
    {"omim": "230500", "name_check": "gm1", "role": "start", "why": "GM1 type 1"},
    {"omim": "253010", "name_check": "mucopolysaccharidosis", "role": "same_gene_contrast", "why": "Morquio B"},
    {"omim": "272800", "name_check": "tay-sachs", "role": "positive_neighbor", "why": "Tay-Sachs"},
    {"omim": "271900", "name_check": "canavan", "role": "phenocopy_counterexample", "why": "Canavan"},
    {"omim": "999999", "name_check": "missing", "role": "x", "why": "not in HPO"},
]
REACTOME = {
    "P16278": [{"stId": "R-HSA-1", "displayName": "Glycosphingolipid catabolism", "isInDisease": False},
               {"stId": "R-HSA-2", "displayName": "Keratan sulfate degradation", "isInDisease": False},
               {"stId": "R-HSA-9", "displayName": "Defective GLB1 causes MPS IVB", "isInDisease": True}],
    "P06865": [{"stId": "R-HSA-1", "displayName": "Glycosphingolipid catabolism", "isInDisease": False}],
    "Q00000": [{"stId": "R-HSA-4", "displayName": "Aspartate metabolism", "isInDisease": False}],
}
ACCESSIONS = {"GLB1": "P16278", "HEXA": "P06865", "ASPA": "Q00000"}


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


@needs_networkx
class ClusterPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        for sub in ("data/processed", "data/manifests", "graph"):
            (self.tmp / sub).mkdir(parents=True)
        for name in ("nodes.csv", "edges.csv"):
            shutil.copy(REPO / "graph" / name, self.tmp / "graph" / name)

    def tearDown(self) -> None:
        remove_tmp(self.tmp)

    def run_fetch(self) -> None:
        hpo_paths = {name: FIXTURES / name for name in fetch.HPO_ASSETS}
        mondo = json.loads((FIXTURES / "mondo.json").read_text())
        with mock.patch.object(fetch, "PANEL", TEST_PANEL), \
             mock.patch.object(fetch, "hpo_release", return_value=("v2026-09-01", hpo_paths, {"phenotype.hpoa": "u"})), \
             mock.patch.object(fetch, "load_mondo", return_value=(mondo, "v-test", FIXTURES / "mondo.json")), \
             mock.patch.object(fetch, "request_bytes", return_value=(b"95", {})), \
             mock.patch.object(fetch, "uniprot_accession", side_effect=lambda s, *a: (ACCESSIONS[s], s, "2026_03")), \
             mock.patch.object(fetch, "reactome_pathways", side_effect=lambda acc, *a: REACTOME[acc]), \
             mock.patch.object(fetch.time, "sleep"), \
             mock.patch.object(sys, "argv", ["x", "--repo-root", str(self.tmp)]):
            self.assertEqual(fetch.main(), 0)

    def test_full_chain(self) -> None:
        self.run_fetch()
        processed = self.tmp / "data" / "processed"
        diseases = {r["hpo_disease_id"]: r for r in read(processed / "cluster_diseases.csv")}
        self.assertEqual(set(diseases), {"OMIM:230500", "OMIM:253010", "OMIM:272800", "OMIM:271900"})
        self.assertEqual(diseases["OMIM:272800"]["disease_id"], "MONDO:0010100")  # xref fallback

        annotations = read(processed / "cluster_disease_phenotypes.csv")
        gm1_terms = {a["hpo_id"] for a in annotations if a["hpo_disease_id"] == "OMIM:230500"}
        self.assertIn("HP:0001250", gm1_terms)        # alt_id HP:0002279 resolved
        self.assertNotIn("HP:0002655", gm1_terms)     # NOT-qualified row dropped
        self.assertNotIn("HP:0000007", gm1_terms)     # inheritance aspect dropped

        terms = {t["hpo_id"]: t for t in read(processed / "cluster_hpo_terms.csv")}
        self.assertGreater(float(terms["HP:0010729"]["information_content"]),
                           float(terms["HP:0001250"]["information_content"]))  # specific > broad

        hierarchy = read(processed / "cluster_disease_hierarchy.csv")
        self.assertIn(("MONDO:0009260", "MONDO:0018149"), {(h["child_id"], h["parent_id"]) for h in hierarchy})

        with mock.patch.object(sys, "argv", ["x", "--repo-root", str(self.tmp)]):
            self.assertEqual(sim.main(), 0)
        pairs = {frozenset((r["source_id"], r["target_id"])): r for r in read(processed / "disease_similarity.csv")}
        gm1, morquio, tay, canavan = "MONDO:0009260", "MONDO:0010012", "MONDO:0010100", "MONDO:0010079"
        self.assertEqual(pairs[frozenset((gm1, morquio))]["relation_class"], "same_gene_different_presentation")
        self.assertEqual(pairs[frozenset((gm1, tay))]["shared_pathways"], "R-HSA-1|Glycosphingolipid catabolism")
        self.assertEqual(pairs[frozenset((tay, canavan))]["mechanism_score"], "0.0000")
        self.assertNotIn("R-HSA-9", json.dumps(pairs[frozenset((gm1, morquio))]))  # disease pathways excluded
        self.assertEqual(pairs[frozenset((tay, canavan))]["relation_class"], "phenotype_lookalike_different_mechanism")
        clusters = {r["disease_id"]: r for r in read(processed / "disease_clusters.csv")}
        # The look-alike groups with Tay-Sachs on symptoms alone, but not in the combined clustering.
        self.assertEqual(clusters[tay]["cluster_phenotype"], clusters[canavan]["cluster_phenotype"])
        self.assertNotEqual(clusters[tay]["cluster_combined"], clusters[canavan]["cluster_combined"])
        self.assertEqual(clusters[gm1]["cluster_combined"], clusters[tay]["cluster_combined"])

        with mock.patch.object(sys, "argv", ["x", "--repo-root", str(self.tmp)]):
            self.assertEqual(sync.main(), 0)
            self.assertEqual(sync.main(), 0)  # idempotent

        from graph.load_neo4j import read_csv, validate

        nodes = read_csv(self.tmp / "graph" / "nodes.csv")
        edges = read_csv(self.tmp / "graph" / "edges.csv")
        validate(nodes, edges)
        ids = [e["edge_id"] for e in edges]
        self.assertEqual(len(ids), len(set(ids)))
        kinds = {n["node_type"] for n in nodes}
        self.assertTrue({"Phenotype", "Pathway", "Disease", "Gene"} <= kinds)
        types = {e["edge_type"] for e in edges}
        self.assertIn("SHARES_CAUSAL_GENE", types)
        self.assertIn("HAS_PHENOTYPE", types)
        # The original seed and structure edges survive untouched.
        self.assertIn("EDGE:SIMSTRUCT-P06865-P07686", ids)
        self.assertIn("EDGE:REL-01", ids)
        # Tay-Sachs -> GM2 already existed as a curated seed edge: not duplicated.
        isa = [e for e in edges if e["source_id"] == tay and e["edge_type"] == "IS_A"]
        self.assertEqual(len(isa), 1)
        # Pre-existing Tay-Sachs node gets cluster membership without being replaced.
        tay_node = next(n for n in nodes if n["node_id"] == tay)
        self.assertEqual(tay_node["status"], next(
            r for r in read(REPO / "graph" / "nodes.csv") if r["node_id"] == tay)["status"])
        self.assertIn("cluster", json.loads(tay_node["properties_json"]))


if __name__ == "__main__":
    unittest.main()
