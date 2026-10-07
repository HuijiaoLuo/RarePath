"""Checks for AlphaFold metadata selection without network access."""

import unittest

from pipelines.fetch_alphafold_structures import model_download, select_model


class AlphaFoldStructureFetchTests(unittest.TestCase):
    def test_selects_the_newest_matching_accession(self) -> None:
        payload = [
            {
                "uniprotAccession": "P16278",
                "entryId": "AF-P16278-F1",
                "latestVersion": 4,
                "modelCreatedDate": "2023-01-01",
                "pdbUrl": "https://example.org/v4.pdb",
            },
            {
                "uniprotAccession": "P16278",
                "entryId": "AF-P16278-F1",
                "latestVersion": 5,
                "modelCreatedDate": "2024-01-01",
                "pdbUrl": "https://example.org/v5.pdb",
            },
        ]
        selected = select_model("P16278", payload)
        self.assertEqual(selected["latestVersion"], 5)

    def test_prefers_requested_pdb_and_falls_back_to_cif(self) -> None:
        self.assertEqual(
            model_download({"pdbUrl": "https://example.org/model.pdb"}, "pdb"),
            ("pdb", "https://example.org/model.pdb"),
        )
        self.assertEqual(
            model_download({"cifUrl": "https://example.org/model.cif"}, "pdb"),
            ("cif", "https://example.org/model.cif"),
        )


if __name__ == "__main__":
    unittest.main()
