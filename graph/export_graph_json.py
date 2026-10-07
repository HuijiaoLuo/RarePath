#!/usr/bin/env python3
"""Export the source-controlled graph CSVs as the explorer's data file.

Writes ``demo/data/graph.js`` (``window.RAREPATH_GRAPH = {...}``) so the
explorer opens straight from disk (file://) or any static host, plus
``demo/data/graph.json`` for tooling. The same ``build_payload`` function is
used by ``api/server.py`` for rows read from Neo4j, so both paths return the
same shape.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
STRUCTURE_FIELDS = [
    "method", "score_name", "primary_score", "minimum_coverage_pct", "aligned_residue_pairs",
    "high_confidence_ca_pairs", "structure_comparison_id", "source_model_version", "target_model_version",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        return [{k: (v or "") for k, v in row.items() if k is not None} for row in csv.DictReader(stream)]


def parse_props(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def seed_evidence_wording(repo_root: Path) -> dict[str, dict[str, str]]:
    """Pull the curated UI wording for E-01..E-09 out of the seed evidence table."""
    path = repo_root / "docs" / "SEED_EVIDENCE_TABLE.md"
    if not path.exists():
        return {}
    wording: dict[str, dict[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\|\s*E-\d+\s*\|", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6:
            plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cells[4])
            wording[cells[0]] = {"assertion": cells[1], "type": cells[2], "wording": plain, "status": cells[5]}
    return wording


def search_terms(node: dict[str, Any]) -> list[str]:
    terms = {node["label"], node["id"], node.get("external_id", "")}
    terms.update(node.get("synonyms", []))
    if node["kind"] == "Gene":
        terms.add(node["label"])
    return sorted(t for t in terms if t)


def graph_version(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], extra: Any = None) -> str:
    """A short fingerprint of the graph content: same nodes and edges, same version.

    It does not depend on when or where the payload was built, so the CSV export, the
    Neo4j copy and the chat server agree whenever they hold the same graph, and an answer
    or a feedback record can name exactly which graph it was based on.
    """
    canonical = json.dumps({"nodes": nodes, "edges": edges, **({"extra": extra} if extra else {})}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "g" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]


SEQUENCE_METHOD = "smith_waterman_local_blosum62_affine_v0.2"
SIGNIFICANT_EVALUE = 0.001  # predeclared in pipelines/compute_protein_similarity.py


def protein_comparisons(repo_root: Path) -> list[dict[str, Any]]:
    """Pairwise protein comparisons for the gene panel: the BLOSUM62 alignment and, where it passed
    the predeclared mapping gate, the AlphaFold C-alpha superposition. Pairs that did not pass are
    kept with status "not evaluated", so the page can say so instead of implying a difference."""
    seq = {(r["source_gene_symbol"], r["target_gene_symbol"]): r
           for r in read_csv(repo_root / "data/processed/protein_similarity.csv") if r.get("method") == SEQUENCE_METHOD}
    struct = {(r["source_gene_symbol"], r["target_gene_symbol"]): r
              for r in read_csv(repo_root / "data/processed/structure_comparison.csv")}
    out = []
    for key in sorted(set(seq) | set(struct)):
        a, b = seq.get(key, {}), struct.get(key, {})
        evalue = a.get("evalue", "")
        try:
            significant = float(evalue) < SIGNIFICANT_EVALUE
        except ValueError:
            significant = None
        out.append({
            "genes": list(key),
            "proteins": [a.get("source_protein_id") or b.get("source_protein_id", ""), a.get("target_protein_id") or b.get("target_protein_id", "")],
            "sequence": {
                "method": SEQUENCE_METHOD, "identity_pct": a.get("identity_pct", ""), "aligned_residues": a.get("aligned_residues", ""),
                "minimum_coverage_pct": a.get("minimum_coverage_pct", ""), "evalue": evalue, "bitscore": a.get("bitscore", ""),
                "significant": significant, "significant_if_evalue_below": SIGNIFICANT_EVALUE,
            } if a else None,
            "structure": {
                "method": b.get("method", ""), "status": b.get("status", ""), "ca_rmsd_angstrom": b.get("ca_rmsd_angstrom", ""),
                "high_confidence_ca_pairs": b.get("high_confidence_ca_pairs", ""), "plddt_cutoff": b.get("plddt_cutoff", ""),
                "models": [b.get("source_structure_id", ""), b.get("target_structure_id", "")],
                "model_version": b.get("source_model_version", ""), "notes": b.get("notes", ""),
            } if b else None,
        })
    return out


def build_components(repo_root: Path) -> dict[str, str]:
    """Which method and source snapshots went into this graph, read from the pipeline manifests."""
    def manifest(name: str) -> dict[str, Any]:
        path = repo_root / "data" / "manifests" / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    out: dict[str, str] = {}
    method = manifest("disease_similarity_v0.1.json").get("method", "")
    if method:
        out["disease_similarity"] = method.rsplit("_", 1)[-1]
    for key, name, field in (
        ("disease_panel", "cluster_expansion_v0.1.json", "retrieved_at"),
        ("gene_profiles", "gene_profiles_v0.1.json", "retrieved_at"),
        ("clinvar", "gene_variants_v0.1.json", "retrieved_at"),
        ("protein_similarity", "protein_similarity_v0.2.json", "generated_at"),
    ):
        value = str(manifest(name).get(field, ""))[:10]
        if value:
            out[key] = value
    # Source releases, shown on the page: HPO's terms require its version wherever HPO data is displayed.
    sources = manifest("cluster_expansion_v0.1.json").get("sources", {})
    for key, src, field in (("mondo_release", "mondo", "release_tag"), ("hpo_release", "hpo", "release_tag"),
                            ("reactome_release", "reactome", "version"), ("uniprot_release", "uniprot", "release")):
        value = str(sources.get(src, {}).get(field, ""))
        if value:
            out[key] = value
    return out


def build_payload(
    node_rows: Iterable[dict[str, Any]],
    edge_rows: Iterable[dict[str, Any]],
    repo_root: Path = REPO_ROOT,
    source: str = "csv",
) -> dict[str, Any]:
    diseases = {r["disease_id"]: r for r in read_csv(repo_root / "data/processed/diseases.csv")}
    studies = {f"NCT:{r['nct_id']}": r for r in read_csv(repo_root / "data/processed/studies.csv")}
    wording = seed_evidence_wording(repo_root)

    nodes = []
    for row in node_rows:
        props = parse_props(row.get("properties_json"))
        node = {
            "id": row["node_id"],
            "kind": row.get("node_type") or row.get("kind", ""),
            "label": row.get("label", ""),
            "external_id": row.get("external_id", ""),
            "source_url": row.get("source_url", ""),
            "status": row.get("status", ""),
            "props": props,
        }
        synonyms = list(props.get("synonyms", []))
        seed = diseases.get(node["id"])
        if seed:
            synonyms += [s.strip() for s in seed.get("synonyms", "").split(";") if s.strip()]
            node["xrefs"] = [x.strip() for x in seed.get("xrefs", "").split(";") if x.strip()]
        node["synonyms"] = sorted(set(synonyms))
        study = studies.get(node["id"]) or props.get("study")
        if study:
            node["study"] = {
                k: study.get(k, "") for k in (
                    "brief_title", "official_title", "overall_status", "study_type", "phases", "conditions",
                    "lead_sponsor", "study_start_date", "primary_completion_date", "minimum_age", "maximum_age",
                    "source_url", "retrieved_at",
                )
            }
        if node["kind"] == "Evidence":
            key = node["id"].removeprefix("EVIDENCE:")
            if key in wording:
                node["wording"] = wording[key]
        node["search"] = search_terms(node)
        nodes.append(node)

    edges = []
    for row in edge_rows:
        props = parse_props(row.get("properties_json"))
        for field in STRUCTURE_FIELDS:
            if row.get(field):
                props.setdefault(field, row[field])
        edges.append(
            {
                "id": row["edge_id"],
                "type": row.get("edge_type") or row.get("type", ""),
                "source": row["source_id"],
                "target": row["target_id"],
                "assertion_level": row.get("assertion_level", ""),
                "evidence_id": row.get("evidence_id", ""),
                "confidence": row.get("confidence", ""),
                "source_url": row.get("source_url", ""),
                "notes": row.get("notes", ""),
                "limitations": row.get("limitations", ""),
                "props": props,
            }
        )

    comparisons = protein_comparisons(repo_root)
    nodes.sort(key=lambda n: (n["kind"], n["label"].lower()))
    edges.sort(key=lambda e: e["id"])
    kinds: dict[str, int] = {}
    for n in nodes:
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": source,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "kinds": kinds,
            "graph_version": graph_version(nodes, edges, comparisons),
            "build": build_components(repo_root),
            "searched_sources": [
                label for kind, label in (
                    ("Disease", "MONDO disease names, synonyms and cross-references"),
                    ("Gene", "Gene symbols (ClinVar / HPO gene-disease links)"),
                    ("Phenotype", "HPO phenotype annotations"),
                    ("Pathway", "Reactome pathways"),
                    ("Study", "ClinicalTrials.gov seed studies"),
                    ("Organization", "Curated patient organizations"),
                    ("Protein", "Reviewed UniProt proteins"),
                ) if kinds.get(kind)
            ],
        },
        "nodes": nodes,
        "edges": edges,
        "protein_comparisons": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--out-dir", default="demo/data")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    payload = build_payload(read_csv(root / "graph/nodes.csv"), read_csv(root / "graph/edges.csv"), root)
    out = root / args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (out / "graph.json").write_text(text, encoding="utf-8")
    (out / "graph.js").write_text(
        "// Generated by graph/export_graph_json.py - do not edit by hand.\n"
        f"window.RAREPATH_GRAPH = {text};\n",
        encoding="utf-8",
    )
    print(f"Exported {payload['meta']['node_count']} nodes and {payload['meta']['edge_count']} edges "
          f"(graph {payload['meta']['graph_version']}) to {out}")
    structures = root / "data/processed/gene_structures.json"
    variants = root / "data/processed/gene_variants.json"
    if structures.exists():
        data = json.loads(structures.read_text(encoding="utf-8"))
        if variants.exists():  # ClinVar positions ride along with each structure
            for gene, v in json.loads(variants.read_text(encoding="utf-8")).items():
                if gene in data:
                    data[gene]["variants"] = v
        # Loaded by the explorer only when someone opens a gene panel, so the first page load stays small.
        (out / "structures.js").write_text(
            "// Generated by graph/export_graph_json.py from data/processed/gene_structures.json - do not edit by hand.\n"
            "// AlphaFold DB models (CC BY 4.0): C-alpha trace in 0.1 Å units and per-residue pLDDT; ClinVar missense positions.\n"
            f"window.RAREPATH_STRUCTURES = {json.dumps(data, separators=(',', ':'), sort_keys=True)};\n",
            encoding="utf-8",
        )
        print(f"Exported protein structures to {out / 'structures.js'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
