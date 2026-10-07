#!/usr/bin/env python3
"""Synchronize computed, bounded structure evidence into the local graph CSVs.

Only rows marked ``computed`` in data/processed/structure_comparison.csv create
an inferred ``SIMILAR_TO`` edge. Rows marked ``not_evaluated`` are intentionally
not converted into graph edges: insufficient sequence mapping is not negative
biological evidence.

The script modifies source-controlled graph/nodes.csv and graph/edges.csv, but
does not connect to Neo4j. Run graph/load_neo4j.py afterwards for a local dry
run; use its explicit --load option separately when a reviewed graph is ready
to write to Neo4j.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_VERSION = "0.1.0"
NODE_FIELDS = ["node_id", "node_type", "label", "external_id", "source_url", "status"]
EDGE_FIELDS = [
    "edge_id",
    "source_id",
    "edge_type",
    "target_id",
    "assertion_level",
    "evidence_id",
    "confidence",
    "source_url",
    "notes",
    "method",
    "score_name",
    "primary_score",
    "minimum_coverage_pct",
    "aligned_residue_pairs",
    "high_confidence_ca_pairs",
    "structure_comparison_id",
    "source_model_version",
    "target_model_version",
]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        rows = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"Malformed row at {path}:{line_number}")
            rows.append({key: value or "" for key, value in row.items() if key is not None})
    return list(reader.fieldnames), rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def accession(protein_id: str) -> str:
    prefix, separator, value = protein_id.partition(":")
    if prefix != "UNIPROT" or not separator or not value:
        raise ValueError(f"Expected UNIPROT protein ID, received {protein_id!r}")
    return value


def derived_identifiers(row: dict[str, str]) -> tuple[str, str]:
    source = accession(row["source_protein_id"])
    target = accession(row["target_protein_id"])
    suffix = f"{source}_{target}"
    return f"EVIDENCE:SIMSTRUCT_{suffix}", f"EDGE:SIMSTRUCT-{source}-{target}"


def model_urls(row: dict[str, str]) -> str:
    return ";".join(filter(None, (row.get("source_model_url", ""), row.get("target_model_url", ""))))


def evidence_node(row: dict[str, str], evidence_node_id: str) -> dict[str, str]:
    return {
        "node_id": evidence_node_id,
        "node_type": "Evidence",
        "label": (
            f"{row['source_gene_symbol']}/{row['target_gene_symbol']} "
            "sequence-guided AlphaFold structure comparison"
        ),
        "external_id": row["structure_comparison_id"],
        "source_url": model_urls(row),
        "status": "inferred_computational",
    }


def similarity_edge(row: dict[str, str], edge_id: str, evidence_node_id: str) -> dict[str, str]:
    evidence_id = evidence_node_id.removeprefix("EVIDENCE:")
    return {
        "edge_id": edge_id,
        "source_id": row["source_protein_id"],
        "edge_type": "SIMILAR_TO",
        "target_id": row["target_protein_id"],
        "assertion_level": "inferred",
        "evidence_id": evidence_id,
        "confidence": "medium",
        "source_url": model_urls(row),
        "notes": (
            "Computational research lead only: sequence-guided AlphaFold predicted-monomer "
            f"C-alpha fit, RMSD {row['ca_rmsd_angstrom']} A across "
            f"{row['high_confidence_ca_pairs']} mapped pairs with pLDDT >= {row['plddt_cutoff']}; "
            f"minimum mapped coverage {row['minimum_mapped_ca_coverage_pct']}%. "
            "This does not establish shared disease mechanism, substrate, or treatment response."
        ),
        "method": row["method"],
        "score_name": "sequence_guided_ca_rmsd_angstrom",
        "primary_score": row["ca_rmsd_angstrom"],
        "minimum_coverage_pct": row["minimum_mapped_ca_coverage_pct"],
        "aligned_residue_pairs": row["aligned_residue_pairs"],
        "high_confidence_ca_pairs": row["high_confidence_ca_pairs"],
        "structure_comparison_id": row["structure_comparison_id"],
        "source_model_version": row["source_model_version"],
        "target_model_version": row["target_model_version"],
    }


def synchronize(
    node_rows: list[dict[str, str]],
    edge_rows: list[dict[str, str]],
    structure_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Replace previous derived structure edges with rows that pass their gate."""

    retained_nodes = [
        row for row in node_rows if not row.get("node_id", "").startswith("EVIDENCE:SIMSTRUCT_")
    ]
    retained_edges = [
        row for row in edge_rows if not row.get("edge_id", "").startswith("EDGE:SIMSTRUCT-")
    ]
    node_ids = {row["node_id"] for row in retained_nodes}
    generated: list[dict[str, str]] = []
    for row in structure_rows:
        if row.get("status") != "computed":
            continue
        for protein_id in (row["source_protein_id"], row["target_protein_id"]):
            if protein_id not in node_ids:
                raise ValueError(f"Structure result points to missing graph protein node: {protein_id}")
        if not row.get("ca_rmsd_angstrom"):
            raise ValueError(f"Computed structure result lacks RMSD: {row['structure_comparison_id']}")
        evidence_node_id, edge_id = derived_identifiers(row)
        retained_nodes.append(evidence_node(row, evidence_node_id))
        retained_edges.append(similarity_edge(row, edge_id, evidence_node_id))
        generated.append(
            {
                "structure_comparison_id": row["structure_comparison_id"],
                "evidence_node_id": evidence_node_id,
                "edge_id": edge_id,
                "primary_score": row["ca_rmsd_angstrom"],
            }
        )
    return retained_nodes, retained_edges, generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--structure-comparison", default="data/processed/structure_comparison.csv")
    parser.add_argument("--nodes", default="graph/nodes.csv")
    parser.add_argument("--edges", default="graph/edges.csv")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    structure_path = root / args.structure_comparison
    nodes_path = root / args.nodes
    edges_path = root / args.edges
    node_fields, node_rows = read_csv(nodes_path)
    edge_fields, edge_rows = read_csv(edges_path)
    _structure_fields, structure_rows = read_csv(structure_path)
    if node_fields[: len(NODE_FIELDS)] != NODE_FIELDS:
        raise ValueError(f"Unexpected graph node schema in {nodes_path}")
    if any(field not in edge_fields for field in EDGE_FIELDS[:9]):
        raise ValueError(f"Graph edge schema in {edges_path} is missing a required base field")

    updated_nodes, updated_edges, generated = synchronize(node_rows, edge_rows, structure_rows)
    # Preserve columns added by other layers (e.g. properties_json from the cluster sync).
    write_csv(nodes_path, node_fields, updated_nodes)
    write_csv(edges_path, EDGE_FIELDS + [f for f in edge_fields if f not in EDGE_FIELDS], updated_edges)
    manifest_path = root / "data" / "manifests" / "graph_structure_sync_v0.1.json"
    manifest_path.write_text(
        json.dumps(
            {
                "pipeline": "RarePath structure evidence graph synchronization",
                "script_version": SCRIPT_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "inputs": {
                    "structure_comparison_csv": args.structure_comparison,
                    "structure_comparison_sha256": sha256_file(structure_path),
                    "nodes_csv": args.nodes,
                    "edges_csv": args.edges,
                },
                "policy": {
                    "created_edges": "only rows where status == computed",
                    "excluded_rows": "not_evaluated rows are not negative structural evidence",
                    "assertion_level": "inferred",
                    "confidence": "medium",
                },
                "generated": generated,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Synchronized {len(generated)} computed structure result(s) into {nodes_path} and {edges_path}.")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"Graph synchronization failed: {error}")
        raise SystemExit(1)
