#!/usr/bin/env python3
"""Download a small, versioned AlphaFold DB structure snapshot for RarePath.

This pipeline is intentionally bounded to the reviewed human UniProt proteins
already listed in data/processed/proteins.csv. It queries the AlphaFold DB
metadata endpoint for each accession, downloads one model file per accession,
keeps raw metadata and coordinates locally, and writes an auditable normalized
model table plus a run manifest.

It never downloads an AlphaFold proteome or a Foldseek database.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCRIPT_VERSION = "0.1.0"
USER_AGENT = "RarePathHackathon/0.1 (bounded AlphaFold DB structure snapshot)"
ALPHAFOLD_API = "https://alphafold.ebi.ac.uk/api/prediction/{accession}"
DEFAULT_MAX_MODEL_BYTES = 50 * 1024 * 1024

CSV_FIELDS = [
    "structure_id",
    "protein_id",
    "gene_symbol",
    "uniprot_accession",
    "structure_source",
    "model_id",
    "model_version",
    "model_created_date",
    "model_format",
    "sequence_length",
    "global_metric_name",
    "global_metric_value",
    "model_url",
    "metadata_url",
    "raw_metadata_path",
    "raw_model_path",
    "model_sha256",
    "model_bytes",
    "retrieved_at",
    "status",
    "notes",
]


class DownloadError(RuntimeError):
    """Raised when a source cannot be downloaded or interpreted safely."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def run_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def request_bytes(url: str, max_bytes: int, retries: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        request = Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, chemical/x-pdb, */*"},
        )
        try:
            with urlopen(request, timeout=90) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise DownloadError(
                        f"Refusing {url}: {content_length} bytes exceeds limit {max_bytes}."
                    )
                payload = response.read(max_bytes + 1)
                if len(payload) > max_bytes:
                    raise DownloadError(f"Refusing {url}: response exceeds limit {max_bytes}.")
                return payload
        except (HTTPError, URLError, TimeoutError, DownloadError) as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise DownloadError(f"Could not download {url}: {last_error}")


def request_json(url: str, max_bytes: int) -> Any:
    try:
        return json.loads(request_bytes(url, max_bytes=max_bytes).decode("utf-8"))
    except json.JSONDecodeError as error:
        raise DownloadError(f"Source did not return JSON: {url}") from error


def read_proteins(path: Path, requested_accessions: set[str] | None) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"No protein records found in {path}")
    selected = [
        row
        for row in rows
        if requested_accessions is None or row["uniprot_accession"] in requested_accessions
    ]
    selected.sort(key=lambda row: row["uniprot_accession"])
    if requested_accessions:
        found = {row["uniprot_accession"] for row in selected}
        missing = sorted(requested_accessions - found)
        if missing:
            raise ValueError(f"Accessions not present in {path}: {', '.join(missing)}")
    return selected


def model_version_key(model: dict[str, Any]) -> tuple[int, str, str]:
    value = str(model.get("latestVersion") or model.get("modelVersion") or "")
    match = re.search(r"\d+", value)
    version = int(match.group()) if match else -1
    return (
        version,
        str(model.get("modelCreatedDate") or ""),
        str(model.get("entryId") or ""),
    )


