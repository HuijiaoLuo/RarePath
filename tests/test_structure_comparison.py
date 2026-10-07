"""Offline checks for the bounded sequence-guided structure comparison."""

import unittest
from pathlib import Path

from pipelines.compute_protein_similarity import smith_waterman_blosum62_affine_with_positions
from pipelines.compute_structure_comparison import (
    parse_ca_trace,
    rigid_superposition,
    validate_trace_against_sequence,
)


class StructureComparisonTests(unittest.TestCase):
    def test_traceback_positions_match_the_returned_alignment(self) -> None:
        _score, aligned_a, aligned_b, positions = smith_waterman_blosum62_affine_with_positions(
            "AAAACAAC", "AAACACAC"
        )
        self.assertEqual((aligned_a, aligned_b), ("AAACA-AC", "AAACACAC"))
        self.assertEqual(len(positions), len(aligned_a))
        for column, (source_index, target_index) in enumerate(positions):
            self.assertEqual(source_index is None, aligned_a[column] == "-")
            self.assertEqual(target_index is None, aligned_b[column] == "-")

    def test_rigid_superposition_recovers_a_known_rotation_and_translation(self) -> None:
        source = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
        # A 90-degree rotation about z, then translation (3, -2, 5).
        target = [(3.0, -2.0, 5.0), (3.0, -1.0, 5.0), (2.0, -2.0, 5.0), (3.0, -2.0, 6.0)]
        rmsd, rotation, translation = rigid_superposition(source, target)
        self.assertLess(rmsd, 1e-9)
        transformed = [
            tuple(
                sum(rotation[row][column] * point[column] for column in range(3))
                + translation[row]
                for row in range(3)
            )
            for point in source
        ]
        for expected, observed in zip(target, transformed):
            for expected_value, observed_value in zip(expected, observed):
                self.assertAlmostEqual(expected_value, observed_value, places=8)

    def test_pdb_ca_parser_reads_residue_and_plddt(self) -> None:
        path = Path(__file__).parent / "fixtures" / "one_residue.pdb"
        trace = parse_ca_trace(path)
        self.assertEqual(trace[0].residue, "A")
        self.assertEqual(trace[0].coordinate, (1.25, 2.5, 3.75))
        self.assertEqual(trace[0].plddt, 92.5)
        validate_trace_against_sequence(trace, "A", path)


if __name__ == "__main__":
    unittest.main()
