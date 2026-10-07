#!/usr/bin/env python3
"""Score disease pairs by mechanism and phenotype, then cluster the panel.

Offline step. Inputs are the committed CSVs written by
``fetch_cluster_expansion.py``; nothing is downloaded.

Two independent signals are computed for every disease pair:

* **Mechanism** - Jaccard overlap of the Reactome (non-disease) pathways that
  the diseases' Mendelian genes participate in. Shared causal genes are
  reported separately.
* **Phenotype** - simGIC: the information content (IC) of the HPO terms both
  diseases carry, divided by the IC of the terms either carries, after
  propagating annotations up the HPO is_a hierarchy. IC is computed over the
  full HPO annotation corpus, so broad terms ("Seizure") count much less than
  distinctive ones ("Macular cherry-red spot").

The signals are kept apart and every pair receives a plain-language relation
class. A high phenotype score without a mechanism link is labelled a
look-alike, not a neighbor. Louvain community detection is then run three
times (mechanism only, phenotype only, combined) so a reviewer can see what
each signal contributes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

SCRIPT_VERSION = "0.4.0"
METHOD_ID = "disease_similarity_reactome_idf_jaccard_mondo_group_hpo_simgic_v0.4"

# Predeclared gates (recorded in the manifest).
MECHANISM_HIGH = 0.25          # weighted pathway overlap (or shared MONDO group) needed for a mechanism link
MECHANISM_NONE = 0.10          # below this, "no specific shared process" (look-alike if symptoms overlap)
MONDO_GROUP_WEIGHT = 0.6       # two diseases filed under the same MONDO parent in this panel (e.g. GM2 gangliosidosis)
# Two diseases in the same mechanism-defined MONDO class (lysosomal storage disease, RASopathy, ciliopathy).
# Between MECHANISM_NONE and MECHANISM_HIGH: such a pair is never a "look-alike", but is not a neighbour either.
# Added in v0.4 because Reactome's lowest-level pathways split one cascade into steps (PTPN11 upstream and
# RAF1 downstream of RAS share none), which labelled true relatives as look-alikes.
MONDO_CLASS_WEIGHT = 0.15
MONDO_CLASS_IDS = {"MONDO:0002561", "MONDO:0021060", "MONDO:0005308"}
# HPO "Abnormality of metabolism/homeostasis": lab findings such as enzyme activity or substrate build-up.
# They describe the mechanism, so they are left out of the symptom score to keep the two signals independent.
EXCLUDED_PHENOTYPE_BRANCHES = ("HP:0001939",)
PHENOTYPE_HIGH_PERCENTILE = 0.75  # pair must be in the top quarter of phenotype overlap in this panel
SHARED_TERM_MIN_IC = 2.0       # informative shared phenotype: present in < ~13.5% of annotated diseases
SHARED_TERMS_SHOWN = 6
LOUVAIN_SEED = 42
LOUVAIN_RESOLUTION = 1.0

RELATION_TEXT = {
    "same_gene_similar_presentation": "Same causal gene and similar symptoms (subtypes of one condition).",
    "same_gene_different_presentation": "Same causal gene, but a clearly different symptom pattern: one gene can cause different diseases.",
    "mechanism_and_phenotype_neighbor": "Different genes in the same biological pathways, with an overlapping, distinctive symptom pattern.",
    "mechanism_neighbor_different_presentation": "Different genes in the same pathways, but the symptom patterns differ.",
    "phenotype_lookalike_different_mechanism": "Symptoms overlap, but there is no shared gene, only broad biological processes in common and no shared mechanism class: treat as a look-alike, not a research neighbor.",
    "phenotype_neighbor_weak_mechanism": "Distinctive symptoms overlap and they share a biological process or a mechanism-defined disease class, but the specific mechanism link is weak; needs review.",
    "not_linked": "No strong mechanism or phenotype link in this panel.",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def closure(term_id: str, parents: dict[str, list[str]], cache: dict[str, frozenset[str]]) -> frozenset[str]:
    if term_id not in cache:
        result = {term_id}
        for parent in parents.get(term_id, []):
            result |= closure(parent, parents, cache)
        cache[term_id] = frozenset(result)
    return cache[term_id]


def sim_gic(a: set[str], b: set[str], ic: dict[str, float]) -> float:
    union = sum(ic.get(t, 0.0) for t in a | b)
    if union <= 0:
        return 0.0
    return sum(ic.get(t, 0.0) for t in a & b) / union


def weighted_jaccard(a: set[str], b: set[str], weight: dict[str, float]) -> float:
    """Jaccard overlap where each pathway counts by its rarity in the panel (IDF).

    A pathway shared by every panel gene (weight 0) adds nothing; a pathway shared by
    only two genes counts a lot. This stops broad pathways from making everything similar.
    """
    union = sum(weight.get(x, 0.0) for x in a | b)
    return sum(weight.get(x, 0.0) for x in a & b) / union if union > 0 else 0.0


CROSS_FAMILY = "cross-family"


def scoring_gene(row: dict[str, str]) -> bool:
    """Genes that drive the mechanism score: the fetch step's curated flag, else every Mendelian gene."""
    if "used_for_scoring" in row and row["used_for_scoring"] != "":
        return row["used_for_scoring"].lower() == "true"
    return row.get("association_type", "").upper() == "MENDELIAN"


