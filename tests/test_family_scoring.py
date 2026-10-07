"""Scoring v0.3: families are scored against their own genes and pairs, and curated genes are respected."""

import unittest

from pipelines.compute_disease_similarity import compute
from tests._support import make_tmp, needs_networkx, remove_tmp

TERMS = [
    {"hpo_id": "HP:1", "hpo_label": "root", "parents": "", "information_content": "0.1"},
    {"hpo_id": "HP:A", "hpo_label": "sign A", "parents": "HP:1", "information_content": "3.0"},
    {"hpo_id": "HP:B", "hpo_label": "sign B", "parents": "HP:1", "information_content": "3.0"},
    {"hpo_id": "HP:C", "hpo_label": "sign C", "parents": "HP:1", "information_content": "3.0"},
    {"hpo_id": "HP:D", "hpo_label": "sign D", "parents": "HP:1", "information_content": "3.0"},
]


def disease(i, fam):
    return {"disease_id": i, "label": i, "family": fam, "panel_role": ""}


def gene(d, g, used="true"):
    return {"disease_id": d, "gene_symbol": g, "association_type": "MENDELIAN", "used_for_scoring": used}


def pw(g, *ids):
    return [{"gene_symbol": g, "pathway_id": p, "pathway_label": p, "is_in_disease": "false"} for p in ids]


def ann(d, *terms):
    return [{"disease_id": d, "hpo_id": t} for t in terms]


# Family L: four diseases. L1 and L2 share a specific pathway (P-spec); all share a broad one (P-broad).
L = [disease(f"L{i}", "lyso") for i in range(1, 5)]
L_GENES = [gene(f"L{i}", f"g{i}") for i in range(1, 5)]
L_PATHS = pw("g1", "P-broad", "P-spec") + pw("g2", "P-broad", "P-spec") + pw("g3", "P-broad", "P-x3") + pw("g4", "P-broad", "P-x4")
L_ANN = ann("L1", "HP:A", "HP:B") + ann("L2", "HP:A", "HP:B") + ann("L3", "HP:C") + ann("L4", "HP:D")

# Family R: three diseases with unrelated genes and pathways; R1 also lists an extra non-curated gene.
R = [disease(f"R{i}", "ras") for i in range(1, 4)]
R_GENES = [gene("R1", "r1"), gene("R1", "g1", used="false"), gene("R2", "r2"), gene("R3", "r3")]
R_PATHS = pw("r1", "Q1") + pw("r2", "Q1", "Q2") + pw("r3", "Q3")
R_ANN = ann("R1", "HP:C", "HP:D") + ann("R2", "HP:C") + ann("R3", "HP:A")


def scored(diseases, genes, paths, anns):
    rows, clusters, stats = compute(diseases, anns, TERMS, genes, paths)
    return {frozenset((r["source_id"], r["target_id"])): r for r in rows}, clusters, stats


@needs_networkx
class FamilyScoringTests(unittest.TestCase):
    def test_adding_a_family_leaves_existing_scores_unchanged(self):
        alone, _, _ = scored(L, L_GENES, L_PATHS, L_ANN)
        both, _, _ = scored(L + R, L_GENES + R_GENES, L_PATHS + R_PATHS, L_ANN + R_ANN)
        for key, row in alone.items():
            for field in ("relation_class", "mechanism_score", "phenotype_percentile"):
                self.assertEqual(row[field], both[key][field], (sorted(key), field))

    def test_genes_not_used_for_scoring_are_ignored(self):
        both, clusters, _ = scored(L + R, L_GENES + R_GENES, L_PATHS + R_PATHS, L_ANN + R_ANN)
        self.assertEqual(both[frozenset(("L1", "R1"))]["shared_genes"], "")
        self.assertEqual({c["disease_id"]: c["genes"] for c in clusters}["R1"], "r1")

    def test_pairs_carry_their_comparison_set(self):
        both, _, stats = scored(L + R, L_GENES + R_GENES, L_PATHS + R_PATHS, L_ANN + R_ANN)
        self.assertEqual(both[frozenset(("L1", "L2"))]["comparison_set"], "lyso")
        self.assertEqual(both[frozenset(("L1", "R3"))]["comparison_set"], "cross-family")
        self.assertEqual(set(stats["phenotype_high_cutoff_simgic"]), {"lyso", "ras", "cross-family"})

    def test_specific_shared_pathway_makes_a_mechanism_link(self):
        both, _, _ = scored(L + R, L_GENES + R_GENES, L_PATHS + R_PATHS, L_ANN + R_ANN)
        self.assertGreaterEqual(float(both[frozenset(("L1", "L2"))]["mechanism_score"]), 0.25)
        # Only the broad pathway (all four family genes) is shared: capped below the "no specific process" line.
        self.assertLess(float(both[frozenset(("L3", "L4"))]["mechanism_score"]), 0.10)

    def test_shared_mechanism_class_is_a_weak_link_not_a_lookalike(self):
        # X1 and X2 share distinctive symptoms but no gene or pathway: a look-alike, unless they share a class.
        diseases = [disease("X1", "f"), disease("X2", "f"), disease("X3", "f"), disease("X4", "f")]
        genes = [gene("X1", "x1"), gene("X2", "x2"), gene("X3", "x3"), gene("X4", "x4")]
        paths = pw("x1", "A") + pw("x2", "B") + pw("x3", "C") + pw("x4", "D")
        anns = ann("X1", "HP:A", "HP:B") + ann("X2", "HP:A", "HP:B") + ann("X3", "HP:C") + ann("X4", "HP:D")
        without, _, _ = compute(diseases, anns, TERMS, genes, paths)
        cls = [{"child_id": i, "parent_id": "MONDO:CLASS", "parent_label": "test class", "grouping": "class"}
               for i in ("X1", "X2")]
        with_class, clusters, _ = compute(diseases, anns, TERMS, genes, paths, cls)
        key = lambda rows: {frozenset((r["source_id"], r["target_id"])): r for r in rows}
        before, after = key(without)[frozenset(("X1", "X2"))], key(with_class)[frozenset(("X1", "X2"))]
        self.assertEqual(before["relation_class"], "phenotype_lookalike_different_mechanism")
        self.assertEqual(after["relation_class"], "phenotype_neighbor_weak_mechanism")
        self.assertEqual(after["shared_mondo_class"], "MONDO:CLASS|test class")
        # A class alone never pulls two diseases into one community.
        c = {r["disease_id"]: r["cluster_combined"] for r in clusters}
        self.assertNotEqual(c["X1"], c["X2"])


if __name__ == "__main__":
    unittest.main()
