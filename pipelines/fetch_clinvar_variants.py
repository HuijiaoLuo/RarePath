#!/usr/bin/env python3
"""Map disease-causing missense variants from ClinVar onto the AlphaFold models.

For every gene with a structure in ``data/processed/gene_structures.json``:

1. Search ClinVar (NCBI E-utilities) for ``GENE[gene] AND (clinsig_pathogenic[prop]
   OR clinsig_likely_pathogenic[prop])`` and fetch the record summaries.
2. Keep germline single-nucleotide **missense** variants whose current
   classification is Pathogenic, Likely pathogenic or Pathogenic/Likely pathogenic,
   and whose preferred name is written on this gene's transcript (ClinVar also lists
   overlapping genes, such as read-through transcripts).
3. Read the protein change from ClinVar's preferred name, e.g.
   ``NM_000404.4(GLB1):c.817T>C (p.Trp273Arg)``, and keep it only if the reference
   amino acid matches the AlphaFold model's sequence at that position. If ClinVar's
   transcript numbers residues differently from UniProt by a constant shift (ARSA: 2),
   the shift is detected per gene and applied only when it explains at least 90% of
   the variants. Anything else that does not match is dropped and counted.

It also asks one question of the result: are these variants concentrated in the
parts of each protein that AlphaFold predicts confidently (pLDDT >= 90)? For each
gene it compares the share of variant positions in very-high-confidence regions
with the share of all residues there, and pools the genes in the manifest. This
is descriptive only: ClinVar is biased towards well-studied regions.

Responses are cached under ``data/raw/clinvar/variants/`` and reused;
``--refresh`` ignores the cache and ``--offline`` never touches the network.
Set NCBI_API_KEY to allow faster requests.

    python pipelines/fetch_clinvar_variants.py

Outputs:
    data/processed/gene_variants.csv
    data/processed/gene_variants.json        (per gene: positions for the 3D view)
    data/manifests/gene_variants_v0.1.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

try:
    from fetch_cluster_expansion import FetchError, cached_bytes, write_atomic, write_csv
except ImportError:  # pragma: no cover
    from pipelines.fetch_cluster_expansion import FetchError, cached_bytes, write_atomic, write_csv

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_VERSION = "0.1.0"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
QUERY = "{gene}[gene] AND (clinsig_pathogenic[prop] OR clinsig_likely_pathogenic[prop])"
MAX_RECORDS = 5000
BATCH = 200
KEEP_CLASSES = {"pathogenic", "likely pathogenic", "pathogenic/likely pathogenic"}
VERY_HIGH = 90
THREE = {
    "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C", "Gln": "Q", "Glu": "E", "Gly": "G", "His": "H", "Ile": "I",
    "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F", "Pro": "P", "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V",
}
PROTEIN_CHANGE = re.compile(r"\(p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})\)")
FIELDS = [
    "gene_symbol", "uniprot_accession", "clinvar_id", "variation_name", "protein_change", "position", "ref", "alt",
    "classification", "review_status", "last_evaluated", "conditions", "plddt", "source_url",
]


class EutilsError(Exception):
    """NCBI answered, but with an error message instead of results."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_record(rec: dict, gene: str) -> dict | None:
    """One ClinVar summary record -> a missense variant row, or None if it does not qualify."""
    gc = rec.get("germline_classification") or {}
    classification = (gc.get("description") or "").strip()
    if classification.lower() not in KEEP_CLASSES:
        return None
    if "missense variant" not in (rec.get("molecular_consequence_list") or []):
        return None
    genes = {g.get("symbol") for g in rec.get("genes") or []}
    if gene not in genes:
        return None
    vs = (rec.get("variation_set") or [{}])[0]
    if (vs.get("variant_type") or "").lower() != "single nucleotide variant":
        return None
    name = vs.get("variation_name") or rec.get("title") or ""
    # ClinVar also lists overlapping genes (read-through transcripts, antisense loci). The preferred
    # name says which gene the protein change is written on, and that must be this one.
    if f"({gene}):" not in name:
        return None
    m = PROTEIN_CHANGE.search(name)
    if not m or m.group(1) not in THREE or m.group(3) not in THREE or m.group(1) == m.group(3):
        return None
    ref, pos, alt = THREE[m.group(1)], int(m.group(2)), THREE[m.group(3)]
    conditions = sorted({t.get("trait_name", "") for t in gc.get("trait_set") or [] if t.get("trait_name")})
    return {
        "gene_symbol": gene, "clinvar_id": str(rec.get("uid", "")), "variation_name": name,
        "protein_change": f"{m.group(1)}{pos}{m.group(3)}", "position": pos, "ref": ref, "alt": alt,
        "classification": classification, "review_status": gc.get("review_status", ""),
        "last_evaluated": (gc.get("last_evaluated") or "")[:10].replace("/", "-"),
        "conditions": "; ".join(conditions),
        "source_url": f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{rec.get('uid', '')}/",
    }


