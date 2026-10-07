#!/usr/bin/env python3
"""Merge the phenotype/mechanism cluster layer into graph/nodes.csv and edges.csv.

Ownership rules (so the script is safe to re-run):

* every edge it writes has an ``EDGE:CLX-`` ID; every evidence node an
  ``EVIDENCE:CLX-`` ID; every other new node has status ``cluster_expansion``;
* existing nodes are never removed or relabelled. Cluster membership is added to
  their ``properties_json`` under the key ``cluster`` and replaced on re-run;
* a curated edge that already exists outside this layer (same source, type and
  target) is not duplicated.

Does not contact Neo4j. Run ``python graph/load_neo4j.py`` afterwards.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_VERSION = "0.1.0"
OWNED_STATUS = "cluster_expansion"
NODE_BASE = ["node_id", "node_type", "label", "external_id", "source_url", "status"]
EDGE_BASE = ["edge_id", "source_id", "edge_type", "target_id", "assertion_level", "evidence_id",
             "confidence", "source_url", "notes"]
EXTRA_NODE_FIELDS = ["properties_json"]
EXTRA_EDGE_FIELDS = ["limitations", "properties_json"]

TOP_PHENOTYPES_PER_DISEASE = 8
MAX_BRIDGE_PHENOTYPES = 40
BRIDGE_MIN_IC = 2.0

EDGE_TYPE = {
    "same_gene_similar_presentation": ("SHARES_CAUSAL_GENE", "high"),
    "same_gene_different_presentation": ("SHARES_CAUSAL_GENE", "high"),
    "mechanism_and_phenotype_neighbor": ("MECHANISM_NEIGHBOR", "medium"),
    "mechanism_neighbor_different_presentation": ("MECHANISM_NEIGHBOR", "low"),
    "phenotype_neighbor_weak_mechanism": ("PHENOTYPE_NEIGHBOR", "medium"),
    "phenotype_lookalike_different_mechanism": ("PHENOTYPE_LOOKALIKE", "low"),
}
LIMITATIONS = {
    "SHARES_CAUSAL_GENE": "A shared gene does not mean the same variants, severity or treatment response.",
    "MECHANISM_NEIGHBOR": (
        "Pathway overlap is computed from Reactome membership of the causal genes. It suggests a shared "
        "biological process to investigate; it is not evidence that a therapy transfers."
    ),
    "PHENOTYPE_NEIGHBOR": "Strong symptom overlap and one specific shared process, but weak overall pathway overlap; needs expert review before use.",
    "PHENOTYPE_LOOKALIKE": (
        "Counterexample: symptoms overlap, but the diseases share no gene and only broad biological "
        "processes (pathways most of the panel's genes take part in). Do not treat as a research "
        "neighbor on symptoms alone."
    ),
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = [{k: (v or "") for k, v in row.items() if k is not None} for row in reader]
        return list(reader.fieldnames or []), rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})


def merged_fields(existing: list[str], base: list[str], extra: list[str]) -> list[str]:
    fields = list(existing) if existing else list(base)
    for field in base + extra:
        if field not in fields:
            fields.append(field)
    return fields


def props(row: dict[str, str]) -> dict:
    try:
        return json.loads(row.get("properties_json") or "{}")
    except json.JSONDecodeError:
        return {}


def dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def split_pairs(value: str, keys: list[str]) -> list[dict[str, str]]:
    items = []
    for chunk in filter(None, (c.strip() for c in value.split(";"))):
        parts = chunk.split("|")
        items.append({k: (parts[i] if i < len(parts) else "") for i, k in enumerate(keys)})
    return items


def scoring_gene(row: dict[str, str]) -> bool:
    """Same rule as compute_disease_similarity.scoring_gene: the fetch step's flag, else Mendelian."""
    if row.get("used_for_scoring", "") != "":
        return row["used_for_scoring"].lower() == "true"
    return row.get("association_type", "").upper() == "MENDELIAN"