def pathway_rarity(
    gene_set: set[str], gene_paths: dict[str, set[str]]
) -> tuple[dict[str, float], set[str]]:
    """IDF weight of each pathway over ``gene_set``, and the pathways specific enough to count on their own.

    w = ln(genes in set / genes in set that are in the pathway). A pathway is "specific" if it
    involves at most half of the set's genes (and always if it involves two or fewer).
    """
    n_genes = len(gene_set) or 1
    members: dict[str, int] = {}
    for gene in gene_set:
        for pid in gene_paths.get(gene, ()):
            members[pid] = members.get(pid, 0) + 1
    weights = {pid: math.log(n_genes / n) for pid, n in members.items()}
    specific = {pid for pid, n in members.items() if n <= max(2, n_genes / 2)}
    return weights, specific


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def most_informative_shared(
    shared: set[str], parents: dict[str, list[str]], ic: dict[str, float], cache: dict[str, frozenset[str]]
) -> list[str]:
    """Shared terms that are not an ancestor of another shared term, by IC."""
    covered: set[str] = set()
    for term in shared:
        covered |= closure(term, parents, cache) - {term}
    leaves = [t for t in shared if t not in covered and ic.get(t, 0.0) >= SHARED_TERM_MIN_IC]
    return sorted(leaves, key=lambda t: (-ic.get(t, 0.0), t))[:SHARED_TERMS_SHOWN]


def percentile_rank(values: list[float], reference: list[float] | None = None) -> dict[float, float]:
    """Mid-rank percentile of each value within ``reference`` (default: the values themselves)."""
    ordered = sorted(values if reference is None else reference)
    n = len(ordered)
    ranks: dict[float, float] = {}
    for value in set(values):
        below = sum(1 for v in ordered if v < value)
        equal = sum(1 for v in ordered if v == value)
        ranks[value] = (below + 0.5 * equal) / n if n else 0.0
    return ranks


def classify(shared_genes: list[str], mechanism: float, phenotype_high: bool) -> str:
    if shared_genes:
        return "same_gene_similar_presentation" if phenotype_high else "same_gene_different_presentation"
    if mechanism >= MECHANISM_HIGH:
        return "mechanism_and_phenotype_neighbor" if phenotype_high else "mechanism_neighbor_different_presentation"
    if phenotype_high:
        return "phenotype_lookalike_different_mechanism" if mechanism < MECHANISM_NONE else "phenotype_neighbor_weak_mechanism"
    return "not_linked"


