#!/usr/bin/env python3
"""Add hand-checked studies and patient organisations to the graph.

Offline step. Reads ``data/curated/family_resources.csv``: one row per study or
patient organisation, with the official URL, the diseases it covers and the date
and page on which that was checked. Diseases are given as MONDO IDs (for example
a disease series such as "Noonan syndrome") or as OMIM IDs of panel diseases,
which are resolved through ``data/processed/cluster_diseases.csv``.

Writes Study/Organization nodes, one Evidence node per row, and STUDIES or
SUPPORTS edges into ``graph/nodes.csv`` and ``graph/edges.csv``. The step is
idempotent: everything it wrote before (IDs starting ``EDGE:CUR-`` and
``EVIDENCE:CUR-``, nodes with status ``curated_resource``) is replaced.

    python pipelines/sync_curated_resources.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

OWNED_STATUS = "curated_resource"
STUDY_FIELDS = ("overall_status", "study_type", "lead_sponsor", "study_start_date", "completion_date")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")


def resolve(ref: str, omim_to_disease: dict[str, str], node_ids: set[str]) -> str | None:
    ref = ref.strip()
    if ref.startswith("OMIM:"):
        return omim_to_disease.get(ref)
    return ref if ref in node_ids else None


def build(resources: list[dict[str, str]], omim_to_disease: dict[str, str], node_ids: set[str]):
    """Return (nodes, edges, problems). Pure function for testing."""
    nodes, edges, problems = [], [], []
    for row in resources:
        rid, kind = row["resource_id"], row["kind"]
        if kind not in ("Study", "Organization"):
            problems.append(f"{rid}: unknown kind {kind!r}")
            continue
        evidence_key = f"CUR-{slug(rid.split(':', 1)[-1])}"
        props: dict = {"short_name": row.get("short_name", ""), "claim": row.get("claim", ""),
                       "checked_on": row.get("checked_on", ""), "checked_via": row.get("checked_via", "")}
        if kind == "Study":
            props["study"] = {
                "brief_title": row["label"], "conditions": row.get("conditions_on_record", ""),
                "source_url": row["url"], "retrieved_at": row.get("checked_on", ""),
                **{k: row.get(k, "") for k in STUDY_FIELDS},
                "primary_completion_date": "",
            }
        nodes.append({
            "node_id": rid, "node_type": kind, "label": row["label"],
            "external_id": rid.split(":", 1)[-1] if kind == "Study" else row.get("short_name", ""),
            "source_url": row["url"], "status": OWNED_STATUS,
            "properties_json": json.dumps(props, ensure_ascii=False, sort_keys=True),
        })
        nodes.append({
            "node_id": f"EVIDENCE:{evidence_key}", "node_type": "Evidence",
            "label": f"{row.get('short_name') or row['label']}: checked {row.get('checked_on', '')}",
            "external_id": evidence_key, "source_url": row.get("checked_via") or row["url"], "status": OWNED_STATUS,
            "properties_json": json.dumps({"claim": row.get("claim", ""), "checked_on": row.get("checked_on", "")},
                                          ensure_ascii=False, sort_keys=True),
        })
        edge_type = "STUDIES" if kind == "Study" else "SUPPORTS"
        for ref in filter(None, (r.strip() for r in row.get("disease_ids", "").split(";"))):
            target = resolve(ref, omim_to_disease, node_ids)
            if not target:
                problems.append(f"{rid}: disease {ref} is not in the graph")
                continue
            what = "Study record includes" if kind == "Study" else "Patient organisation for"
            edges.append({
                "edge_id": f"EDGE:CUR-{slug(rid.split(':', 1)[-1])}-{slug(target)}", "source_id": rid,
                "edge_type": edge_type, "target_id": target, "assertion_level": "curated",
                "evidence_id": evidence_key, "confidence": "high", "source_url": row.get("checked_via") or row["url"],
                "notes": f"{what} this disease (checked {row.get('checked_on', '')}). {row.get('claim', '')}".strip(),
            })
    return nodes, edges, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    source = root / "data" / "curated" / "family_resources.csv"
    if not source.exists():
        print(f"No curated resources at {source}; nothing to do.")
        return 0
    nodes_path, edges_path = root / "graph" / "nodes.csv", root / "graph" / "edges.csv"
    node_rows, edge_rows = read_csv(nodes_path), read_csv(edges_path)
    node_fields = list(node_rows[0].keys()) if node_rows else []
    edge_fields = list(edge_rows[0].keys()) if edge_rows else []
    node_rows = [n for n in node_rows if n.get("status") != OWNED_STATUS and not n["node_id"].startswith("EVIDENCE:CUR-")]
    edge_rows = [e for e in edge_rows if not e["edge_id"].startswith("EDGE:CUR-")]
    clusters = root / "data" / "processed" / "cluster_diseases.csv"
    omim_to_disease = {r["hpo_disease_id"]: r["disease_id"] for r in read_csv(clusters)} if clusters.exists() else {}
    existing = {n["node_id"] for n in node_rows}
    nodes, edges, problems = build(read_csv(source), omim_to_disease, existing)
    # A study that is already in the graph (from the seed pipeline) keeps its node; only the new links are added.
    nodes = [n for n in nodes if n["node_id"] not in existing]
    triples = {(e["source_id"], e["edge_type"], e["target_id"]) for e in edge_rows}
    edges = [e for e in edges if (e["source_id"], e["edge_type"], e["target_id"]) not in triples]
    write_csv(nodes_path, node_rows + nodes, node_fields)
    write_csv(edges_path, edge_rows + edges, edge_fields)
    for problem in problems:
        print(f"Skipped: {problem}", file=sys.stderr)
    print(f"Curated resources: {len(nodes)} nodes and {len(edges)} edges written; {len(problems)} skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