def build(inputs: dict[str, list[dict[str, str]]], manifest: dict) -> tuple[list[dict], list[dict]]:
    """Return (nodes, edges) owned by this layer. Pure function for testing."""
    hpo_tag = manifest.get("sources", {}).get("hpo", {}).get("release_tag", "")
    mondo_tag = manifest.get("sources", {}).get("mondo", {}).get("release_tag", "")
    reactome_version = manifest.get("sources", {}).get("reactome", {}).get("version", "")
    hpo_urls = manifest.get("sources", {}).get("hpo", {}).get("urls", {})
    sim_manifest = inputs.get("_sim_manifest", [{}])[0] if inputs.get("_sim_manifest") else {}

    nodes: list[dict] = []
    edges: list[dict] = []
    evidence = {
        "CLX-MONDO": ("MONDO disease identity and is_a hierarchy", f"https://github.com/monarch-initiative/mondo/releases/tag/{mondo_tag}", mondo_tag),
        "CLX-HPO-ANNOT": ("HPO disease-phenotype annotations (phenotype.hpoa)", hpo_urls.get("phenotype.hpoa", "https://hpo.jax.org/data/annotations"), hpo_tag),
        "CLX-HPO-G2D": ("HPO gene-disease associations (genes_to_disease.txt)", hpo_urls.get("genes_to_disease.txt", "https://hpo.jax.org/data/annotations"), hpo_tag),
        "CLX-REACTOME": ("Reactome lowest-level pathway membership via UniProt", "https://reactome.org/ContentService", f"Reactome v{reactome_version}"),
        "CLX-SIMDIS": ("Computed disease similarity: Reactome pathway Jaccard + HPO simGIC, Louvain clusters", "data/processed/disease_similarity.csv", sim_manifest.get("method", "disease_similarity")),
    }
    for key, (label, url, version) in evidence.items():
        nodes.append({
            "node_id": f"EVIDENCE:{key}", "node_type": "Evidence", "label": label, "external_id": version,
            "source_url": url, "status": "inferred_computational" if key == "CLX-SIMDIS" else "curated_source",
            "properties_json": dumps({"source_version": version, **({"gates": sim_manifest.get("gates", {})} if key == "CLX-SIMDIS" else {})}),
        })

    clusters = {r["disease_id"]: r for r in inputs["clusters"]}
    for d in inputs["diseases"]:
        c = clusters.get(d["disease_id"], {})
        nodes.append({
            "node_id": d["disease_id"], "node_type": "Disease", "label": d["label"], "external_id": d["disease_id"],
            "source_url": f"https://monarchinitiative.org/{d['disease_id']}", "status": OWNED_STATUS,
            "properties_json": dumps({
                "synonyms": [s.strip() for s in d.get("synonyms", "").split(";") if s.strip()],
                "hpo_disease_id": d.get("hpo_disease_id", ""),
                "family": d.get("family", ""),
                "cluster": {
                    "panel_role": d.get("panel_role", ""), "panel_rationale": d.get("panel_rationale", ""),
                    "combined": c.get("cluster_combined", ""), "mechanism": c.get("cluster_mechanism", ""),
                    "phenotype": c.get("cluster_phenotype", ""),
                },
            }),
        })

    # Series parents (e.g. "Noonan syndrome") that are not panel diseases themselves get a node of their own.
    panel_ids = {d["disease_id"] for d in inputs["diseases"]}
    # Mechanism classes (e.g. "RASopathy") are scoring context only: drawing them as parents would merge
    # whole families into one community in the guide, so they get no node or IS_A edge.
    hierarchy = [h for h in inputs["hierarchy"] if h.get("grouping", "series") != "class"]
    family_of = {d["disease_id"]: d.get("family", "") for d in inputs["diseases"]}
    for parent_id in sorted({h["parent_id"] for h in hierarchy} - panel_ids):
        h = next(x for x in hierarchy if x["parent_id"] == parent_id)
        families = sorted({family_of.get(x["child_id"], "") for x in hierarchy if x["parent_id"] == parent_id} - {""})
        nodes.append({
            "node_id": parent_id, "node_type": "Disease", "label": h.get("parent_label", parent_id), "external_id": parent_id,
            "source_url": f"https://monarchinitiative.org/{parent_id}", "status": OWNED_STATUS,
            "properties_json": dumps({"disease_group": True, **({"family": families[0]} if len(families) == 1 else {})}),
        })

    # Hierarchy: direct is_a, plus a transitive link to a seed parent only when no direct parent is in scope.
    direct_children = {h["child_id"] for h in hierarchy if h["relation"] == "is_a"}
    for h in hierarchy:
        if h["relation"] != "is_a" and h["child_id"] in direct_children:
            continue
        edges.append({
            "edge_id": f"EDGE:CLX-ISA-{h['child_id']}-{h['parent_id']}", "source_id": h["child_id"], "edge_type": "IS_A",
            "target_id": h["parent_id"], "assertion_level": "curated", "evidence_id": "CLX-MONDO", "confidence": "high",
            "source_url": f"https://monarchinitiative.org/{h['child_id']}",
            "notes": f"MONDO {h['relation'].replace('_', ' ')} ({h.get('mondo_release_tag', '')}).",
            "_parent_label": h.get("parent_label", ""),
        })

    genes: dict[str, str] = {}
    for g in inputs["genes"]:
        if not scoring_gene(g):
            continue
        genes[g["gene_symbol"]] = g.get("ncbi_gene_id", "")
        edges.append({
            "edge_id": f"EDGE:CLX-GENE-{g['disease_id']}-{g['gene_symbol']}", "source_id": g["disease_id"],
            "edge_type": "HAS_GENE", "target_id": f"GENE_SYMBOL:{g['gene_symbol']}", "assertion_level": "curated",
            "evidence_id": "CLX-HPO-G2D", "confidence": "high",
            "source_url": f"https://hpo.jax.org/browse/disease/{g['hpo_disease_id']}",
            "notes": f"Mendelian gene-disease association in HPO ({g.get('source', '')}).",
        })
    profiles = {r["gene_symbol"]: r for r in inputs.get("gene_profiles", [])}
    for symbol, ncbi in sorted(genes.items()):
        props: dict = {"ncbi_gene_id": ncbi}
        prof = profiles.get(symbol)
        if prof:
            props["protein"] = {
                "name": prof.get("protein_name", ""), "uniprot": prof.get("uniprot_accession", ""),
                "length": int(prof["length"]) if prof.get("length", "").isdigit() else None,
                "function": prof.get("function", ""), "location": prof.get("subcellular_location", ""),
                "uniprot_release": prof.get("uniprot_release", ""), "retrieved_at": prof.get("retrieved_at", ""),
                "structure_status": prof.get("structure_status", ""),
                **({"alphafold": {"model_id": prof["alphafold_model_id"], "version": prof.get("alphafold_version", ""),
                                  "mean_plddt": float(prof["alphafold_mean_plddt"]), "model_url": prof.get("alphafold_model_url", "")}}
                   if prof.get("alphafold_model_id") else {}),
            }
        nodes.append({
            "node_id": f"GENE_SYMBOL:{symbol}", "node_type": "Gene", "label": symbol, "external_id": ncbi,
            "source_url": f"https://www.ncbi.nlm.nih.gov/gene/{ncbi.split(':')[-1]}" if ncbi else "",
            "status": OWNED_STATUS, "properties_json": dumps(props),
        })

    # Pathways: keep the ones shared by at least two panel genes (the mechanism bridges).
    pathway_genes: dict[str, set[str]] = {}
    pathway_label: dict[str, str] = {}
    pathway_size: dict[str, str] = {}
    for p in inputs["pathways"]:
        if p.get("is_in_disease", "false").lower() == "true" or p["gene_symbol"] not in genes:
            continue
        pathway_genes.setdefault(p["pathway_id"], set()).add(p["gene_symbol"])
        pathway_label[p["pathway_id"]] = p["pathway_label"]
        if p.get("pathway_size_human"):
            pathway_size[p["pathway_id"]] = p["pathway_size_human"]
    for pid, members in sorted(pathway_genes.items()):
        if len(members) < 2:
            continue
        nodes.append({
            "node_id": f"REACTOME:{pid}", "node_type": "Pathway", "label": pathway_label[pid], "external_id": pid,
            "source_url": f"https://reactome.org/content/detail/{pid}", "status": OWNED_STATUS,
            "properties_json": dumps({"panel_genes": sorted(members),
                                      **({"human_proteins": int(pathway_size[pid])} if pid in pathway_size else {})}),
        })
        for symbol in sorted(members):
            edges.append({
                "edge_id": f"EDGE:CLX-PW-{symbol}-{pid}", "source_id": f"GENE_SYMBOL:{symbol}",
                "edge_type": "PARTICIPATES_IN", "target_id": f"REACTOME:{pid}", "assertion_level": "curated",
                "evidence_id": "CLX-REACTOME", "confidence": "high",
                "source_url": f"https://reactome.org/content/detail/{pid}",
                "notes": f"{symbol} protein is a participant in this Reactome pathway.",
            })

    # Phenotypes: each disease's most informative annotations plus directly shared bridges.
    ic = {t["hpo_id"]: float(t["information_content"]) for t in inputs["terms"] if t.get("information_content")}
    label = {t["hpo_id"]: t["hpo_label"] for t in inputs["terms"]}
    by_disease: dict[str, list[dict[str, str]]] = {}
    for a in inputs["annotations"]:
        by_disease.setdefault(a["disease_id"], []).append(a)
    carriers: dict[str, set[str]] = {}
    for a in inputs["annotations"]:
        carriers.setdefault(a["hpo_id"], set()).add(a["disease_id"])
    keep: set[str] = set()
    for rows in by_disease.values():
        ranked = sorted({r["hpo_id"] for r in rows}, key=lambda t: (-ic.get(t, 0.0), t))
        keep.update(ranked[:TOP_PHENOTYPES_PER_DISEASE])
    bridges = sorted((t for t, ds in carriers.items() if len(ds) >= 2 and ic.get(t, 0.0) >= BRIDGE_MIN_IC),
                     key=lambda t: (-ic.get(t, 0.0), t))[:MAX_BRIDGE_PHENOTYPES]
    keep.update(bridges)
    for term in sorted(keep):
        nodes.append({
            "node_id": term, "node_type": "Phenotype", "label": label.get(term, term), "external_id": term,
            "source_url": f"https://hpo.jax.org/browse/term/{term}", "status": OWNED_STATUS,
            "properties_json": dumps({"information_content": round(ic.get(term, 0.0), 3),
                                      "panel_disease_count": len(carriers.get(term, set()))}),
        })
    seen_pheno: set[tuple[str, str]] = set()
    for a in inputs["annotations"]:
        key = (a["disease_id"], a["hpo_id"])
        if a["hpo_id"] not in keep or key in seen_pheno:
            continue
        seen_pheno.add(key)
        detail = ", ".join(filter(None, [f"frequency {a['frequency']}" if a.get("frequency") else "",
                                         f"reference {a['reference']}" if a.get("reference") else ""]))
        edges.append({
            "edge_id": f"EDGE:CLX-PH-{a['disease_id']}-{a['hpo_id']}", "source_id": a["disease_id"],
            "edge_type": "HAS_PHENOTYPE", "target_id": a["hpo_id"], "assertion_level": "curated",
            "evidence_id": "CLX-HPO-ANNOT", "confidence": "high",
            "source_url": f"https://hpo.jax.org/browse/disease/{a['hpo_disease_id']}",
            "notes": f"HPO annotation ({a.get('evidence', '')}){': ' + detail if detail else ''}.",
            "properties_json": dumps({"information_content": round(ic.get(a["hpo_id"], 0.0), 3),
                                      "frequency": a.get("frequency", ""), "reference": a.get("reference", "")}),
        })

    for s in inputs["similarity"]:
        mapping = EDGE_TYPE.get(s["relation_class"])
        if not mapping:
            continue
        edge_type, confidence = mapping
        shared_pathways = split_pairs(s.get("shared_pathways", ""), ["id", "label"])
        shared_phenotypes = split_pairs(s.get("shared_phenotypes", ""), ["id", "label", "ic"])
        edges.append({
            "edge_id": f"EDGE:CLX-SIM-{s['source_id']}-{s['target_id']}", "source_id": s["source_id"],
            "edge_type": edge_type, "target_id": s["target_id"], "assertion_level": "inferred",
            "evidence_id": "CLX-SIMDIS", "confidence": confidence, "source_url": "",
            "notes": s["relation_text"],
            "limitations": LIMITATIONS[edge_type],
            "properties_json": dumps({
                "relation_class": s["relation_class"], "mechanism_score": float(s["mechanism_score"]),
                "phenotype_score": float(s["phenotype_score"]), "phenotype_percentile": float(s["phenotype_percentile"]),
                "combined_score": float(s["combined_score"]),
                "shared_genes": [g.strip() for g in s.get("shared_genes", "").split(";") if g.strip()],
                "shared_pathways": shared_pathways, "shared_phenotypes": shared_phenotypes,
                "comparison_set": s.get("comparison_set", ""),
                "shared_mondo_group": [g.strip() for g in s.get("shared_mondo_group", "").split(";") if g.strip()],
                "shared_mondo_class": split_pairs(s.get("shared_mondo_class", ""), ["id", "label"]),
                "method": s.get("method", ""), "undirected": True,
            }),
        })
    return nodes, edges


