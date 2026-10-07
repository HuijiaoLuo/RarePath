"""Gene profiles: UniProt text cleaned, AlphaFold C-alpha trace extracted, and nothing fetched when offline."""

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

from pipelines import fetch_cluster_expansion as fce
from pipelines import fetch_gene_profiles as fgp
from tests._support import make_tmp, needs_networkx, remove_tmp

FIXTURES = Path(__file__).parent / "fixtures" / "genes"


class GeneProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_tmp()
        processed = self.root / "data" / "processed"
        processed.mkdir(parents=True)
        (processed / "cluster_disease_genes.csv").write_text(
            "disease_id,gene_symbol,association_type,used_for_scoring\n"
            "MONDO:1,GLB1,MENDELIAN,true\nMONDO:2,BRAF,MENDELIAN,false\n", encoding="utf-8")
        (processed / "cluster_gene_pathways.csv").write_text(
            "gene_symbol,uniprot_accession\nGLB1,P16278\n", encoding="utf-8")
        uni = self.root / "data" / "raw" / "uniprot" / "entries"
        af = self.root / "data" / "raw" / "structures" / "alphafold" / "profiles"
        uni.mkdir(parents=True), af.mkdir(parents=True)
        shutil.copy(FIXTURES / "P16278.tsv", uni / "P16278.tsv")
        shutil.copy(FIXTURES / "P16278_prediction.json", af / "P16278_prediction.json")
        shutil.copy(FIXTURES / "AF-P16278-F1-model_v6.pdb", af / "AF-P16278-F1-model_v6.pdb")

    def tearDown(self) -> None:
        remove_tmp(self.root)

    def run_offline(self) -> None:
        with mock.patch.object(fce, "request_bytes", side_effect=AssertionError("network used")), \
             mock.patch.object(sys, "argv", ["x", "--repo-root", str(self.root), "--offline"]):
            self.assertEqual(fgp.main(), 0)

    def test_profile_and_trace_from_cache(self) -> None:
        self.run_offline()
        processed = self.root / "data" / "processed"
        rows = (processed / "gene_profiles.csv").read_text(encoding="utf-8")
        self.assertIn("GLB1,P16278,Beta-galactosidase,4,", rows)          # name without EC/alternative names
        self.assertNotIn("ECO:", rows)
        self.assertNotIn("PubMed", rows)
        self.assertNotIn("BRAF", rows)                                    # not a scoring gene
        structures = json.loads((processed / "gene_structures.json").read_text(encoding="utf-8"))
        s = structures["GLB1"]
        self.assertEqual(s["plddt"], [96, 88, 62, 35])                    # B-factor column, one per residue
        self.assertEqual(len(s["xyz"]), 12)
        self.assertEqual(s["seq"], "MMMM")                                # one letter per residue, from the PDB
        self.assertTrue(all(abs(sum(s["xyz"][i::3])) <= 2 for i in range(3)))  # centred (up to rounding)
        self.assertEqual(s["xyz"][3] - s["xyz"][0], 38)                   # 3.8 Å stored as tenths

    def test_clean_comment(self) -> None:
        text = fgp.clean_comment("FUNCTION: Binds X (PubMed:3) {ECO:0000269|PubMed:1}.; FUNCTION: Also Y (Probable).", "FUNCTION")
        self.assertEqual(text, "Binds X. Also Y.")

    def test_canonical_isoform_only(self) -> None:
        text = fgp.clean_comment("FUNCTION: [Isoform 1]: Cleaves galactose. {ECO:1}.; FUNCTION: [Isoform 2]: Binds elastin.", "FUNCTION")
        self.assertEqual(text, "Cleaves galactose.")

    def test_clean_location(self) -> None:
        loc = fgp.clean_location("SUBCELLULAR LOCATION: Cell membrane {ECO:1}; Lipid-anchor; Cytoplasmic side. Golgi apparatus. "
                                 "Cytoplasm, cytoskeleton, cilium basal body. Note=Shuttles. {ECO:2}.; SUBCELLULAR LOCATION: [Isoform 2]: Nucleus.")
        self.assertEqual(loc, "Cell membrane; Golgi apparatus; Cilium basal body")


if __name__ == "__main__":
    unittest.main()