def select_model(accession: str, payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        candidates = [payload]
    elif isinstance(payload, list):
        candidates = [item for item in payload if isinstance(item, dict)]
    else:
        raise DownloadError(f"AlphaFold metadata for {accession} has an unexpected shape.")
    exact = [
        item
        for item in candidates
        if str(item.get("uniprotAccession") or item.get("uniprot_accession") or "") == accession
    ]
    candidates = exact or candidates
    if not candidates:
        raise DownloadError(f"AlphaFold DB returned no model candidates for {accession}.")
    return max(candidates, key=model_version_key)


def model_download(model: dict[str, Any], requested_format: str) -> tuple[str, str]:
    if requested_format == "pdb" and model.get("pdbUrl"):
        return "pdb", str(model["pdbUrl"])
    if requested_format == "cif" and model.get("cifUrl"):
        return "cif", str(model["cifUrl"])
    if model.get("pdbUrl"):
        return "pdb", str(model["pdbUrl"])
    if model.get("cifUrl"):
        return "cif", str(model["cifUrl"])
    raise DownloadError("AlphaFold metadata has neither pdbUrl nor cifUrl.")


def relative_to_root(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def resolved_row(
    protein: dict[str, str],
    model: dict[str, Any],
    metadata_url: str,
    metadata_path: Path,
    model_url: str,
    model_path: Path,
    model_format: str,
    model_payload: bytes,
    retrieved_at: str,
    root: Path,
) -> dict[str, str]:
    global_metric = model.get("globalMetricValue", "")
    return {
        "structure_id": f"ALPHAFOLD:{model.get('entryId') or protein['uniprot_accession']}",
        "protein_id": protein["protein_id"],
        "gene_symbol": protein["gene_symbol"],
        "uniprot_accession": protein["uniprot_accession"],
        "structure_source": "AlphaFold Protein Structure Database",
        "model_id": str(model.get("entryId") or ""),
        "model_version": str(model.get("latestVersion") or model.get("modelVersion") or ""),
        "model_created_date": str(model.get("modelCreatedDate") or ""),
        "model_format": model_format,
        "sequence_length": str(len(str(model.get("sequence") or "")) or protein.get("sequence_length", "")),
        "global_metric_name": "globalMetricValue",
        "global_metric_value": str(global_metric),
        "model_url": model_url,
        "metadata_url": metadata_url,
        "raw_metadata_path": relative_to_root(metadata_path, root),
        "raw_model_path": relative_to_root(model_path, root),
        "model_sha256": sha256_bytes(model_payload),
        "model_bytes": str(len(model_payload)),
        "retrieved_at": retrieved_at,
        "status": "downloaded",
        "notes": "Predicted monomer model. Preserve pLDDT/PAE metadata before structural interpretation.",
    }


def failed_row(protein: dict[str, str], metadata_url: str, retrieved_at: str, error: Exception) -> dict[str, str]:
    return {
        "structure_id": f"ALPHAFOLD:{protein['uniprot_accession']}",
        "protein_id": protein["protein_id"],
        "gene_symbol": protein["gene_symbol"],
        "uniprot_accession": protein["uniprot_accession"],
        "structure_source": "AlphaFold Protein Structure Database",
        "model_id": "",
        "model_version": "",
        "model_created_date": "",
        "model_format": "",
        "sequence_length": protein.get("sequence_length", ""),
        "global_metric_name": "",
        "global_metric_value": "",
        "model_url": "",
        "metadata_url": metadata_url,
        "raw_metadata_path": "",
        "raw_model_path": "",
        "model_sha256": "",
        "model_bytes": "",
        "retrieved_at": retrieved_at,
        "status": "failed",
        "notes": str(error),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--proteins-csv", default="data/processed/proteins.csv")
    parser.add_argument("--accession", action="append", help="UniProt accession; repeatable.")
    parser.add_argument("--format", choices=("pdb", "cif"), default="pdb")
    parser.add_argument("--max-model-bytes", type=int, default=DEFAULT_MAX_MODEL_BYTES)
    parser.add_argument("--dry-run", action="store_true", help="Resolve metadata without downloading coordinates.")
    args = parser.parse_args()
    if args.max_model_bytes < 1:
        parser.error("--max-model-bytes must be positive")

    root = Path(args.repo_root).resolve()
    proteins = read_proteins(
        root / args.proteins_csv,
        set(args.accession) if args.accession else None,
    )
    started_at = utc_now()
    retrieved_at = iso_time(started_at)
    stamp = run_stamp(started_at)
    raw_dir = root / "data" / "raw" / "structures" / "alphafold" / stamp
    rows: list[dict[str, str]] = []

    for protein in proteins:
        accession = protein["uniprot_accession"]
        metadata_url = ALPHAFOLD_API.format(accession=accession)
        print(f"Resolving AlphaFold DB metadata for {accession}...", flush=True)
        try:
            metadata = request_json(metadata_url, max_bytes=args.max_model_bytes)
            metadata_path = raw_dir / f"{accession}_metadata.json"
            write_json(metadata_path, metadata)
            model = select_model(accession, metadata)
            model_format, model_url = model_download(model, args.format)
            if args.dry_run:
                rows.append(
                    {
                        **resolved_row(
                            protein,
                            model,
                            metadata_url,
                            metadata_path,
                            model_url,
                            raw_dir / f"{accession}.{model_format}",
                            model_format,
                            b"",
                            retrieved_at,
                            root,
                        ),
                        "model_sha256": "",
                        "model_bytes": "",
                        "status": "metadata_resolved",
                        "notes": "Dry run: coordinates not downloaded.",
                    }
                )
                continue
            print(f"Downloading {accession} {model_format.upper()} model...", flush=True)
            model_payload = request_bytes(model_url, max_bytes=args.max_model_bytes)
            model_path = raw_dir / f"{accession}.{model_format}"
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_bytes(model_payload)
            rows.append(
                resolved_row(
                    protein,
                    model,
                    metadata_url,
                    metadata_path,
                    model_url,
                    model_path,
                    model_format,
                    model_payload,
                    retrieved_at,
                    root,
                )
            )
        except (DownloadError, OSError, ValueError) as error:
            print(f"Failed {accession}: {error}", file=sys.stderr)
            rows.append(failed_row(protein, metadata_url, retrieved_at, error))

    write_csv(root / "data" / "processed" / "structure_models.csv", rows)
    manifest_path = root / "data" / "manifests" / f"structure_snapshot_{stamp}.json"
    manifest = {
        "pipeline": "RarePath bounded AlphaFold DB structure fetch",
        "script_version": SCRIPT_VERSION,
        "retrieved_at": retrieved_at,
        "source": "AlphaFold Protein Structure Database API",
        "metadata_endpoint_template": ALPHAFOLD_API,
        "requested_format": args.format,
        "max_model_bytes": args.max_model_bytes,
        "dry_run": args.dry_run,
        "inputs": {
            "proteins_csv": args.proteins_csv,
            "accessions": [protein["uniprot_accession"] for protein in proteins],
        },
        "outputs": {
            "structure_models_csv": "data/processed/structure_models.csv",
            "raw_directory": relative_to_root(raw_dir, root),
        },
        "records": rows,
    }
    write_json(manifest_path, manifest)
    downloaded = sum(row["status"] == "downloaded" for row in rows)
    failed = sum(row["status"] == "failed" for row in rows)
    print(f"Wrote {len(rows)} structure records; downloaded={downloaded}, failed={failed}")
    print(f"Manifest: {manifest_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DownloadError, OSError, ValueError) as error:
        print(f"Structure fetch failed: {error}", file=sys.stderr)
        raise SystemExit(1)