MAX_OFFSET = 60


def numbering_offset(rows: list[dict], seq: str, first_residue: int = 1) -> int:
    """Shift between ClinVar's transcript numbering and the UniProt/AlphaFold sequence.

    ClinVar names variants on its preferred (usually MANE Select) transcript, which can start a few
    residues earlier or later than the UniProt canonical sequence (ARSA: 2). A shift is accepted only
    if it explains at least 90% of at least 10 variants and the unshifted numbering explains under half.
    """
    def hits(k: int) -> int:
        return sum(1 for r in rows if 0 <= r["position"] + k - first_residue < len(seq) and seq[r["position"] + k - first_residue] == r["ref"])
    if len(rows) < 10 or hits(0) >= 0.5 * len(rows):
        return 0
    best = max(range(-MAX_OFFSET, MAX_OFFSET + 1), key=lambda k: (hits(k), -abs(k)))
    return best if hits(best) >= 0.9 * len(rows) else 0


def place_on_structure(rows: list[dict], seq: str, plddt: list[int], first_residue: int = 1,
                       offset: int = 0) -> tuple[list[dict], int]:
    """Keep variants whose reference amino acid matches the model; return (kept rows, number rejected).

    ``position`` becomes the model (UniProt) position; ``protein_change`` keeps ClinVar's own numbering.
    """
    kept, rejected = [], 0
    for r in rows:
        r = {**r, "position": r["position"] + offset}
        i = r["position"] - first_residue
        if 0 <= i < len(seq) and seq[i] == r["ref"]:
            kept.append({**r, "plddt": plddt[i]})
        else:
            rejected += 1
    return kept, rejected


