#!/usr/bin/env python3
"""Fetch a short profile and the predicted 3D structure for every scoring gene.

For each gene used for scoring (``used_for_scoring`` in cluster_disease_genes.csv):

* **UniProt** (reviewed human entry): protein name, length, the curated
  "Function" and "Subcellular location" summaries.
* **AlphaFold DB**: the predicted model's ID, version and mean confidence
  (pLDDT), and the model file itself. Only the C-alpha trace and the per-residue
  pLDDT are kept for the explorer's 3D view, centred and rounded to 0.1 Å.

Local-first like the other fetch steps: every response and model file is cached
under ``data/raw/`` and reused; ``--refresh`` ignores the cache and
``--offline`` never touches the network. Proteins with no single full-length
AlphaFold model (very long proteins are split into fragments) are recorded
without a structure rather than shown in pieces.

    python pipelines/fetch_gene_profiles.py

Outputs:
    data/processed/gene_profiles.csv
    data/processed/gene_structures.json     (C-alpha traces for the explorer)
    data/manifests/gene_profiles_v0.1.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

try:  # run as a script (python pipelines/...) or imported as pipelines.fetch_gene_profiles
    from fetch_cluster_expansion import FetchError, cached_bytes, sha256_file, uniprot_accession, write_atomic, write_csv
except ImportError:  # pragma: no cover - import path depends on how the module is loaded
    from pipelines.fetch_cluster_expansion import FetchError, cached_bytes, sha256_file, uniprot_accession, write_atomic, write_csv

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_VERSION = "0.1.0"
UNIPROT_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"
ALPHAFOLD_API = "https://alphafold.ebi.ac.uk/api/prediction/{accession}"
UNIPROT_FIELDS = "accession,gene_primary,protein_name,length,cc_function,cc_subcellular_location"
PROFILE_FIELDS = [
    "gene_symbol", "uniprot_accession", "protein_name", "length", "function", "subcellular_location",
    "alphafold_model_id", "alphafold_version", "alphafold_mean_plddt", "alphafold_model_url",
    "structure_status", "uniprot_release", "uniprot_url", "retrieved_at",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _strip_evidence(text: str) -> str:
    text = re.sub(r"\{ECO:[^}]*\}", "", text or "")
    text = re.sub(r"\s*\((?:PubMed|By similarity|Probable|Microbial infection)[^)]*\)", "", text)
    text = re.sub(r"\s+([.,;])", r"\1", text)
    text = re.sub(r"\.(\s*\.)+", ".", text)
    return re.sub(r"\s{2,}", " ", text).strip(" ;")


def comment_blocks(text: str, label: str) -> list[str]:
    """UniProt's 'LABEL: ...; LABEL: [Isoform 2]: ...' as a list of blocks for the canonical protein.

    Blocks without an isoform tag describe the canonical entry. If every block is tagged, only the
    first one (normally Isoform 1, the canonical sequence) is kept, without its tag.
    """
    blocks = [b.strip(" ;") for b in re.split(rf"(?:^|;\s*){label}:\s*", text or "") if b.strip(" ;")]
    plain = [b for b in blocks if not b.startswith("[")]
    if plain:
        return plain
    return [re.sub(r"^\[[^\]]*\]:\s*", "", blocks[0])] if blocks else []


def clean_comment(text: str, label: str) -> str:
    """Plain-language text from a UniProt comment: canonical isoform only, evidence codes removed."""
    return _strip_evidence(" ".join(comment_blocks(text, label)))


TOPOLOGY = re.compile(r"(membrane protein|anchor|side|GPI-like-anchor)$", re.I)


def clean_location(text: str) -> str:
    """'Cell membrane; Lipid-anchor; Cytoplasmic side. Golgi apparatus. Note=...' -> 'Cell membrane, Golgi apparatus'."""
    places: list[str] = []
    for block in comment_blocks(text, "SUBCELLULAR LOCATION"):
        block = _strip_evidence(block.split("Note=")[0])
        for part in re.split(r"[.;]\s*", block):
            part = part.strip(" .")
            if not part or TOPOLOGY.search(part):
                continue
            # UniProt writes a location as a path ("Cytoplasm, cytoskeleton, cilium basal body"): keep the most specific step.
            place = part.split(", ")[-1]
            place = place[:1].upper() + place[1:]
            if place not in places:
                places.append(place)
    return "; ".join(places)


def first_sentences(text: str, limit: int = 600) -> str:
    """Up to ``limit`` characters, cut at a sentence end."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind(". ")
    return (cut[: end + 1] if end > 120 else cut.rstrip() + "…")


