"""ClinVar variants: only qualifying missense changes, and only where the model's sequence agrees."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from pipelines import fetch_cluster_expansion as fce
from pipelines import fetch_clinvar_variants as fcv
from tests._support import make_tmp, needs_networkx, remove_tmp


def record(uid, name, cls="Pathogenic", consequence="missense variant", genes=("GLB1",), vtype="single nucleotide variant"):
    return {"uid": uid, "title": name, "genes": [{"symbol": g} for g in genes],
            "molecular_consequence_list": [consequence],
            "germline_classification": {"description": cls, "review_status": "criteria provided, single submitter",
                                        "last_evaluated": "2024/06/26 00:00", "trait_set": [{"trait_name": "GM1 gangliosidosis"}]},
            "variation_set": [{"variation_name": name, "variant_type": vtype}]}


class ClinVarVariantTests(unittest.TestCase):
    def test_parse_record_filters(self):
        ok = fcv.parse_record(record("1", "NM_000404.4(GLB1):c.400G>A (p.Gly2Arg)"), "GLB1")
        self.assertEqual((ok["position"], ok["ref"], ok["alt"], ok["protein_change"]), (2, "G", "R", "Gly2Arg"))
        self.assertEqual(ok["last_evaluated"], "2024-06-26")
        for bad in (record("2", "NM_1.1(GLB1):c.1A>G (p.Gly2Arg)", cls="Uncertain significance"),
                    record("3", "NM_1.1(GLB1):c.1A>G (p.Gly2Ter)", consequence="nonsense"),
                    record("4", "NM_9.1(CCR4):c.1A>G (p.Gly2Arg)", genes=("GLB1", "CCR4")),
                    record("5", "NM_1.1(GLB1):c.1A>G (p.Gly2=)"),
                    record("6", "NM_1.1(GLB1):c.1A>G (p.Gly2Arg)", vtype="Deletion")):
            self.assertIsNone(fcv.parse_record(bad, "GLB1"), bad["uid"])

    def test_overlapping_gene_is_allowed_when_named_on_this_gene(self):
        rec = record("7", "NM_000169.3(GLA):c.101A>C (p.Asn34Thr)", genes=("GLA", "RPL36A-HNRNPH2"))
        self.assertEqual(fcv.parse_record(rec, "GLA")["position"], 34)

    def test_numbering_offset(self):
        seq = "XX" + "MGLWAKRDE" * 3                      # UniProt numbering = transcript numbering - 2... reversed here
        rows = [{"position": i + 1 - 2, "ref": seq[i]} for i in range(2, 14)]
        self.assertEqual(fcv.numbering_offset(rows, seq), 2)
        self.assertEqual(fcv.numbering_offset(rows[:5], seq), 0)          # too few variants to infer a shift
        same = [{"position": i + 1, "ref": seq[i]} for i in range(12)]
        self.assertEqual(fcv.numbering_offset(same, seq), 0)

    def test_reference_must_match_model(self):
        rows = [fcv.parse_record(record("1", "NM_1.1(GLB1):c.1A>G (p.Gly2Arg)"), "GLB1"), fcv.parse_record(record("2", "NM_1.1(GLB1):c.1A>G (p.Ala3Val)"), "GLB1")]
        kept, rejected = fcv.place_on_structure(rows, "MGL", [50, 95, 70])
        self.assertEqual([r["clinvar_id"] for r in kept], ["1"])
        self.assertEqual((kept[0]["plddt"], rejected), (95, 1))

    def test_end_to_end_offline(self):
        root = make_tmp()
        try:
            (root / "data" / "processed").mkdir(parents=True)
            (root / "data" / "processed" / "gene_structures.json").write_text(json.dumps(
                {"GLB1": {"accession": "P16278", "seq": "MGLW", "plddt": [40, 95, 92, 60], "first_residue": 1}}))
            cache = root / "data" / "raw" / "clinvar" / "variants"
            cache.mkdir(parents=True)
            recs = {"1": record("1", "NM_1.1(GLB1):c.1A>G (p.Gly2Arg)"), "2": record("2", "NM_1.1(GLB1):c.1A>G (p.Gly2Glu)", cls="Likely pathogenic"),
                    "3": record("3", "NM_1.1(GLB1):c.1A>G (p.Trp4Cys)"), "4": record("4", "NM_1.1(GLB1):c.1A>G (p.Pro4Leu)")}
            (cache / "GLB1_search.json").write_text(json.dumps({"esearchresult": {"count": "4", "idlist": list(recs)}}))
            (cache / "GLB1_summary_1.json").write_text(json.dumps({"result": {"uids": list(recs), **recs}}))
            with mock.patch.object(fce, "request_bytes", side_effect=AssertionError("network used")), \
                 mock.patch.object(sys, "argv", ["x", "--repo-root", str(root), "--offline"]):
                self.assertEqual(fcv.main(), 0)
            per_gene = json.loads((root / "data" / "processed" / "gene_variants.json").read_text())["GLB1"]
            self.assertEqual(per_gene["positions"], [[2, "Gly2Arg / Gly2Glu", 2, "GM1 gangliosidosis"], [4, "Trp4Cys", 1, "GM1 gangliosidosis"]])
            self.assertEqual(per_gene["rejected_sequence_mismatch"], 1)          # Pro4Leu: residue 4 is W
            self.assertEqual((per_gene["variant_positions_very_high"], per_gene["residues_very_high"]), (1, 2))
            manifest = json.loads((root / "data" / "manifests" / "gene_variants_v0.1.json").read_text())
            self.assertEqual(manifest["pooled_confidence"]["expected_variant_positions_very_high_if_random"], 1.0)
            self.assertEqual(manifest["pooled_confidence"]["observed_over_expected"], 1.0)
        finally:
            remove_tmp(root)


    def test_oversized_batch_is_split_and_errors_are_not_cached(self):
        root = make_tmp()
        try:
            (root / "data" / "processed").mkdir(parents=True)
            (root / "data" / "processed" / "gene_structures.json").write_text(json.dumps(
                {"GLB1": {"accession": "P16278", "seq": "MG" + "A" * 20, "plddt": [95] * 22, "first_residue": 1}}))
            cache = root / "data" / "raw" / "clinvar" / "variants"
            cache.mkdir(parents=True)
            recs = {str(i): record(str(i), "NM_1.1(GLB1):c.1A>G (p.Gly2Arg)") for i in range(12)}
            ids = list(recs)
            (cache / "GLB1_search.json").write_text(json.dumps({"esearchresult": {"count": "12", "idlist": ids}}))
            (cache / "GLB1_summary_1.json").write_text(json.dumps({"eutilsresult": {"ERROR": "Input XML size is too big"}}))
            for tag, part in (("1a", ids[:6]), ("1b", ids[6:])):
                (cache / f"GLB1_summary_{tag}.json").write_text(json.dumps({"result": {"uids": part, **{u: recs[u] for u in part}}}))
            with mock.patch.object(fce, "request_bytes", side_effect=AssertionError("network used")), \
                 mock.patch.object(sys, "argv", ["x", "--repo-root", str(root), "--offline"]):
                self.assertEqual(fcv.main(), 0)
            self.assertFalse((cache / "GLB1_summary_1.json").exists())
            per_gene = json.loads((root / "data" / "processed" / "gene_variants.json").read_text())["GLB1"]
            self.assertEqual(per_gene["missense_kept"], 12)
            # A second offline run finds only the halves in the cache and must still use them.
            with mock.patch.object(fce, "request_bytes", side_effect=AssertionError("network used")), \
                 mock.patch.object(sys, "argv", ["x", "--repo-root", str(root), "--offline"]):
                self.assertEqual(fcv.main(), 0)
            again = json.loads((root / "data" / "processed" / "gene_variants.json").read_text())
            self.assertEqual(again["GLB1"]["missense_kept"], 12)
        finally:
            remove_tmp(root)


    def test_batches_split_twice_are_found_offline(self):
        # Like GLA on the real run: batch 7 split into 7a and 7b, and 7a split again into 7aa and 7ab,
        # so neither 7.json nor 7a.json exists (only a leftover 7a.json.headers.json).
        root = make_tmp()
        try:
            (root / "data" / "processed").mkdir(parents=True)
            (root / "data" / "processed" / "gene_structures.json").write_text(json.dumps(
                {"GLB1": {"accession": "P16278", "seq": "MG" + "A" * 20, "plddt": [95] * 22, "first_residue": 1}}))
            cache = root / "data" / "raw" / "clinvar" / "variants"
            cache.mkdir(parents=True)
            recs = {str(i): record(str(i), "NM_1.1(GLB1):c.1A>G (p.Gly2Arg)") for i in range(24)}
            ids = list(recs)
            (cache / "GLB1_search.json").write_text(json.dumps({"esearchresult": {"count": "24", "idlist": ids}}))
            (cache / "GLB1_summary_1a.json.headers.json").write_text("{}")
            for tag, part in (("1aa", ids[:6]), ("1ab", ids[6:12]), ("1b", ids[12:])):
                (cache / f"GLB1_summary_{tag}.json").write_text(json.dumps({"result": {"uids": part, **{u: recs[u] for u in part}}}))
            with mock.patch.object(fce, "request_bytes", side_effect=AssertionError("network used")), \
                 mock.patch.object(sys, "argv", ["x", "--repo-root", str(root), "--offline"]):
                self.assertEqual(fcv.main(), 0)
            manifest = json.loads((root / "data" / "manifests" / "gene_variants_v0.1.json").read_text())
            self.assertEqual((manifest["problems"], manifest["variants"]), ([], 24))
        finally:
            remove_tmp(root)


if __name__ == "__main__":
    unittest.main()
