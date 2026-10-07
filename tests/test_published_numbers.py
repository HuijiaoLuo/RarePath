"""The numbers written in the README, case study and docs must match the committed data.

If a pipeline run changes a count (for example a ClinVar refresh), this test fails until the
public text is updated, so the portfolio never quotes a number the data no longer supports.
"""

import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
MANIFESTS = ROOT / "data" / "manifests"


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def n(value: int) -> str:
    return f"{value:,}"


class PublishedNumberTests(unittest.TestCase):
    def assert_says(self, rel: str, phrase: str) -> None:
        self.assertIn(phrase, text(rel), f"{rel} should say “{phrase}” (from the committed data)")

    @unittest.skipUnless((PROCESSED / "cluster_diseases.csv").exists(), "no cluster data")
    def test_disease_count(self):
        with (PROCESSED / "cluster_diseases.csv").open(encoding="utf-8", newline="") as stream:
            count = sum(1 for _ in csv.DictReader(stream))
        for rel in ("README.md", "demo/index.html", "docs/CLUSTER_EXPANSION.md"):
            self.assert_says(rel, f"{count} diseases")

    @unittest.skipUnless((PROCESSED / "disease_similarity.csv").exists(), "no similarity data")
    def test_check_count(self):
        from pipelines.check_cluster_benchmark import run
        count = len(run(PROCESSED))
        self.assert_says("README.md", f"{count} checks")
        self.assert_says("demo/index.html", f"{count} checks")
        self.assert_says("docs/CLUSTER_EXPANSION.md", f"It has {count} checks")

    @unittest.skipUnless((PROCESSED / "disease_similarity.csv").exists(), "no similarity data")
    def test_lookalike_pairs(self):
        with (PROCESSED / "disease_similarity.csv").open(encoding="utf-8", newline="") as stream:
            pairs = sorted(" vs ".join(sorted((r["source_label"], r["target_label"])))
                           for r in csv.DictReader(stream) if r["relation_class"] == "phenotype_lookalike_different_mechanism")
        self.assertEqual(pairs, ["Bardet-Biedl syndrome 1 vs Prader-Willi syndrome", "Canavan disease vs Krabbe disease"],
                         "the README, case study and method notes name exactly these look-alike pairs")
        self.assert_says("README.md", "only 2 pairs are labelled look-alikes")
        self.assert_says("demo/index.html", "only two pairs are labelled look-alikes")
        for rel in ("README.md", "demo/index.html", "docs/CLUSTER_EXPANSION.md", "CHANGELOG.md"):
            self.assertNotIn("three counterexamples", text(rel).replace("\n", " "), rel)

    @unittest.skipUnless((MANIFESTS / "gene_profiles_v0.1.json").exists(), "no gene profiles")
    def test_gene_and_structure_counts(self):
        m = json.loads((MANIFESTS / "gene_profiles_v0.1.json").read_text(encoding="utf-8"))
        self.assert_says("demo/index.html", f"{m['profiles']} genes · {m['structures']} structures")

    @unittest.skipUnless((MANIFESTS / "gene_variants_v0.1.json").exists(), "no ClinVar variants")
    def test_variant_counts(self):
        m = json.loads((MANIFESTS / "gene_variants_v0.1.json").read_text(encoding="utf-8"))
        self.assertEqual(m["problems"], [], "the ClinVar step reported problems; re-run it before publishing")
        pc = m["pooled_confidence"]
        headline = f"{n(m['variants'])} missense records at {n(pc['variant_positions'])} positions in {m['genes']} proteins"
        self.assert_says("docs/GENE_AND_VARIANT_LAYER.md", headline)
        self.assert_says("demo/index.html", f"across {n(m['variants'])} ClinVar variants in {m['genes']} proteins")
        self.assert_says("docs/GENE_AND_VARIANT_LAYER.md", f"**{n(pc['variant_positions_very_high'])}**")
        self.assert_says("docs/GENE_AND_VARIANT_LAYER.md", f"**{pc['observed_over_expected']:.2f}**")

    @unittest.skipUnless((PROCESSED / "structure_comparison.csv").exists(), "no protein comparisons")
    def test_protein_comparison_numbers(self):
        from graph.export_graph_json import protein_comparisons
        rows = protein_comparisons(ROOT)
        fitted = [c for c in rows if c["structure"] and c["structure"]["status"] == "computed"]
        self.assertEqual([c["genes"] for c in fitted], [["HEXA", "HEXB"]], "only HEXA-HEXB passes the mapping gate")
        st, q = fitted[0]["structure"], fitted[0]["sequence"]
        self.assertTrue(q["significant"])
        doc = "docs/PROTEIN_SIMILARITY_PORTFOLIO.md"
        self.assert_says(doc, f"{st['high_confidence_ca_pairs']} high-confidence C-alpha pairs")
        self.assert_says(doc, f"{st['ca_rmsd_angstrom']} Å C-alpha RMSD")
        self.assert_says(doc, f"{q['identity_pct']}% identity")
        # every other pair is "not evaluated", never a low score
        for c in rows:
            if c not in fitted:
                self.assertEqual(c["structure"]["ca_rmsd_angstrom"], "", c["genes"])
                self.assertFalse(c["sequence"]["significant"], c["genes"])

    def test_test_count(self):
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
        self.assert_says("README.md", f"# {suite.countTestCases()} tests")


if __name__ == "__main__":
    unittest.main()