def uniprot_profile(accession: str, cache_dir: Path, refresh: bool) -> tuple[dict[str, str], str]:
    params = {"query": f"accession:{accession}", "format": "tsv", "fields": UNIPROT_FIELDS, "size": "1"}
    body, headers = cached_bytes(cache_dir / f"{accession}.tsv", f"{UNIPROT_SEARCH_URL}?{urlencode(params)}",
                                 "text/tab-separated-values", refresh)
    rows = list(csv.DictReader(body.decode("utf-8").splitlines(), delimiter="\t"))
    row = next((r for r in rows if r.get("Entry") == accession), None)
    if not row:
        raise FetchError(f"UniProt has no entry {accession}")
    release = next((v for k, v in headers.items() if k.lower() == "x-uniprot-release"), "unknown")
    return {
        "protein_name": re.sub(r"\s*\(.*$", "", row.get("Protein names", "")).strip(),
        "length": row.get("Length", ""),
        "function": first_sentences(clean_comment(row.get("Function [CC]", ""), "FUNCTION")),
        "subcellular_location": first_sentences(clean_location(row.get("Subcellular location [CC]", "")), 240),
    }, release


def alphafold_entry(accession: str, length: int, cache_dir: Path, refresh: bool) -> dict[str, Any] | None:
    """The single full-length AlphaFold model for this accession, or None."""
    try:
        body, _ = cached_bytes(cache_dir / f"{accession}_prediction.json", ALPHAFOLD_API.format(accession=accession),
                               "application/json", refresh)
    except FetchError as error:
        if "404" in str(error):
            return None
        raise
    entries = json.loads(body.decode("utf-8"))
    if isinstance(entries, dict):
        entries = [entries]
    for e in entries:
        start, end = int(e.get("uniprotStart") or e.get("sequenceStart") or 0), int(e.get("uniprotEnd") or e.get("sequenceEnd") or 0)
        if str(e.get("modelEntityId") or e.get("entryId", "")).endswith("-F1") and start == 1 and (not length or end == length):
            return e
    return None


THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "SEC": "U", "PYL": "O",
}


def ca_trace(pdb_text: str, sequence: list[str] | None = None) -> tuple[list[int], list[float], list[int]]:
    """C-alpha residue numbers, coordinates (flat x, y, z) and pLDDT (B-factor column) from a PDB file.

    If ``sequence`` is given, the one-letter amino acid of each residue is appended to it.
    """
    resnums, xyz, plddt, seen = [], [], [], set()
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM") or line[12:16].strip() != "CA":
            continue
        key = (line[21], line[22:27])
        if key in seen:  # alternate locations
            continue
        seen.add(key)
        resnums.append(int(line[22:26]))
        xyz.extend(float(line[c:c + 8]) for c in (30, 38, 46))
        plddt.append(round(float(line[60:66])))
        if sequence is not None:
            sequence.append(THREE_TO_ONE.get(line[17:20].strip(), "X"))
    return resnums, xyz, plddt


def compact_trace(xyz: list[float]) -> list[int]:
    """Centre the trace and store tenths of an Ångström as integers (small, exact enough for display)."""
    n = len(xyz) // 3
    if not n:
        return []
    centre = [sum(xyz[i::3]) / n for i in range(3)]
    return [round((xyz[i] - centre[i % 3]) * 10) for i in range(len(xyz))]


