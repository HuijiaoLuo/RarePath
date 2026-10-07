#!/usr/bin/env python3
"""Check the disease clusters against biology that is already well established.

These are sanity checks, not tuning targets: each one is a textbook relationship the
clustering must reproduce (or a known non-relationship it must not invent). Run after
compute_disease_similarity.py:

    python pipelines/check_cluster_benchmark.py

Exits with status 1 if any check fails.

How checks are added: a new disease family first gets *predictions*, written down
before its data is scored. They are reported but do not fail the build. After one
review on real data they become enforced checks here (or are documented as misses
in docs/CLUSTER_EXPANSION.md). The RASopathy and ciliopathy predictions (12/12 held
on the first real run) were promoted this way. Two further checks came from that
review and are marked as such: they guard the v0.4 fix and were not predeclared.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

G1, G2, G3 = "GM1 gangliosidosis type 1", "GM1 gangliosidosis type 2", "GM1 gangliosidosis type 3"
TS, SH, AB = "Tay-Sachs disease", "Sandhoff disease", "Tay-Sachs disease AB variant"
GA = ("Gaucher disease type I", "Gaucher disease type II", "Gaucher disease type III")
MA, MB = "mucopolysaccharidosis type 4A", "mucopolysaccharidosis type 4B"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def run(processed: Path) -> list[tuple[str, bool, str]]:
    sim = read_rows(processed / "disease_similarity.csv")
    clusters = {r["label"]: r["cluster_combined"] for r in read_rows(processed / "disease_clusters.csv")}

    def pair(a: str, b: str) -> dict[str, str]:
        return next(r for r in sim if {r["source_label"], r["target_label"]} == {a, b})

    def together(*labels: str) -> bool:
        return len({clusters[x] for x in labels}) == 1

    checks: list[tuple[str, bool, str]] = []
    checks.append(("The three GM1 types cluster together (same gene, GLB1)", together(G1, G2, G3), ""))
    checks.append(("Tay-Sachs, Sandhoff and the AB variant cluster together (MONDO: GM2 gangliosidosis)", together(TS, SH, AB), ""))
    checks.append(("Gaucher types I-III cluster together (same gene, GBA1)", together(*GA), ""))
    canavan = clusters["Canavan disease"]
    checks.append(("Canavan disease (not lysosomal) stays in its own cluster", sum(c == canavan for c in clusters.values()) == 1, ""))
    r = pair(G1, MB)
    checks.append(("GM1 type 1 vs Morquio B: same gene, different disease", r["relation_class"] == "same_gene_different_presentation", r["relation_class"]))
    r = pair(MA, MB)
    checks.append(("Morquio A vs B share a mechanism (keratan sulfate breakdown)", float(r["mechanism_score"]) >= 0.25, f"mechanism {r['mechanism_score']}"))
    r = pair(G2, SH)
    checks.append(("GM1 type 2 vs Sandhoff is a mechanism neighbor", r["relation_class"].startswith("mechanism"), r["relation_class"]))
    r = pair(G2, "Fabry disease")
    checks.append(("GM1 type 2 vs Fabry is not a strong neighbor (only broad pathways shared)", float(r["mechanism_score"]) < 0.25, f"mechanism {r['mechanism_score']}"))
    return checks + family_checks(processed)


NS = ("Noonan syndrome 1", "Noonan syndrome 3", "Noonan syndrome 4", "Noonan syndrome 5", "Noonan syndrome 7")
BBS = ("Bardet-Biedl syndrome 1", "Bardet-Biedl syndrome 2", "Bardet-Biedl syndrome 10")
CEP290 = ("Joubert syndrome 5", "Meckel syndrome, type 4", "Senior-Loken syndrome 6")


def predictions(processed: Path) -> list[tuple[str, bool, str]]:
    """Predeclared, not yet enforced checks for the next disease family (none pending)."""
    return []


def family_checks(processed: Path) -> list[tuple[str, bool, str]]:
    """RASopathy and ciliopathy checks: predeclared in v0.3, enforced since review (skipped if the families are absent)."""
    sim = read_rows(processed / "disease_similarity.csv")
    rows = read_rows(processed / "disease_clusters.csv")
    clusters = {r["label"]: r["cluster_combined"] for r in rows}
    family = {r["label"]: r.get("family", "") for r in rows}
    if not all(x in clusters for x in (*NS, *BBS, *CEP290)):
        return []

    def pair(a: str, b: str) -> dict[str, str]:
        return next(r for r in sim if {r["source_label"], r["target_label"]} == {a, b})

    def together(*labels: str) -> bool:
        return len({clusters[x] for x in labels}) == 1

    out: list[tuple[str, bool, str]] = []
    out.append(("RAS: Noonan syndrome types 1, 3, 4, 5 and 7 cluster together", together(*NS), ""))
    r = pair("Noonan syndrome 1", "LEOPARD syndrome 1")
    out.append(("RAS: Noonan 1 vs LEOPARD 1 share their causal gene (PTPN11)", r["relation_class"].startswith("same_gene"), r["relation_class"]))
    out.append(("RAS: Costello (HRAS) and CFC 3 (MAP2K1) cluster with Noonan 1 (RAS-MAPK)",
                together("Noonan syndrome 1", "Costello syndrome", "cardiofaciocutaneous syndrome 3"), ""))
    r = pair("neurofibromatosis type 1", "Legius syndrome")
    out.append(("RAS: NF1 vs Legius (both brake RAS signalling) share a mechanism", float(r["mechanism_score"]) >= 0.25, f"mechanism {r['mechanism_score']}"))
    r = pair("Noonan syndrome 1", "Aarskog-Scott syndrome, X-linked")
    out.append(("RAS: Aarskog-Scott (FGD1) is not a mechanism neighbor of Noonan 1", float(r["mechanism_score"]) < 0.25, f"{r['relation_class']}, mechanism {r['mechanism_score']}"))
    out.append(("RAS: Aarskog-Scott does not cluster with Noonan 1",
                clusters["Aarskog-Scott syndrome, X-linked"] != clusters["Noonan syndrome 1"], ""))
    out.append(("Cilia: Bardet-Biedl syndromes 1, 2 and 10 cluster together", together(*BBS), ""))
    cep = [pair(a, b) for i, a in enumerate(CEP290) for b in CEP290[i + 1:]]
    out.append(("Cilia: CEP290 diseases share their gene, and at least one pair presents differently",
                all(r["relation_class"].startswith("same_gene") for r in cep)
                and any(r["relation_class"] == "same_gene_different_presentation" for r in cep),
                ", ".join(r["relation_class"] for r in cep)))
    r = pair("Bardet-Biedl syndrome 1", "Prader-Willi syndrome")
    out.append(("Cilia: Prader-Willi vs BBS1 is a look-alike (obesity, hypogonadism), not a neighbor",
                r["relation_class"] == "phenotype_lookalike_different_mechanism", r["relation_class"]))
    out.append(("Cilia: Prader-Willi does not cluster with BBS1",
                clusters["Prader-Willi syndrome"] != clusters["Bardet-Biedl syndrome 1"], ""))
    r = pair("Bardet-Biedl syndrome 1", "Alstrom syndrome")
    out.append(("Cilia: Alstrom vs BBS1 overlap strongly in symptoms (top quarter of the family)",
                float(r["phenotype_percentile"]) >= 0.75, f"percentile {float(r['phenotype_percentile']):.2f}"))
    by_cluster: dict[str, set[str]] = {}
    for label, c in clusters.items():
        by_cluster.setdefault(c, set()).add(family.get(label, ""))
    mixed = sorted(c for c, fams in by_cluster.items() if len(fams) > 1)
    out.append(("No combined cluster mixes disease families", not mixed, ", ".join(mixed)))
    # Added after the v0.3 review (not predeclared): true relatives must not be called look-alikes.
    r = pair("Noonan syndrome 5", "LEOPARD syndrome 1")
    out.append(("[v0.4] Noonan 5 vs LEOPARD 1 is not a look-alike (RAF1 also causes LEOPARD type 2)",
                r["relation_class"] != "phenotype_lookalike_different_mechanism", r["relation_class"]))
    r = pair("Joubert syndrome 2", "Meckel syndrome, type 4")
    out.append(("[v0.4] Joubert 2 vs Meckel 4 is not a look-alike (TMEM216 also causes Meckel type 2)",
                r["relation_class"] != "phenotype_lookalike_different_mechanism", r["relation_class"]))
    r = pair("Krabbe disease", "Canavan disease")
    out.append(("Krabbe vs Canavan (not lysosomal) stays a look-alike", r["relation_class"] == "phenotype_lookalike_different_mechanism", r["relation_class"]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    checks = run(Path(args.repo_root) / "data" / "processed")
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{f' ({detail})' if detail else ''}")
    passed = sum(ok for _, ok, _ in checks)
    print(f"{passed}/{len(checks)} checks pass")
    predicted = predictions(Path(args.repo_root) / "data" / "processed")
    if predicted:
        print("\nPredeclared predictions for the new families (reported, not enforced):")
        for name, ok, detail in predicted:
            print(f"{'HIT ' if ok else 'MISS'}  {name}{f' ({detail})' if detail else ''}")
        print(f"{sum(ok for _, ok, _ in predicted)}/{len(predicted)} predictions hold")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
