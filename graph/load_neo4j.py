#!/usr/bin/env python3
"""Validate and load the seed graph into Neo4j.

Dry-run validation uses only the standard library. A real load requires:
    python -m pip install neo4j
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path
from typing import Any


RELATION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(row[field] is None for field in reader.fieldnames):
                raise ValueError(f"Malformed CSV row at {path}:{line_number}")
            rows.append(row)  # type: ignore[arg-type]
        return rows


def validate(nodes: list[dict[str, str]], edges: list[dict[str, str]]) -> None:
    node_ids = [row["node_id"] for row in nodes]
    node_set = set(node_ids)
    duplicate_nodes = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    if duplicate_nodes:
        raise ValueError(f"Duplicate node IDs: {duplicate_nodes}")

    edge_ids = [row["edge_id"] for row in edges]
    duplicate_edges = sorted({edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1})
    if duplicate_edges:
        raise ValueError(f"Duplicate edge IDs: {duplicate_edges}")

    missing_endpoints = []
    invalid_relationships = []
    for row in edges:
        if row["source_id"] not in node_set:
            missing_endpoints.append((row["edge_id"], row["source_id"]))
        if row["target_id"] not in node_set:
            missing_endpoints.append((row["edge_id"], row["target_id"]))
        if not RELATION_PATTERN.fullmatch(row["edge_type"]):
            invalid_relationships.append(row["edge_type"])

    if missing_endpoints:
        raise ValueError(f"Missing edge endpoints: {missing_endpoints}")
    if invalid_relationships:
        raise ValueError(f"Invalid relationship types: {sorted(set(invalid_relationships))}")

    evidence_ids = {
        row["node_id"].removeprefix("EVIDENCE:")
        for row in nodes
        if row["node_type"] == "Evidence"
    }
    missing_evidence = sorted(
        {
            row["evidence_id"]
            for row in edges
            if row["evidence_id"] and row["evidence_id"] not in evidence_ids
        }
    )
    if missing_evidence:
        raise ValueError(f"Edges reference missing evidence nodes: {missing_evidence}")


LABEL_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9]*$")
STRUCTURAL_EDGE_FIELDS = {"source_id", "target_id", "edge_type"}


def flatten_properties(row: dict[str, str], skip: set[str]) -> dict[str, Any]:
    """Turn a CSV row (plus its optional properties_json column) into Neo4j-safe properties.

    Empty strings are dropped. Scalars and lists of scalars are stored as-is;
    nested objects are stored as JSON strings so the API can return them intact.
    """
    import json

    props: dict[str, Any] = {k: v for k, v in row.items() if k not in skip and k != "properties_json" and v != ""}
    raw = row.get("properties_json", "")
    if raw:
        extra = json.loads(raw)
        for key, value in extra.items():
            if isinstance(value, (str, int, float, bool)):
                props[key] = value
            elif isinstance(value, list) and all(isinstance(v, (str, int, float, bool)) for v in value):
                props[key] = value
            else:
                props[key] = json.dumps(value, ensure_ascii=False)
        props["properties_json"] = raw
    return props


def chunks(rows: list[Any], size: int = 500) -> list[list[Any]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def load_with_driver(
    nodes: list[dict[str, str]],
    edges: list[dict[str, str]],
    uri: str,
    user: str,
    password: str,
    database: str,
    prune: bool = False,
) -> None:
    try:
        from neo4j import GraphDatabase
    except ImportError as error:
        raise RuntimeError(
            "Neo4j driver is not installed. Run: python -m pip install neo4j"
        ) from error

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            session.run(
                "CREATE CONSTRAINT entity_id IF NOT EXISTS "
                "FOR (n:Entity) REQUIRE n.node_id IS UNIQUE"
            ).consume()

            by_kind: dict[str, list[dict[str, Any]]] = {}
            for row in nodes:
                kind = row["node_type"]
                if not LABEL_PATTERN.fullmatch(kind):
                    raise ValueError(f"Invalid node_type for a Neo4j label: {kind!r}")
                props = flatten_properties(row, {"node_type"})
                props["kind"] = kind
                by_kind.setdefault(kind, []).append({"node_id": row["node_id"], "props": props})
            for kind, batch_rows in by_kind.items():
                for batch in chunks(batch_rows):
                    # Generic :Entity keeps the original API stable; the kind label makes Cypher readable.
                    session.run(
                        "UNWIND $rows AS row "
                        "MERGE (n:Entity {node_id: row.node_id}) "
                        f"SET n += row.props, n:{kind}",
                        {"rows": batch},
                    ).consume()

            by_type: dict[str, list[dict[str, Any]]] = {}
            for row in edges:
                by_type.setdefault(row["edge_type"], []).append(
                    {
                        "source_id": row["source_id"],
                        "target_id": row["target_id"],
                        "edge_id": row["edge_id"],
                        "props": flatten_properties(row, STRUCTURAL_EDGE_FIELDS),
                    }
                )
            for edge_type, batch_rows in by_type.items():
                for batch in chunks(batch_rows):
                    session.run(
                        "UNWIND $rows AS row "
                        "MATCH (source:Entity {node_id: row.source_id}) "
                        "MATCH (target:Entity {node_id: row.target_id}) "
                        f"MERGE (source)-[edge:{edge_type} {{edge_id: row.edge_id}}]->(target) "
                        "SET edge += row.props",
                        {"rows": batch},
                    ).consume()

            if prune:
                # Remove graph items that are no longer in the source-controlled CSVs.
                session.run(
                    "MATCH (:Entity)-[r]->(:Entity) WHERE NOT r.edge_id IN $ids DELETE r",
                    {"ids": [row["edge_id"] for row in edges]},
                ).consume()
                session.run(
                    "MATCH (n:Entity) WHERE NOT n.node_id IN $ids DETACH DELETE n",
                    {"ids": [row["node_id"] for row in nodes]},
                ).consume()
    finally:
        driver.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or load the RarePath seed graph.")
    parser.add_argument("--graph-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--load", action="store_true", help="Load into Neo4j after validation.")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="With --load: delete Entity nodes/relationships that are no longer in the CSVs.",
    )
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument(
        "--user",
        default=os.getenv("NEO4J_USER", os.getenv("NEO4J_USERNAME", "neo4j")),
    )
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", ""))
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    args = parser.parse_args()

    graph_root = Path(args.graph_root)
    nodes = read_csv(graph_root / "nodes.csv")
    edges = read_csv(graph_root / "edges.csv")
    validate(nodes, edges)

    print(f"Validated {len(nodes)} nodes and {len(edges)} edges.")
    if not args.load:
        print("Dry run only. Pass --load to write to Neo4j.")
        return 0

    if not args.password:
        raise SystemExit("Set NEO4J_PASSWORD or pass --password before using --load.")
    load_with_driver(nodes, edges, args.uri, args.user, args.password, args.database, args.prune)
    print(f"Loaded {len(nodes)} nodes and {len(edges)} edges into {args.uri}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Graph load failed: {error}", file=sys.stderr)
        raise SystemExit(1)
