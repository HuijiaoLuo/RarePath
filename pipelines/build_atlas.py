#!/usr/bin/env python3
"""Run the cluster layer end to end, then validate and export the graph.

    python pipelines/build_atlas.py              # fetch + compute + sync + validate + export
    python pipelines/build_atlas.py --offline    # skip the network fetch, recompute from committed CSVs
    python pipelines/build_atlas.py --load       # ...and load into Neo4j (needs NEO4J_* env vars)

Each step is a separate script and can be run on its own.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    print(f"\n$ python {' '.join(args)}", flush=True)
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="Do not fetch; reuse data/processed/cluster_*.csv")
    parser.add_argument("--load", action="store_true", help="Also load into Neo4j (with --prune)")
    args = parser.parse_args()
    if not args.offline:
        run("pipelines/fetch_cluster_expansion.py")
        run("pipelines/fetch_gene_profiles.py")
        run("pipelines/fetch_clinvar_variants.py")
    run("pipelines/compute_disease_similarity.py")
    run("pipelines/check_cluster_benchmark.py")
    run("pipelines/sync_cluster_to_graph.py")
    run("pipelines/sync_curated_resources.py")
    run("graph/load_neo4j.py")
    run("graph/export_graph_json.py")
    if args.load:
        run("graph/load_neo4j.py", "--load", "--prune")
    print("\nDone. Open demo/explore.html, or run: python api/server.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode)