def louvain(ids: list[str], weighted_edges: list[tuple[str, str, float]]) -> tuple[dict[str, int], float]:
    try:
        import networkx as nx
        from networkx.algorithms.community import louvain_communities, modularity
    except ImportError as error:  # pragma: no cover - environment guard
        raise SystemExit("Clustering needs networkx: python -m pip install networkx") from error
    graph = nx.Graph()
    graph.add_nodes_from(ids)
    for a, b, w in weighted_edges:
        if w > 0:
            graph.add_edge(a, b, weight=w)
    if graph.number_of_edges() == 0:
        return {node: i for i, node in enumerate(sorted(ids))}, 0.0
    communities = louvain_communities(graph, weight="weight", resolution=LOUVAIN_RESOLUTION, seed=LOUVAIN_SEED)
    # Stable numbering: largest community first, then by smallest member ID.
    ordered = sorted((sorted(c) for c in communities), key=lambda c: (-len(c), c[0]))
    assignment = {node: index for index, members in enumerate(ordered) for node in members}
    return assignment, float(modularity(graph, [set(c) for c in ordered], weight="weight"))


def compute(
    diseases: list[dict[str, str]],
    annotations: list[dict[str, str]],
    term_rows: list[dict[str, str]],
    gene_rows: list[dict[str, str]],
    pathway_rows: list[dict[str, str]],
    hierarchy_rows: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    ids = sorted({d["disease_id"] for d in diseases})
    label = {d["disease_id"]: d["label"] for d in diseases}
    ic = {r["hpo_id"]: float(r["information_content"]) for r in term_rows if r.get("information_content")}
    term_label = {r["hpo_id"]: r["hpo_label"] for r in term_rows}
    parents = {r["hpo_id"]: [p.strip() for p in r["parents"].split(";") if p.strip()] for r in term_rows}
    cache: dict[str, frozenset[str]] = {}

    def excluded(term: str) -> bool:
        return any(branch in closure(term, parents, cache) for branch in EXCLUDED_PHENOTYPE_BRANCHES)

    phenos: dict[str, set[str]] = {i: set() for i in ids}
    direct: dict[str, set[str]] = {i: set() for i in ids}
    dropped_lab_terms = 0
    for a in annotations:
        if a["disease_id"] in phenos:
            if excluded(a["hpo_id"]):
                dropped_lab_terms += 1
                continue
            direct[a["disease_id"]].add(a["hpo_id"])
            phenos[a["disease_id"]] |= closure(a["hpo_id"], parents, cache)

    genes: dict[str, set[str]] = {i: set() for i in ids}
    for g in gene_rows:
        if g["disease_id"] in genes and scoring_gene(g):
            genes[g["disease_id"]].add(g["gene_symbol"])
    family = {d["disease_id"]: d.get("family", "") or "panel" for d in diseases}

    gene_paths: dict[str, set[str]] = {}
    path_label: dict[str, str] = {}
    for p in pathway_rows:
        if p.get("is_in_disease", "false").lower() == "true":
            continue
        gene_paths.setdefault(p["gene_symbol"], set()).add(p["pathway_id"])
        path_label[p["pathway_id"]] = p["pathway_label"]
    paths = {i: set().union(*(gene_paths.get(g, set()) for g in genes[i])) if genes[i] else set() for i in ids}
    # Pathway rarity weight (IDF), measured within the comparison set: a disease family's own genes for
    # pairs inside one family, all panel genes for pairs across families. Adding a new family therefore
    # never changes the scores inside an existing one.
    family_genes: dict[str, set[str]] = {}
    for i in ids:
        family_genes.setdefault(family[i], set()).update(g for g in genes[i] if gene_paths.get(g))
    family_genes[CROSS_FAMILY] = set().union(*family_genes.values()) if family_genes else set()
    rarity = {name: pathway_rarity(members_of, gene_paths) for name, members_of in family_genes.items()}
    # Curated grouping: MONDO parents of each panel disease (within this panel's hierarchy file).
    groups: dict[str, set[str]] = {i: set() for i in ids}
    classes: dict[str, set[str]] = {i: set() for i in ids}
    class_label: dict[str, str] = {}
    for h in hierarchy_rows or []:
        if h.get("child_id") not in groups:
            continue
        is_class = h.get("grouping") == "class" or h["parent_id"] in MONDO_CLASS_IDS
        (classes if is_class else groups)[h["child_id"]].add(h["parent_id"])
        if is_class:
            class_label[h["parent_id"]] = h.get("parent_label", "")

    pairs = []
    for a, b in combinations(ids, 2):
        shared_terms = phenos[a] & phenos[b]
        scope = family[a] if family[a] == family[b] else CROSS_FAMILY
        path_weight, informative = rarity[scope]
        pairs.append(
            {
                "a": a,
                "b": b,
                "scope": scope,
                "phenotype": sim_gic(phenos[a], phenos[b], ic),
                "pathway_overlap": weighted_jaccard(paths[a], paths[b], path_weight),
                "informative": informative,
                "path_weight": path_weight,
                "shared_group": sorted(groups[a] & groups[b]),
                "shared_class": sorted(classes[a] & classes[b]),
                "shared_genes": sorted(genes[a] & genes[b]),
                "shared_pathways": sorted(paths[a] & paths[b]),
                "shared_terms": most_informative_shared(shared_terms, parents, ic, cache),
                "shared_direct": len(direct[a] & direct[b]),
            }
        )

    for p in pairs:
        # Broad pathways (shared by more than half of the comparison set's genes) cannot create a mechanism link on their own.
        if not p["informative"] & set(p["shared_pathways"]):
            p["pathway_overlap"] = min(p["pathway_overlap"], MECHANISM_NONE / 2)
        p["mechanism"] = max(p["pathway_overlap"], MONDO_GROUP_WEIGHT if p["shared_group"] else 0.0,
                             MONDO_CLASS_WEIGHT if p["shared_class"] else 0.0)
        # Show the most specific shared pathways first.
        p["shared_pathways"].sort(key=lambda pid, w=p["path_weight"]: -w.get(pid, 0.0))
    # Phenotype percentiles are also ranked within the comparison set, so the "top quarter" of a family
    # is not diluted by the many unrelated cross-family pairs. Cross-family pairs are ranked against the
    # pooled within-family pairs: they only count as high when they overlap as much as a family's own top
    # quarter does (otherwise the top quarter of mostly unrelated pairs would yield many weak look-alikes).
    within = [p["phenotype"] for p in pairs if p["scope"] != CROSS_FAMILY]
    ranks_by_scope = {
        scope: percentile_rank(
            [p["phenotype"] for p in pairs if p["scope"] == scope],
            within if scope == CROSS_FAMILY and within else None,
        )
        for scope in {p["scope"] for p in pairs}
    }
    pheno_values = [p["phenotype"] for p in pairs]
    rows, mech_edges, pheno_edges, combined_edges = [], [], [], []
    for p in pairs:
        ranks = ranks_by_scope[p["scope"]]
        pct = ranks.get(p["phenotype"], 0.0) if p["phenotype"] > 0 else 0.0
        high = pct >= PHENOTYPE_HIGH_PERCENTILE and p["phenotype"] > 0
        relation = classify(p["shared_genes"], p["mechanism"], high)
        combined = 0.5 * max(p["mechanism"], 1.0 if p["shared_genes"] else 0.0) + 0.5 * pct
        mech_weight = max(p["mechanism"], 1.0 if p["shared_genes"] else 0.0)
        mech_edges.append((p["a"], p["b"], mech_weight if mech_weight >= MECHANISM_HIGH else 0.0))
        pheno_edges.append((p["a"], p["b"], p["phenotype"] if high else 0.0))
        # Look-alikes (symptoms without a shared gene or pathway) never pull diseases into one cluster.
        # Neither does a shared mechanism class on its own (no gene, no series, pathway overlap below the
        # "no specific process" line): it only changes the label, not the communities.
        class_only = (not p["shared_genes"] and not p["shared_group"] and p["pathway_overlap"] < MECHANISM_NONE)
        clusters_together = relation not in ("not_linked", "phenotype_lookalike_different_mechanism") and not class_only
        combined_edges.append((p["a"], p["b"], combined if clusters_together else 0.0))
        rows.append(
            {
                "source_id": p["a"],
                "target_id": p["b"],
                "source_label": label[p["a"]],
                "target_label": label[p["b"]],
                "comparison_set": p["scope"],
                "relation_class": relation,
                "relation_text": RELATION_TEXT[relation],
                "mechanism_score": f"{p['mechanism']:.4f}",
                "pathway_overlap": f"{p['pathway_overlap']:.4f}",
                "shared_mondo_group": "; ".join(p["shared_group"]),
                "shared_mondo_class": "; ".join(f"{c}|{class_label.get(c, '')}" for c in p["shared_class"]),
                "phenotype_score": f"{p['phenotype']:.4f}",
                "phenotype_percentile": f"{pct:.4f}",
                "combined_score": f"{combined:.4f}",
                "shared_genes": "; ".join(p["shared_genes"]),
                "shared_pathways": "; ".join(f"{pid}|{path_label.get(pid, '')}" for pid in p["shared_pathways"]),
                "shared_phenotypes": "; ".join(
                    f"{t}|{term_label.get(t, '')}|{ic.get(t, 0.0):.2f}" for t in p["shared_terms"]
                ),
                "shared_direct_phenotype_count": p["shared_direct"],
                "method": METHOD_ID,
            }
        )
    rows.sort(key=lambda r: -float(r["combined_score"]))

    clusters = {}
    stats: dict[str, object] = {}
    for name, edges in (("mechanism", mech_edges), ("phenotype", pheno_edges), ("combined", combined_edges)):
        assignment, q = louvain(ids, edges)
        clusters[name] = assignment
        stats[f"{name}_modularity"] = round(q, 4)
        stats[f"{name}_cluster_count"] = len(set(assignment.values()))

    role = {d["disease_id"]: d.get("panel_role", "") for d in diseases}
    cluster_rows = [
        {
            "disease_id": i,
            "label": label[i],
            "family": family[i] if family[i] != "panel" else "",
            "panel_role": role[i],
            "genes": "; ".join(sorted(genes[i])),
            "pathway_count": len(paths[i]),
            "phenotype_term_count": len(direct[i]),
            "cluster_combined": f"C{clusters['combined'][i] + 1}",
            "cluster_mechanism": f"M{clusters['mechanism'][i] + 1}",
            "cluster_phenotype": f"P{clusters['phenotype'][i] + 1}",
            "method": METHOD_ID,
        }
        for i in ids
    ]
    cutoffs = {}
    for scope in sorted({p["scope"] for p in pairs}):
        values = sorted(within if scope == CROSS_FAMILY and within else [p["phenotype"] for p in pairs if p["scope"] == scope])
        index = min(len(values) - 1, int(PHENOTYPE_HIGH_PERCENTILE * len(values)))
        cutoffs[scope] = round(values[index], 4)
    stats.update(
        {
            "pairs": len(rows),
            "pairs_by_comparison_set": {s: sum(1 for p in pairs if p["scope"] == s) for s in sorted(cutoffs)},
            "lab_annotations_excluded_from_phenotype": dropped_lab_terms,
            "phenotype_high_cutoff_simgic": cutoffs,
            "relation_class_counts": {
                k: sum(1 for r in rows if r["relation_class"] == k) for k in RELATION_TEXT
            },
        }
    )
    return rows, cluster_rows, stats


SIM_FIELDS = [
    "source_id", "target_id", "source_label", "target_label", "comparison_set", "relation_class", "relation_text",
    "mechanism_score", "pathway_overlap", "shared_mondo_group", "shared_mondo_class", "phenotype_score", "phenotype_percentile",
    "combined_score", "shared_genes",
    "shared_pathways", "shared_phenotypes", "shared_direct_phenotype_count", "method",
]
CLUSTER_FIELDS = [
    "disease_id", "label", "family", "panel_role", "genes", "pathway_count", "phenotype_term_count",
    "cluster_combined", "cluster_mechanism", "cluster_phenotype", "method",
]
INPUTS = {
    "diseases": "cluster_diseases.csv",
    "annotations": "cluster_disease_phenotypes.csv",
    "terms": "cluster_hpo_terms.csv",
    "genes": "cluster_disease_genes.csv",
    "pathways": "cluster_gene_pathways.csv",
}
OPTIONAL_INPUTS = {"hierarchy": "cluster_disease_hierarchy.csv"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    processed = root / "data" / "processed"
    paths = {k: processed / v for k, v in INPUTS.items()}
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise SystemExit(f"Missing inputs (run fetch_cluster_expansion.py first): {missing}")
    loaded = {k: read_csv(p) for k, p in paths.items()}
    rows, cluster_rows, stats = compute(
        loaded["diseases"], loaded["annotations"], loaded["terms"], loaded["genes"], loaded["pathways"],
        read_csv(processed / OPTIONAL_INPUTS["hierarchy"]) if (processed / OPTIONAL_INPUTS["hierarchy"]).exists() else None,
    )
    write_csv(processed / "disease_similarity.csv", rows, SIM_FIELDS)
    write_csv(processed / "disease_clusters.csv", cluster_rows, CLUSTER_FIELDS)
    manifest = {
        "pipeline": "RarePath disease similarity and clustering",
        "script_version": SCRIPT_VERSION,
        "method": METHOD_ID,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "inputs": {name: {"path": f"data/processed/{INPUTS[name]}", "sha256": sha256_file(p)} for name, p in paths.items()},
        "gates": {
            "mechanism_high": MECHANISM_HIGH,
            "mechanism_none": MECHANISM_NONE,
            "mechanism_definition": "max(IDF-weighted Jaccard of Reactome pathways, MONDO_GROUP_WEIGHT if both diseases share a MONDO series parent, MONDO_CLASS_WEIGHT if they share a mechanism-defined MONDO class); pathway overlap is capped below mechanism_none unless at least one shared pathway involves at most half of the comparison set's genes",
            "comparison_set": "pairs inside one disease family are weighted and ranked against that family's genes and pairs; pairs across families are weighted against all panel genes and their phenotype score is ranked against the pooled within-family pairs",
            "scoring_genes": "used_for_scoring flag from the fetch step (Mendelian HPO genes, restricted to curated genes where the panel names them)",
            "mondo_group_weight": MONDO_GROUP_WEIGHT,
            "mondo_class_weight": MONDO_CLASS_WEIGHT,
            "mondo_class_ids": sorted(MONDO_CLASS_IDS),
            "excluded_phenotype_branches": list(EXCLUDED_PHENOTYPE_BRANCHES),
            "phenotype_high_percentile": PHENOTYPE_HIGH_PERCENTILE,
            "shared_term_min_ic": SHARED_TERM_MIN_IC,
            "reactome_disease_pathways_excluded": True,
            "hpo_aspect": "P (phenotypic abnormality), NOT-qualified annotations excluded",
            "louvain_seed": LOUVAIN_SEED,
            "louvain_resolution": LOUVAIN_RESOLUTION,
        },
        "interpretation": (
            "Research-navigation signal only. A shared pathway or symptom pattern does not establish "
            "shared treatment response, trial eligibility or disease equivalence."
        ),
        "results": stats,
    }
    (root / "data" / "manifests" / "disease_similarity_v0.1.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(stats, indent=2))
    for r in cluster_rows:
        print(f"{r['cluster_combined']:>4} {r['cluster_mechanism']:>4} {r['cluster_phenotype']:>4}  {r['label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
