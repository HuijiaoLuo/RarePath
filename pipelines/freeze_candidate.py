#!/usr/bin/env python3
"""Freeze the current build as a named demo candidate, or check that nothing has drifted since.

    python pipelines/freeze_candidate.py                    # run checks, tests and the chat eval; write docs/demo_candidate.json
    python pipelines/freeze_candidate.py --name dc-2        # choose the candidate's name
    python pipelines/freeze_candidate.py --check            # compare today's files with the frozen record

A candidate is only written when everything passes: 23/23 biology checks, every test
(0 skipped), every chat-eval case, and no problems in the ClinVar manifest. The record
holds the graph version, the SHA-256 of every file a visitor sees or a result depends
on, and the results, so a user test or a screenshot can name exactly what it showed.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RECORD = ROOT / "docs" / "demo_candidate.json"
TRACKED = [
    "demo/explore.html", "demo/index.html", "demo/data/graph.js", "demo/data/structures.js",
    "graph/nodes.csv", "graph/edges.csv", "evals/chat_cases.json", "evals/facts.json",
]
TRACKED_GLOBS = ["data/curated/*.csv", "data/manifests/*.json", "docs/img/*.png"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tracked_files() -> dict[str, str]:
    paths = [ROOT / p for p in TRACKED] + [p for g in TRACKED_GLOBS for p in sorted(ROOT.glob(g))]
    return {p.relative_to(ROOT).as_posix(): sha256(p) for p in paths if p.is_file()}


def graph_summary() -> dict:
    from graph.export_graph_json import build_payload, read_csv

    meta = build_payload(read_csv(ROOT / "graph/nodes.csv"), read_csv(ROOT / "graph/edges.csv"), ROOT)["meta"]
    return {k: meta[k] for k in ("graph_version", "build", "node_count", "edge_count", "kinds")}


def page_graph_version() -> str:
    text = (ROOT / "demo/data/graph.js").read_text(encoding="utf-8")
    payload = json.loads(text[text.index("{"): text.rindex("}") + 1])
    return payload.get("meta", {}).get("graph_version", "")


def git_state() -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        if commit.returncode == 0:
            return {"commit": commit.stdout.strip(), "uncommitted_changes": bool(dirty.stdout.strip())}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"commit": "", "uncommitted_changes": None}


def run_tests() -> dict:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):  # the pipelines under test print progress
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped)}


def collect() -> tuple[dict, list[str]]:
    from evals import run_chat_eval
    from pipelines.check_cluster_benchmark import run as checks

    problems: list[str] = []
    graph = graph_summary()
    if page_graph_version() != graph["graph_version"]:
        problems.append(f"demo/data/graph.js is graph {page_graph_version() or 'without a version'}, the CSVs are {graph['graph_version']}: "
                        "run python graph/export_graph_json.py")
    bio = checks(ROOT / "data" / "processed")
    passed = sum(1 for c in bio if c[1])
    if passed != len(bio):
        problems.append(f"biology checks: {passed}/{len(bio)} pass")
    variants = json.loads((ROOT / "data/manifests/gene_variants_v0.1.json").read_text(encoding="utf-8"))
    if variants.get("problems"):
        problems.append("ClinVar manifest lists problems")
    tests = run_tests()
    if tests["failures"] or tests["errors"] or tests["skipped"]:
        problems.append(f"tests: {tests['failures']} failed, {tests['errors']} errors, {tests['skipped']} skipped (needs 0/0/0)")
    try:
        report = run_chat_eval.run(live=False)
        ev = {"questions": len(report["cases"]), "passed": sum(r["passed"] for r in report["cases"])}
        if ev["passed"] != ev["questions"]:
            problems.append(f"chat eval: {ev['passed']}/{ev['questions']} questions pass")
    except SystemExit as stale:
        ev = {"questions": 0, "passed": 0}
        problems.append(str(stale))
    record = {
        "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "graph": graph,
        "results": {
            "biology_checks": {"run": len(bio), "passed": passed},
            "clinvar": {"variants": variants.get("variants"), "genes": variants.get("genes"), "problems": len(variants.get("problems", []))},
            "tests": tests,
            "chat_eval_offline": ev,
        },
        "files": tracked_files(),
        "environment": {"python": platform.python_version(), "platform": platform.system(), **git_state()},
    }
    return record, problems


def check(record_path: Path) -> int:
    if not record_path.exists():
        print(f"No frozen candidate at {record_path.relative_to(ROOT)}; run without --check first.")
        return 1
    frozen = json.loads(record_path.read_text(encoding="utf-8"))
    drift = []
    now_version = graph_summary()["graph_version"]
    if now_version != frozen["graph"]["graph_version"]:
        drift.append(f"graph version {frozen['graph']['graph_version']} -> {now_version}")
    current = tracked_files()
    for path, digest in frozen["files"].items():
        if path not in current:
            drift.append(f"missing: {path}")
        elif current[path] != digest:
            drift.append(f"changed: {path}")
    drift += [f"new: {p}" for p in current if p not in frozen["files"]]
    name = frozen.get("name", "candidate")
    if drift:
        print(f"{name} has drifted ({len(drift)}):")
        for d in drift:
            print(f"  - {d}")
        return 1
    print(f"{name} is intact: graph {now_version}, {len(current)} files unchanged since {frozen['frozen_at']}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="")
    parser.add_argument("--check", action="store_true", help="compare the current files with the frozen record")
    parser.add_argument("--record", default=str(RECORD))
    args = parser.parse_args()
    if args.check:
        return check(Path(args.record))
    print("Running biology checks, tests and the chat eval (about a minute)...")
    record, problems = collect()
    if problems:
        print("Not frozen. Fix these first:")
        for p in problems:
            print(f"  - {p}")
        return 1
    record = {"name": args.name or f"demo-candidate-{record['frozen_at'][:10]}", **record}
    Path(args.record).write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    r = record["results"]
    print(f"Frozen {record['name']}: graph {record['graph']['graph_version']}, "
          f"{r['biology_checks']['passed']}/{r['biology_checks']['run']} checks, {r['tests']['run']} tests, "
          f"{r['chat_eval_offline']['passed']}/{r['chat_eval_offline']['questions']} eval questions, {len(record['files'])} files -> {Path(args.record).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
