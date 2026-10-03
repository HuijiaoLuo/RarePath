#!/usr/bin/env python3
"""Fetch and normalize the first RarePath seed dataset.

The script deliberately uses the Python standard library only. It stores raw
source snapshots before writing the normalized CSV files used by the prototype.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCRIPT_VERSION = "0.1.0"
USER_AGENT = "RarePathHackathon/0.1 (public-data seed pipeline)"

MONDO_RELEASE_URL = "https://api.github.com/repos/monarch-initiative/mondo/releases/latest"
EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CLINICAL_TRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"

SEED_DISEASES = {
    "MONDO:0018149": "GM1 gangliosidosis",
    "MONDO:0009261": "GM1 gangliosidosis type 2",
    "MONDO:0017720": "GM2 gangliosidosis",
    "MONDO:0010100": "Tay-Sachs disease",
    "MONDO:0010006": "Sandhoff disease",
}
SEED_DISEASE_LABEL_HINTS = ["gaucher disease type ii"]

CLINVAR_QUERIES = [
    {
        "gene_symbol": "GLB1",
        "condition": "GM1 gangliosidosis",
        "query": 'GLB1[gene] AND "GM1 gangliosidosis"[All Fields]',
    },
    {
        "gene_symbol": "HEXA",
        "condition": "Tay-Sachs disease or GM2 gangliosidosis",
        "query": 'HEXA[gene] AND ("Tay-Sachs disease"[All Fields] OR "GM2 gangliosidosis"[All Fields])',
    },
    {
        "gene_symbol": "HEXB",
        "condition": "Sandhoff disease or GM2 gangliosidosis",
        "query": 'HEXB[gene] AND ("Sandhoff disease"[All Fields] OR "GM2 gangliosidosis"[All Fields])',
    },
    {
        "gene_symbol": "GM2A",
        "condition": "GM2 gangliosidosis",
        "query": 'GM2A[gene] AND "GM2 gangliosidosis"[All Fields]',
    },
]

NCT_IDS = ["NCT05109793", "NCT00029965", "NCT07054515", "NCT04470713"]


class DownloadError(RuntimeError):
    """Raised when a source cannot be downloaded safely."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_stamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def iso_time(now: datetime) -> str:
    return now.isoformat().replace("+00:00", "Z")


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def write_bytes(path: Path, payload: bytes) -> None:
    ensure_directory(path.parent)
    path.write_bytes(payload)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def request_bytes(url: str, retries: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"})
        try:
            with urlopen(request, timeout=90) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise DownloadError(f"Could not download {url}: {last_error}")


def request_json(url: str, retries: int = 3) -> Any:
    try:
        return json.loads(request_bytes(url, retries).decode("utf-8"))
    except json.JSONDecodeError as error:
        raise DownloadError(f"Source did not return JSON: {url}") from error


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(as_text(item) for item in value if item is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def find_mondo_asset(release: dict[str, Any]) -> str:
    assets = release.get("assets", [])
    for asset in assets:
        if asset.get("name") == "mondo.json":
            return str(asset["browser_download_url"])

    tag = release.get("tag_name")
    if tag:
        return f"https://github.com/monarch-initiative/mondo/releases/download/{tag}/mondo.json"

    raise DownloadError("The latest Mondo release has no mondo.json asset or release tag.")


def mondo_synonyms(node: dict[str, Any]) -> str:
    synonyms = node.get("meta", {}).get("synonyms", [])
    values: list[str] = []
    for synonym in synonyms:
        if isinstance(synonym, dict) and synonym.get("val"):
            values.append(str(synonym["val"]))
        elif isinstance(synonym, str):
            values.append(synonym)
    return "; ".join(sorted(set(values)))


def mondo_xrefs(node: dict[str, Any]) -> str:
    xrefs = node.get("meta", {}).get("xrefs", [])
    values: list[str] = []
    for xref in xrefs:
        if isinstance(xref, dict) and xref.get("val"):
            values.append(str(xref["val"]))
        elif isinstance(xref, str):
            values.append(xref)
    return "; ".join(sorted(set(values)))


def normalize_mondo_id(value: str) -> str:
    """Convert OBO PURLs in Mondo JSON into the CURIE form used by the app."""
    marker = "http://purl.obolibrary.org/obo/"
    if value.startswith(marker):
        value = value.removeprefix(marker)
    if value.startswith("MONDO_"):
        return value.replace("_", ":", 1)
    return value


def fetch_mondo(data_root: Path, stamp: str, retrieved_at: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    release = request_json(MONDO_RELEASE_URL)
    release_tag = str(release.get("tag_name", "unknown-release"))
    source_url = find_mondo_asset(release)
    raw_dir = data_root / "raw" / "mondo" / release_tag
    write_json(raw_dir / "release.json", release)

    mondo_path = raw_dir / "mondo.json"
    if not mondo_path.exists():
        print(f"Downloading Mondo release {release_tag}...", flush=True)
        write_bytes(mondo_path, request_bytes(source_url))

    with mondo_path.open("r", encoding="utf-8") as stream:
        mondo = json.load(stream)

    nodes: dict[str, dict[str, Any]] = {}
    for graph in mondo.get("graphs", []):
        for node in graph.get("nodes", []):
            raw_node_id = node.get("id")
            if raw_node_id:
                nodes[normalize_mondo_id(str(raw_node_id))] = node

    selected: dict[str, dict[str, Any]] = {}
    for node_id in SEED_DISEASES:
        if node_id in nodes:
            selected[node_id] = nodes[node_id]

    lowered_hints = [hint.lower() for hint in SEED_DISEASE_LABEL_HINTS]
    for node_id, node in nodes.items():
        label = str(node.get("lbl", "")).lower()
        if label in lowered_hints:
            selected[node_id] = node

    rows = [
        {
            "disease_id": node_id,
            "label": str(node.get("lbl", "")),
            "synonyms": mondo_synonyms(node),
            "xrefs": mondo_xrefs(node),
            "mondo_release_tag": release_tag,
            "source_url": source_url,
            "retrieved_at": retrieved_at,
        }
        for node_id, node in sorted(selected.items())
    ]
    write_csv(
        data_root / "processed" / "diseases.csv",
        rows,
        ["disease_id", "label", "synonyms", "xrefs", "mondo_release_tag", "source_url", "retrieved_at"],
    )

    return rows, {
        "release_tag": release_tag,
        "source_url": source_url,
        "raw_path": str(mondo_path),
        "sha256": sha256_file(mondo_path),
        "record_count": len(rows),
        "requested_seed_ids": SEED_DISEASES,
        "missing_seed_ids": sorted(set(SEED_DISEASES) - set(selected)),
        "snapshot_stamp": stamp,
    }


def eutils_json(endpoint: str, parameters: dict[str, str]) -> Any:
    parameters = {**parameters, "tool": "rarepath_hackathon", "retmode": "json"}
    url = f"{EUTILS_URL}/{endpoint}?{urlencode(parameters)}"
    # NCBI documents a three-requests-per-second limit without an API key.
    time.sleep(0.35)
    return request_json(url)


def clinvar_traits(document: dict[str, Any]) -> str:
    traits = document.get("trait_set", [])
    names = []
    for trait in traits:
        if isinstance(trait, dict):
            name = first_present(trait, "trait_name", "name")
            if name:
                names.append(as_text(name))
    return "; ".join(sorted(set(names)))


def clinvar_genes(document: dict[str, Any]) -> str:
    genes = document.get("genes", [])
    names = []
    for gene in genes:
        if isinstance(gene, dict):
            symbol = first_present(gene, "symbol", "gene_symbol")
            if symbol:
                names.append(as_text(symbol))
    return "; ".join(sorted(set(names)))


def normalize_clinvar_document(
    document: dict[str, Any],
    seed_gene: str,
    seed_condition: str,
    query: str,
    retrieved_at: str,
) -> dict[str, str]:
    classification = document.get("germline_classification", {})
    if not isinstance(classification, dict):
        classification = {}

    return {
        "clinvar_variation_id": as_text(first_present(document, "variation_id", "uid")),
        "accession": as_text(first_present(document, "accession", "rcv_accession")),
        "title": as_text(document.get("title")),
        "seed_gene": seed_gene,
        "reported_genes": clinvar_genes(document),
        "seed_condition": seed_condition,
        "reported_traits": clinvar_traits(document),
        "clinical_significance": as_text(first_present(classification, "description", "clinical_significance")),
        "review_status": as_text(first_present(classification, "review_status", "reviewStatus")),
        "last_evaluated": as_text(first_present(classification, "last_evaluated", "last_evaluated_date")),
        "variation_type": as_text(first_present(document, "variation_type", "obj_type")),
        "query": query,
        "source_url": "https://www.ncbi.nlm.nih.gov/clinvar/",
        "retrieved_at": retrieved_at,
        "assertion_level": "curated_source_record",
    }


def fetch_clinvar(data_root: Path, stamp: str, retrieved_at: str, max_per_gene: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    raw_dir = data_root / "raw" / "clinvar" / stamp
    variants: list[dict[str, str]] = []
    gene_rows: list[dict[str, str]] = []
    source_manifest: list[dict[str, Any]] = []

    for seed in CLINVAR_QUERIES:
        symbol = str(seed["gene_symbol"])
        query = str(seed["query"])
        print(f"Querying ClinVar for {symbol}...", flush=True)
        search = eutils_json(
            "esearch.fcgi",
            {"db": "clinvar", "term": query, "retmax": str(max_per_gene)},
        )
        write_json(raw_dir / f"{symbol.lower()}_search.json", search)

        result = search.get("esearchresult", {})
        ids = [str(item) for item in result.get("idlist", [])]
        documents: list[dict[str, Any]] = []

        for start in range(0, len(ids), 100):
            batch = ids[start : start + 100]
            if not batch:
                continue
            summary = eutils_json(
                "esummary.fcgi",
                {"db": "clinvar", "id": ",".join(batch)},
            )
            write_json(raw_dir / f"{symbol.lower()}_summary_{start // 100 + 1}.json", summary)
            summary_result = summary.get("result", {})
            for uid in summary_result.get("uids", []):
                document = summary_result.get(str(uid))
                if isinstance(document, dict):
                    documents.append(document)

        for document in documents:
            variants.append(
                normalize_clinvar_document(
                    document,
                    seed_gene=symbol,
                    seed_condition=str(seed["condition"]),
                    query=query,
                    retrieved_at=retrieved_at,
                )
            )

        gene_rows.append(
            {
                "gene_symbol": symbol,
                "source_url": "https://www.ncbi.nlm.nih.gov/clinvar/docs/access/",
                "query": query,
                "total_matching_records": as_text(result.get("count")),
                "downloaded_records": str(len(documents)),
                "retrieved_at": retrieved_at,
            }
        )
        source_manifest.append(
            {
                "gene_symbol": symbol,
                "query": query,
                "source_record_count": result.get("count", "0"),
                "downloaded_record_count": len(documents),
                "raw_directory": str(raw_dir),
            }
        )

    write_csv(
        data_root / "processed" / "genes.csv",
        gene_rows,
        ["gene_symbol", "source_url", "query", "total_matching_records", "downloaded_records", "retrieved_at"],
    )
    write_csv(
        data_root / "processed" / "variants.csv",
        variants,
        [
            "clinvar_variation_id",
            "accession",
            "title",
            "seed_gene",
            "reported_genes",
            "seed_condition",
            "reported_traits",
            "clinical_significance",
            "review_status",
            "last_evaluated",
            "variation_type",
            "query",
            "source_url",
            "retrieved_at",
            "assertion_level",
        ],
    )

    return variants, {
        "source_url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
        "raw_directory": str(raw_dir),
        "query_count": len(CLINVAR_QUERIES),
        "variant_record_count": len(variants),
        "queries": source_manifest,
    }


def trial_date(module: dict[str, Any], key: str) -> str:
    value = module.get(key, {})
    if isinstance(value, dict):
        return as_text(value.get("date"))
    return as_text(value)


def join_interventions(arms_module: dict[str, Any]) -> str:
    entries = arms_module.get("interventions", [])
    values = []
    for entry in entries:
        if isinstance(entry, dict):
            name = first_present(entry, "name", "interventionName")
            intervention_type = first_present(entry, "type", "interventionType")
            if name:
                values.append(f"{intervention_type}: {name}".strip(": "))
    return "; ".join(values)


def normalize_trial(study: dict[str, Any], retrieved_at: str) -> dict[str, str]:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    conditions = protocol.get("conditionsModule", {})
    sponsor = protocol.get("sponsorCollaboratorsModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    eligibility = protocol.get("eligibilityModule", {})

    phases = design.get("phases", [])
    return {
        "nct_id": as_text(first_present(identification, "nctId", "orgStudyIdInfo")),
        "official_title": as_text(first_present(identification, "officialTitle", "briefTitle")),
        "brief_title": as_text(identification.get("briefTitle")),
        "overall_status": as_text(status.get("overallStatus")),
        "study_type": as_text(design.get("studyType")),
        "phases": as_text(phases),
        "conditions": as_text(conditions.get("conditions")),
        "interventions": join_interventions(arms),
        "lead_sponsor": as_text(sponsor.get("leadSponsor", {}).get("name", "")),
        "study_start_date": trial_date(status, "startDateStruct"),
        "primary_completion_date": trial_date(status, "primaryCompletionDateStruct"),
        "completion_date": trial_date(status, "completionDateStruct"),
        "eligibility_criteria": as_text(eligibility.get("eligibilityCriteria")),
        "minimum_age": as_text(eligibility.get("minimumAge")),
        "maximum_age": as_text(eligibility.get("maximumAge")),
        "sex": as_text(eligibility.get("sex")),
        "source_url": f"https://clinicaltrials.gov/study/{identification.get('nctId', '')}",
        "retrieved_at": retrieved_at,
    }


def fetch_trials(data_root: Path, stamp: str, retrieved_at: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    raw_dir = data_root / "raw" / "clinicaltrials" / stamp
    rows: list[dict[str, str]] = []

    for nct_id in NCT_IDS:
        print(f"Downloading {nct_id}...", flush=True)
        source_url = f"{CLINICAL_TRIALS_URL}/{nct_id}"
        study = request_json(source_url)
        write_json(raw_dir / f"{nct_id}.json", study)
        rows.append(normalize_trial(study, retrieved_at))

    write_csv(
        data_root / "processed" / "studies.csv",
        rows,
        [
            "nct_id",
            "official_title",
            "brief_title",
            "overall_status",
            "study_type",
            "phases",
            "conditions",
            "interventions",
            "lead_sponsor",
            "study_start_date",
            "primary_completion_date",
            "completion_date",
            "eligibility_criteria",
            "minimum_age",
            "maximum_age",
            "sex",
            "source_url",
            "retrieved_at",
        ],
    )

    return rows, {
        "source_url": CLINICAL_TRIALS_URL,
        "raw_directory": str(raw_dir),
        "study_record_count": len(rows),
        "nct_ids": NCT_IDS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch versioned Mondo, ClinVar, and ClinicalTrials.gov seed data."
    )
    parser.add_argument(
        "--data-root",
        default="data",
        help="Directory for raw snapshots, normalized data, and manifests. Default: data",
    )
    parser.add_argument(
        "--clinvar-max-per-gene",
        type=int,
        default=100,
        help="Maximum ClinVar summary records retrieved for each seed gene. Default: 100",
    )
    args = parser.parse_args()

    if args.clinvar_max_per_gene < 1:
        parser.error("--clinvar-max-per-gene must be at least 1")

    now = utc_now()
    stamp = run_stamp(now)
    retrieved_at = iso_time(now)
    data_root = Path(args.data_root)
    ensure_directory(data_root / "processed")
    ensure_directory(data_root / "manifests")

    print("Fetching versioned Mondo data...", flush=True)
    diseases, mondo_manifest = fetch_mondo(data_root, stamp, retrieved_at)
    variants, clinvar_manifest = fetch_clinvar(
        data_root,
        stamp,
        retrieved_at,
        max_per_gene=args.clinvar_max_per_gene,
    )
    studies, trials_manifest = fetch_trials(data_root, stamp, retrieved_at)

    manifest = {
        "pipeline": "RarePath seed data fetch",
        "script_version": SCRIPT_VERSION,
        "retrieved_at": retrieved_at,
        "seed_scope": "GM1 / GM2 gangliosidosis prototype",
        "components": {
            "mondo": mondo_manifest,
            "clinvar": clinvar_manifest,
            "clinicaltrials": trials_manifest,
        },
        "normalized_outputs": {
            "diseases": {"path": str(data_root / "processed" / "diseases.csv"), "record_count": len(diseases)},
            "variants": {"path": str(data_root / "processed" / "variants.csv"), "record_count": len(variants)},
            "studies": {"path": str(data_root / "processed" / "studies.csv"), "record_count": len(studies)},
        },
    }
    write_json(data_root / "manifests" / f"seed_snapshot_{stamp}.json", manifest)

    print("\nCompleted seed snapshot.")
    print(f"Diseases: {len(diseases)}")
    print(f"ClinVar records: {len(variants)}")
    print(f"ClinicalTrials.gov records: {len(studies)}")
    print(f"Manifest: {data_root / 'manifests' / f'seed_snapshot_{stamp}.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DownloadError as error:
        print(f"Download failed: {error}", file=sys.stderr)
        raise SystemExit(1)