def confidence_summary(positions: set[int], plddt: list[int], first_residue: int = 1) -> dict:
    """Share of variant positions vs all residues that sit in very-high-confidence (pLDDT >= 90) regions."""
    n = len(plddt)
    at = [plddt[p - first_residue] for p in positions if 0 <= p - first_residue < n]
    return {
        "variant_positions": len(at),
        "variant_positions_very_high": sum(v >= VERY_HIGH for v in at),
        "residues": n,
        "residues_very_high": sum(v >= VERY_HIGH for v in plddt),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    processed = root / "data" / "processed"
    structures_path = processed / "gene_structures.json"
    if not structures_path.exists():
        raise SystemExit("Missing data/processed/gene_structures.json. Run pipelines/fetch_gene_profiles.py first.")
    structures = json.loads(structures_path.read_text(encoding="utf-8"))
    cache = root / "data" / "raw" / "clinvar" / "variants"
    key = os.environ.get("NCBI_API_KEY", "")
    pause = 0.12 if key else 0.4  # NCBI allows 10 requests/s with a key, 3 without
    retrieved_at = utc_now()

    def get(name: str, endpoint: str, params: dict) -> dict:
        path = cache / name
        if args.offline and not path.is_file():
            raise FetchError(f"offline and not cached: {name}")
        if key:
            params = {**params, "api_key": key}
        fresh = args.refresh or not path.is_file()
        body, _ = cached_bytes(path, f"{EUTILS}/{endpoint}?{urlencode(params)}", "application/json", args.refresh)
        if fresh and not args.offline:
            time.sleep(pause)
        data = json.loads(body.decode("utf-8"))
        error = (data.get("eutilsresult") or {}).get("ERROR") or (data.get("error") if isinstance(data.get("error"), str) else "")
        if error:
            path.unlink(missing_ok=True)  # never keep an error response in the cache
            path.with_name(path.name + ".headers.json").unlink(missing_ok=True)
            raise EutilsError(error)
        return data

    def was_split(gene: str, tag: str) -> bool:
        """True if the cache holds pieces of this batch (its first half, at any depth)."""
        return any(not f.name.endswith(".headers.json") for f in cache.glob(f"{gene}_summary_{tag}a*.json"))

    def summaries(gene: str, ids: list[str], tag: str) -> list[dict]:
        """esummary for ``ids``; if NCBI refuses the batch as too large, split it in two and retry.

        A batch that was split on an earlier run has no cache file of its own, only its halves
        (``..._1a.json``, ``..._1b.json``, or deeper: ``..._7aa.json``), so those are used directly,
        also with --offline.
        """
        half = len(ids) // 2
        if not (cache / f"{gene}_summary_{tag}.json").is_file() and was_split(gene, tag):
            return summaries(gene, ids[:half], tag + "a") + summaries(gene, ids[half:], tag + "b")
        try:
            result = get(f"{gene}_summary_{tag}.json", "esummary.fcgi",
                         {"db": "clinvar", "id": ",".join(ids), "retmode": "json"}).get("result", {})
            return [result[u] for u in result.get("uids", []) if u in result]
        except EutilsError as error:
            if len(ids) <= 10:
                raise FetchError(f"esummary failed for {len(ids)} records: {error}") from error
            return summaries(gene, ids[:half], tag + "a") + summaries(gene, ids[half:], tag + "b")

    all_rows, per_gene, problems = [], {}, []
    pooled = {"variant_positions": 0, "variant_positions_very_high": 0, "residues": 0, "residues_very_high": 0}
    expected = 0.0  # variant positions expected in very-high regions if each gene's variants fell anywhere at random
    variance = 0.0  # hypergeometric variance of that count, summed over genes
    for gene, s in sorted(structures.items()):
        seq = s.get("seq", "")
        if not seq:
            problems.append(f"{gene}: structure has no sequence (re-run fetch_gene_profiles.py)")
            continue
        try:
            search = get(f"{gene}_search.json", "esearch.fcgi",
                         {"db": "clinvar", "term": QUERY.format(gene=gene), "retmax": str(MAX_RECORDS), "retmode": "json"})
            ids = search.get("esearchresult", {}).get("idlist", [])
            total = int(search.get("esearchresult", {}).get("count", len(ids)))
            if total > len(ids):
                problems.append(f"{gene}: {total} records, first {len(ids)} used")
            records = []
            for b in range(0, len(ids), BATCH):
                records += summaries(gene, ids[b:b + BATCH], str(b // BATCH + 1))
        except FetchError as error:
            problems.append(f"{gene}: {error}")
            continue
        parsed = [r for r in (parse_record(rec, gene) for rec in records) if r]
        offset = numbering_offset(parsed, seq, s.get("first_residue", 1))
        kept, rejected = place_on_structure(parsed, seq, s["plddt"], s.get("first_residue", 1), offset)
        for r in kept:
            r["uniprot_accession"] = s.get("accession", "")
        all_rows += kept
        by_pos: dict[int, list[dict]] = {}
        for r in kept:
            by_pos.setdefault(r["position"], []).append(r)
        conf = confidence_summary(set(by_pos), s["plddt"], s.get("first_residue", 1))
        for k in pooled:
            pooled[k] += conf[k]
        if conf["residues"]:
            n, k, total = conf["variant_positions"], conf["residues_very_high"], conf["residues"]
            expected += n * k / total
            if total > 1:
                variance += n * k * (total - k) * (total - n) / (total * total * (total - 1))
        per_gene[gene] = {
            "records_searched": len(records), "missense_kept": len(kept), "rejected_sequence_mismatch": rejected,
            "clinvar_to_uniprot_offset": offset,
            **conf,
            # For the 3D view: [position, "Arg201Cys / Arg201His", number of records, "conditions named in ClinVar"]
            "positions": [[p, " / ".join(sorted({r["protein_change"] for r in rs})), len(rs),
                           "; ".join(sorted({c for r in rs for c in r["conditions"].split("; ") if c}))]
                          for p, rs in sorted(by_pos.items())],
        }
        print(f"{gene}: {len(records)} records -> {len(kept)} missense at {len(by_pos)} positions"
              f"{f' (ClinVar numbering shifted by {offset} to match UniProt)' if offset else ''}"
              f"{f' ({rejected} did not match the model sequence)' if rejected else ''}", flush=True)

    all_rows.sort(key=lambda r: (r["gene_symbol"], r["position"], r["alt"]))
    write_csv(processed / "gene_variants.csv", all_rows, FIELDS)
    write_atomic(processed / "gene_variants.json",
                 (json.dumps(per_gene, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))
    share = lambda a, b: round(a / b, 3) if b else None
    manifest = {
        "pipeline": "RarePath ClinVar missense variants on AlphaFold models",
        "script_version": SCRIPT_VERSION,
        "retrieved_at": retrieved_at,
        "query": QUERY,
        "kept_classifications": sorted(KEEP_CLASSES),
        "filters": "germline classification above; preferred name written on this gene's transcript; single nucleotide missense; reference amino acid matches the AlphaFold model sequence (after a per-gene numbering shift, if one explains >= 90% of variants)",
        "genes": len(per_gene),
        "variants": len(all_rows),
        "pooled_confidence": {**pooled,
                              "share_of_variant_positions_very_high": share(pooled["variant_positions_very_high"], pooled["variant_positions"]),
                              "share_of_residues_very_high": share(pooled["residues_very_high"], pooled["residues"]),
                              "expected_variant_positions_very_high_if_random": round(expected, 1),
                              "observed_over_expected": round(pooled["variant_positions_very_high"] / expected, 2) if expected else None,
                              "z_score_within_gene_null": round((pooled["variant_positions_very_high"] - expected) / math.sqrt(variance), 1) if variance else None},
        "statistics_note": ("Null model: within each gene, variant positions are a random sample of that protein's residues "
                            "(hypergeometric); genes are combined by summing means and variances. The pooled shares above "
                            "mix genes with different baselines, so compare observed with expected, not the two shares."),
        "interpretation": ("Descriptive comparison only. ClinVar over-represents well-studied genes and regions; "
                           "a higher share in confident regions is consistent with, but does not prove, that "
                           "disease-causing missense changes concentrate in the folded core."),
        "problems": problems,
        "source": {"name": "ClinVar via NCBI E-utilities", "url": "https://www.ncbi.nlm.nih.gov/clinvar/",
                   "terms": "https://www.ncbi.nlm.nih.gov/home/about/policies/"},
    }
    (root / "data" / "manifests").mkdir(parents=True, exist_ok=True)
    (root / "data" / "manifests" / "gene_variants_v0.1.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for problem in problems:
        print(f"Note: {problem}", file=sys.stderr)
    pc = manifest["pooled_confidence"]
    print(f"{len(all_rows)} variants in {len(per_gene)} genes. Variant positions in very-high-confidence regions: "
          f"{pc['variant_positions_very_high']} observed vs {pc['expected_variant_positions_very_high_if_random']} expected "
          f"within genes (ratio {pc['observed_over_expected']}, z {pc['z_score_within_gene_null']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