def scoring_genes(processed: Path) -> dict[str, str]:
    """gene symbol -> UniProt accession (from the cluster fetch), for every gene used for scoring."""
    with (processed / "cluster_disease_genes.csv").open(encoding="utf-8", newline="") as stream:
        genes = sorted({r["gene_symbol"] for r in csv.DictReader(stream)
                        if (r.get("used_for_scoring") or "").lower() == "true"
                        or (not r.get("used_for_scoring") and r.get("association_type", "").upper() == "MENDELIAN")})
    accessions: dict[str, str] = {}
    pathways = processed / "cluster_gene_pathways.csv"
    if pathways.exists():
        with pathways.open(encoding="utf-8", newline="") as stream:
            for r in csv.DictReader(stream):
                accessions.setdefault(r["gene_symbol"], r["uniprot_accession"])
    return {g: accessions.get(g, "") for g in genes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--refresh", action="store_true", help="Ignore cached responses and model files.")
    parser.add_argument("--offline", action="store_true", help="Use cached files only; skip genes that are not cached.")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    processed, raw = root / "data" / "processed", root / "data" / "raw"
    genes = scoring_genes(processed)
    uniprot_cache, af_cache = raw / "uniprot" / "entries", raw / "structures" / "alphafold" / "profiles"
    retrieved_at = utc_now()
    profiles, structures, model_files, problems = [], {}, {}, []
    releases: set[str] = set()

    def fetch(cache: Path, url: str, accept: str) -> tuple[bytes, dict[str, str]]:
        if args.offline and not cache.is_file():
            raise FetchError(f"offline and not cached: {cache.name}")
        return cached_bytes(cache, url, accept, args.refresh)

    for symbol, accession in genes.items():
        try:
            if not accession:
                if args.offline:
                    raise FetchError("no accession in cluster_gene_pathways.csv")
                accession, _, _ = uniprot_accession(symbol, raw / "uniprot" / "gene_search", args.refresh)
            if args.offline and not (uniprot_cache / f"{accession}.tsv").is_file():
                raise FetchError("offline and UniProt entry not cached")
            info, release = uniprot_profile(accession, uniprot_cache, args.refresh)
            releases.add(release)
        except FetchError as error:
            problems.append(f"{symbol}: {error}")
            continue
        row = {"gene_symbol": symbol, "uniprot_accession": accession, **info, "uniprot_release": release,
               "uniprot_url": f"https://www.uniprot.org/uniprotkb/{accession}/entry", "retrieved_at": retrieved_at,
               "structure_status": "no full-length AlphaFold model"}
        try:
            if args.offline and not (af_cache / f"{accession}_prediction.json").is_file():
                raise FetchError("offline and AlphaFold entry not cached")
            entry = alphafold_entry(accession, int(info["length"] or 0), af_cache, args.refresh)
            if entry:
                version = str(entry.get("latestVersion") or entry.get("modelVersion") or "")
                model_url = entry["pdbUrl"]
                model_path = af_cache / Path(model_url).name
                body, _ = fetch(model_path, model_url, "chemical/x-pdb, text/plain, */*")
                seq: list[str] = []
                resnums, xyz, plddt = ca_trace(body.decode("utf-8", errors="replace"), seq)
                if not resnums:
                    raise FetchError("model file has no C-alpha atoms")
                mean = round(sum(plddt) / len(plddt), 1)
                row.update({"alphafold_model_id": entry.get("modelEntityId") or entry.get("entryId", ""),
                            "alphafold_version": version, "alphafold_mean_plddt": mean,
                            "alphafold_model_url": model_url, "structure_status": "ok"})
                structures[symbol] = {
                    "gene": symbol, "accession": accession, "model_id": row["alphafold_model_id"], "version": version,
                    "mean_plddt": mean, "first_residue": resnums[0], "seq": "".join(seq), "plddt": plddt, "xyz": compact_trace(xyz),
                }
                model_files[Path(model_url).name] = sha256_file(model_path)
        except FetchError as error:
            problems.append(f"{symbol} structure: {error}")
            row["structure_status"] = "not fetched"
        profiles.append(row)
        print(f"{symbol} -> {accession}: {row['structure_status']}"
              f"{' (mean pLDDT ' + str(row.get('alphafold_mean_plddt')) + ')' if row['structure_status'] == 'ok' else ''}",
              flush=True)
        if not args.offline:
            time.sleep(0.2)

    write_csv(processed / "gene_profiles.csv", profiles, PROFILE_FIELDS)
    write_atomic(processed / "gene_structures.json",
                 (json.dumps(structures, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))
    manifest = {
        "pipeline": "RarePath gene profiles and AlphaFold structures",
        "script_version": SCRIPT_VERSION,
        "retrieved_at": retrieved_at,
        "genes_requested": len(genes),
        "profiles": len(profiles),
        "structures": len(structures),
        "problems": problems,
        "sources": {
            "uniprot": {"api": UNIPROT_SEARCH_URL, "fields": UNIPROT_FIELDS, "releases": sorted(releases)},
            "alphafold": {"api": ALPHAFOLD_API, "licence": "CC BY 4.0", "model_sha256": model_files,
                          "citation": "Jumper et al., Nature 2021; Varadi et al., Nucleic Acids Research 2024"},
        },
        "stored_trace": "C-alpha coordinates centred on the protein and rounded to 0.1 Å, with per-residue pLDDT",
    }
    (root / "data" / "manifests").mkdir(parents=True, exist_ok=True)
    (root / "data" / "manifests" / "gene_profiles_v0.1.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for problem in problems:
        print(f"Note: {problem}", file=sys.stderr)
    print(f"{len(profiles)} gene profiles, {len(structures)} structures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
