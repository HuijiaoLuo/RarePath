"""Focused checks for converting eligible structure evidence into graph rows."""

import unittest

from pipelines.sync_structure_evidence_to_graph import EDGE_FIELDS, synchronize


def computed_row() -> dict[str, str]:
    return {
        "structure_comparison_id": "SIMSTRUCT:test:UNIPROT_P06865__UNIPROT_P07686",
        "source_protein_id": "UNIPROT:P06865",
        "target_protein_id": "UNIPROT:P07686",
        "source_gene_symbol": "HEXA",
        "target_gene_symbol": "HEXB",
        "source_model_url": "https://example.org/P06865.pdb",
        "target_model_url": "https://example.org/P07686.pdb",
        "method": "example_method",
        "ca_rmsd_angstrom": "0.865",
        "high_confidence_ca_pairs": "483",
        "plddt_cutoff": "70.0",
        "minimum_mapped_ca_coverage_pct": "89.928",
        "aligned_residue_pairs": "500",
        "source_model_version": "6",
        "target_model_version": "6",
        "status": "computed",
    }


class StructureGraphSyncTests(unittest.TestCase):
    def test_computed_row_creates_a_provenanced_similarity_edge(self) -> None:
        nodes = [
            {"node_id": "UNIPROT:P06865", "node_type": "Protein"},
            {"node_id": "UNIPROT:P07686", "node_type": "Protein"},
        ]
        updated_nodes, updated_edges, generated = synchronize(nodes, [], [computed_row()])
        self.assertEqual(len(generated), 1)
        self.assertEqual(updated_nodes[-1]["node_id"], "EVIDENCE:SIMSTRUCT_P06865_P07686")
        edge = updated_edges[-1]
        self.assertEqual(edge["edge_type"], "SIMILAR_TO")
        self.assertEqual(edge["assertion_level"], "inferred")
        self.assertEqual(edge["confidence"], "medium")
        self.assertEqual(edge["primary_score"], "0.865")
        self.assertTrue(all(field in edge for field in EDGE_FIELDS))

    def test_not_evaluated_row_creates_no_negative_edge(self) -> None:
        row = computed_row()
        row["status"] = "not_evaluated_insufficient_sequence_mapping"
        nodes = [
            {"node_id": "UNIPROT:P06865", "node_type": "Protein"},
            {"node_id": "UNIPROT:P07686", "node_type": "Protein"},
        ]
        updated_nodes, updated_edges, generated = synchronize(nodes, [], [row])
        self.assertEqual(updated_nodes, nodes)
        self.assertEqual(updated_edges, [])
        self.assertEqual(generated, [])


if __name__ == "__main__":
    unittest.main()
