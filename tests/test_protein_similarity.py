"""Focused checks for the reproducible protein-alignment baselines."""

import unittest

from pipelines.compute_protein_similarity import (
    BLOSUM62,
    karlin_altschul,
    alignment_metrics,
    smith_waterman_blosum62_affine,
    smith_waterman_linear,
)


class ProteinSimilarityTests(unittest.TestCase):
    def test_embedded_blosum62_reference_scores(self) -> None:
        self.assertEqual(BLOSUM62["A"]["A"], 4)
        self.assertEqual(BLOSUM62["W"]["W"], 11)
        self.assertEqual(BLOSUM62["A"]["R"], -1)

    def test_affine_alignment_of_an_exact_sequence(self) -> None:
        score, aligned_a, aligned_b = smith_waterman_blosum62_affine("AR", "AR")
        self.assertEqual(score, 9)
        self.assertEqual((aligned_a, aligned_b), ("AR", "AR"))

    def test_affine_traceback_can_extend_a_gap(self) -> None:
        score, aligned_a, aligned_b = smith_waterman_blosum62_affine(
            "AAAACAAC", "AAACACAC"
        )
        self.assertEqual(score, 26)
        self.assertEqual((aligned_a, aligned_b), ("AAACA-AC", "AAACACAC"))

    def test_linear_alignment_restarts_for_a_local_hit(self) -> None:
        score, aligned_a, aligned_b = smith_waterman_linear("ACGT", "AGT")
        self.assertEqual(score, 4)
        self.assertEqual((aligned_a, aligned_b), ("GT", "GT"))

    def test_coverage_counts_residues_across_a_gap(self) -> None:
        metrics = alignment_metrics("AC", "ABC", 0, "A-C", "ABC")
        self.assertEqual(metrics["aligned_residues"], 2)
        self.assertEqual(metrics["query_aligned_residues"], 2)
        self.assertEqual(metrics["target_aligned_residues"], 3)
        self.assertEqual(metrics["query_coverage_pct"], 100.0)
        self.assertEqual(metrics["target_coverage_pct"], 100.0)


class SignificanceTests(unittest.TestCase):
    def test_karlin_altschul_matches_blast_formula(self) -> None:
        # E = K m n exp(-lambda S) with gapped BLOSUM62 11/1 parameters.
        evalue, bits = karlin_altschul(40, 677, 529)
        self.assertAlmostEqual(evalue, 0.041 * 677 * 529 * 2.718281828459045 ** (-0.267 * 40), places=6)
        self.assertAlmostEqual(bits, 20.0, places=1)

    def test_higher_scores_are_more_significant(self) -> None:
        self.assertLess(karlin_altschul(200, 500, 500)[0], karlin_altschul(50, 500, 500)[0])


if __name__ == "__main__":
    unittest.main()