DOWNSTREAM_EDGE_PREFIX = "EDGE:CUR-"


def synchronize(node_rows: list[dict], edge_rows: list[dict], owned_nodes: list[dict], owned_edges: list[dict]):
    retained_nodes = [n for n in node_rows
                      if n.get("status") != OWNED_STATUS and not n["node_id"].startswith("EVIDENCE:CLX-")]
    retained_edges = [e for e in edge_rows if not e["edge_id"].startswith("EDGE:CLX-")]
    index = {n["node_id"]: n for n in retained_nodes}
    for n in retained_nodes:  # strip previous cluster annotation from pre-existing nodes
        p = props(n)
        if "cluster" in p or "protein" in p:
            p.pop("cluster", None)
            p.pop("protein", None)
            n["properties_json"] = dumps(p) if p else ""
    added_nodes = []
    for n in owned_nodes:
        if n["node_id"] in index:
            existing = index[n["node_id"]]
            new_props = props(n)
            merged = props(existing)
            for key in ("synonyms", "hpo_disease_id", "ncbi_gene_id", "family", "disease_group"):
                if key in new_props and key not in merged:
                    merged[key] = new_props[key]
            if "protein" in new_props:  # refreshed on every run
                merged["protein"] = new_props["protein"]
            if "cluster" in new_props:
                merged["cluster"] = new_props["cluster"]
            existing["properties_json"] = dumps(merged) if merged else ""
            if not existing.get("external_id") and n.get("external_id"):
                existing["external_id"] = n["external_id"]
            continue
        index[n["node_id"]] = n
        added_nodes.append(n)
    existing_triples = {(e["source_id"], e["edge_type"], e["target_id"]) for e in retained_edges}
    added_edges = []
    missing = []
    for e in owned_edges:
        if (e["source_id"], e["edge_type"], e["target_id"]) in existing_triples:
            continue
        if e["source_id"] not in index or e["target_id"] not in index:
            missing.append(e["edge_id"])
            continue
        e = {k: v for k, v in e.items() if not k.startswith("_")}
        added_edges.append(e)
    if missing:
        raise ValueError(f"Cluster edges point to nodes that are not in the graph: {missing[:5]}")
    # Links from the curated-resources layer (EDGE:CUR-) depend on panel diseases. If a disease left the
    # panel, drop its links here; sync_curated_resources.py reports the gap when it runs next.
    dangling = [e for e in retained_edges if e["edge_id"].startswith(DOWNSTREAM_EDGE_PREFIX)
                and (e["source_id"] not in index or e["target_id"] not in index)]
    if dangling:
        print(f"Dropped {len(dangling)} curated-resource links to diseases no longer in the panel; "
              "re-run pipelines/sync_curated_resources.py.", file=sys.stderr)
        retained_edges = [e for e in retained_edges if e not in dangling]
    return retained_nodes + added_nodes, retained_edges + added_edges, len(added_nodes), len(added_edges)


