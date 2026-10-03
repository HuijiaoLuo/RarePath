#!/usr/bin/env python3
"""Fetch reviewed human UniProt mappings and sequences for the seed genes.

This is a deterministic identity-resolution step. It does not infer disease
relationships or calculate similarity scores. The output FASTA is the input
for sequence, embedding, and structure workflows.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USER_AGENT = "RarePathHackathon/0.1 (UniProt protein mapping)"
UNIPROT_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"
DEFAULT_GENES = ["GLB1", "HEXA", "HEXB", "GM2A"]
FIELDS = [
    "accession",
    "id",
    "gene_names",
    "protein_name",
    "length",
    "sequence",
    "organism_name",
    "reviewed",
]
CSV_FIELDS = [
    "protein_id",
    "uniprot_accession",
    "isoform_id",
    "gene_symbol",
    "organism_taxon",
    "reviewed",
    "sequence_length",
    "sequence_sha256",
    "mapping_source",
    "source_release",
    "source_url",
    "protein_name",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def request_tsv(url: str) -> tuple[str, str]:
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"},
    )
    try:
        with urlopen(request, timeout=90) as response:
            text = response.read().decode("utf-8")
            release = response.headers.get("X-UniProt-Release", "unknown")
            return text, release
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"UniProt request failed: {url}: {error}") from error


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def query_gene(gene_symbol: str) -> tuple[dict[str, str], str, str]:
    params = {
        "query": f"gene_exact:{gene_symbol} AND organism_id:9606 AND reviewed:true",
        "format": "tsv",
        "fields": ",".join(FIELDS),
        "size": "10",
    }
    url = f"{UNIPROT_SEARCH_URL}?{urlencode(params)}"
    body, release = request_tsv(url)
    rows = list(csv.DictReader(body.splitlines(), delimiter="\t"))
    if not rows:
        raise RuntimeError(f"No reviewed human UniProt entry found for {gene_symbol}")

    rows.sort(key=lambda row: row.get("Entry", ""))
    row = rows[0]
    sequence = row.get("Sequence", "").strip().upper()
    accession = row.get("Entry", "").strip()
    if not accession or not sequence:
        raise RuntimeError(f"Incomplete UniProt row for {gene_symbol}")
    if len(rows) > 1:
        print(
            f"Warning: {gene_symbol} matched {len(rows)} reviewed entries; "
            f"selected {accession} deterministically.",
            file=sys.stderr,
        )
    row["_sequence"] = sequence
    row["_accession"] = accession
    row["_url"] = url
    return row, release, url


def write_outputs(output_root: Path, rows: list[dict[str, str]]) -> None:
    processed = output_root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    csv_path = processed / "proteins.csv"
    fasta_path = processed / "proteins.fasta"

    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    with fasta_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                f">{row['protein_id']}|gene={row['gene_symbol']}|accession={row['uniprot_accession']}\n"
            )
            sequence = row["_sequence"]
            for offset in range(0, len(sequence), 80):
                stream.write(sequence[offset : offset + 80] + "\n")

    print(f"Wrote {len(rows)} protein mappings to {csv_path}")
    print(f"Wrote sequences to {fasta_path}")


def write_manifest(output_root: Path, rows: list[dict[str, str]], retrieved_at: datetime) -> None:
    manifest_dir = output_root / "data" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    stamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
    manifest_path = manifest_dir / f"protein_snapshot_{stamp}.json"
    payload = {
        "pipeline": "RarePath protein mapping",
        "script_version": "0.1.0",
        "retrieved_at": retrieved_at.isoformat().replace("+00:00", "Z"),
        "source": "UniProt REST search",
        "source_releases": sorted({row["source_release"] for row in rows}),
        "genes": [row["gene_symbol"] for row in rows],
        "outputs": {
            "proteins_csv": "data/processed/proteins.csv",
            "proteins_fasta": "data/processed/proteins.fasta",
        },
        "records": [
            {
                "gene_symbol": row["gene_symbol"],
                "uniprot_accession": row["uniprot_accession"],
                "sequence_length": int(row["sequence_length"]),
                "sequence_sha256": row["sequence_sha256"],
            }
            for row in rows
        ],
    }
    with manifest_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
    print(f"Wrote mapping manifest to {manifest_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the RarePath seed protein mappings.")
    parser.add_argument("--output-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--gene", action="append", dest="genes", help="Gene symbol; repeatable.")
    args = parser.parse_args()

    genes = args.genes or DEFAULT_GENES
    retrieved_at = utc_now()
    rows: list[dict[str, str]] = []
    for gene_symbol in genes:
        result, release, source_url = query_gene(gene_symbol)
        sequence = result["_sequence"]
        accession = result["_accession"]
        rows.append(
            {
                "protein_id": f"UNIPROT:{accession}",
                "uniprot_accession": accession,
                "isoform_id": accession,
                "gene_symbol": gene_symbol,
                "organism_taxon": "NCBITaxon:9606",
                "reviewed": "true",
                "sequence_length": str(len(sequence)),
                "sequence_sha256": sha256_text(sequence),
                "mapping_source": "UniProt ID Mapping/search",
                "source_release": release,
                "source_url": source_url,
                "protein_name": result.get("Protein names", ""),
                "_sequence": sequence,
            }
        )

    output_root = Path(args.output_root)
    write_outputs(output_root, rows)
    write_manifest(output_root, rows, retrieved_at)
    print(f"Retrieved at {retrieved_at.isoformat().replace('+00:00', 'Z')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Protein mapping failed: {error}", file=sys.stderr)
        raise SystemExit(1)