INPUTS = {
    "diseases": "cluster_diseases.csv",
    "hierarchy": "cluster_disease_hierarchy.csv",
    "annotations": "cluster_disease_phenotypes.csv",
    "terms": "cluster_hpo_terms.csv",
    "genes": "cluster_disease_genes.csv",
    "pathways": "cluster_gene_pathways.csv",
    "similarity": "disease_similarity.csv",
    "clusters": "disease_clusters.csv",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    processed = root / "data" / "processed"
    inputs = {}
    for key, name in INPUTS.items():
        path = processed / name
        if not path.exists():
            raise SystemExit(f"Missing {path}. Run fetch_cluster_expansion.py and compute_disease_similarity.py first.")
        inputs[key] = read_csv(path)[1]
    manifest = json.loads((root / "data/manifests/cluster_expansion_v0.1.json").read_text(encoding="utf-8"))
    profiles_path = processed / "gene_profiles.csv"
    if profiles_path.exists():  # optional: written by fetch_gene_profiles.py
        inputs["gene_profiles"] = read_csv(profiles_path)[1]
    sim_manifest_path = root / "data/manifests/disease_similarity_v0.1.json"
    if sim_manifest_path.exists():
        inputs["_sim_manifest"] = [json.loads(sim_manifest_path.read_text(encoding="utf-8"))]

    nodes_path, edges_path = root / "graph/nodes.csv", root / "graph/edges.csv"
    node_fields, node_rows = read_csv(nodes_path)
    edge_fields, edge_rows = read_csv(edges_path)
    owned_nodes, owned_edges = build(inputs, manifest)
    nodes, edges, n_added, e_added = synchronize(node_rows, edge_rows, owned_nodes, owned_edges)
    write_csv(nodes_path, merged_fields(node_fields, NODE_BASE, EXTRA_NODE_FIELDS), nodes)
    write_csv(edges_path, merged_fields(edge_fields, EDGE_BASE, EXTRA_EDGE_FIELDS), edges)
    summary = {
        "pipeline": "RarePath cluster layer graph synchronization",
        "script_version": SCRIPT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "added_nodes": n_added,
        "added_edges": e_added,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "edge_types_added": sorted({e["edge_type"] for e in owned_edges}),
    }
    (root / "data/manifests/graph_cluster_sync_v0.1.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f"Cluster graph sync failed: {error}", file=sys.stderr)
        sys.exit(1)
