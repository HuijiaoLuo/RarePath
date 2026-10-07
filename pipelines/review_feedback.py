#!/usr/bin/env python3
"""Review feedback collected by api/server.py, and record each decision.

    python pipelines/review_feedback.py                       # the open queue
    python pipelines/review_feedback.py --all                 # include closed items
    python pipelines/review_feedback.py --set EDGE:CLX-SIM-... confirmed_issue --note "HPO term is wrong"
    python pipelines/review_feedback.py --set EDGE:CLX-SIM-... fixed_in_next_graph --note "pipeline fix in v0.5"

Statuses:
    new                  nobody has looked yet (no decision recorded)
    reviewing            someone is checking the source
    confirmed_issue      the source shows the record is wrong
    rejected             the source supports the record as it is
    fixed_in_next_graph  the data or pipeline was fixed; closed once the graph version changes

Feedback never edits the graph. A person checks the source, fixes the pipeline or
data/curated/, and rebuilds; the rebuild changes graph_version, which closes the loop:

    user flags a record -> fixed category -> person checks the source
    -> data or method fixed -> graph rebuilt -> graph_version changes

The raw feedback (data/feedback/) is git-ignored. Decisions are appended to
data/curated/feedback_decisions.csv, which is committed: it holds record IDs, a
status and the reviewer's note, never anything a user typed.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from graph.export_graph_json import build_payload, read_csv  # noqa: E402

DEFAULT = REPO_ROOT / "data" / "feedback" / "feedback.jsonl"
DECISIONS = REPO_ROOT / "data" / "curated" / "feedback_decisions.csv"
STATUSES = ("new", "reviewing", "confirmed_issue", "rejected", "fixed_in_next_graph")
OPEN = {"new", "reviewing", "confirmed_issue"}
FIELDS = ["decided_at", "target_kind", "target_id", "status", "graph_version", "note"]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def load(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("category") and row.get("target_id"):
            rows.append(row)
    return rows


def load_decisions(path: Path) -> dict[str, dict]:
    """The latest decision per record. The file is append-only, so earlier decisions stay as history."""
    latest: dict[str, dict] = {}
    for row in read_csv(path):
        if row.get("status") in STATUSES and row.get("target_id"):
            latest[row["target_id"]] = row
    return latest


def record_decision(path: Path, target_kind: str, target_id: str, status: str, graph_version: str, note: str = "") -> dict:
    if status not in STATUSES[1:]:
        raise ValueError(f"status must be one of {', '.join(STATUSES[1:])}")
    row = {"decided_at": now(), "target_kind": target_kind, "target_id": target_id, "status": status,
           "graph_version": graph_version, "note": " ".join(note.split())[:300]}
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    return row


def queue(rows: list[dict], graph: dict, decisions: dict[str, dict] | None = None) -> list[dict]:
    """One entry per record: category counts, review status, and what the graph version says about it."""
    decisions = decisions or {}
    labels = {n["id"]: n["label"] for n in graph.get("nodes", [])}
    edges = {e["id"]: e for e in graph.get("edges", [])}
    current = graph.get("meta", {}).get("graph_version", "")
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(r.get("target_kind", ""), r["target_id"])].append(r)
    out = []
    for (kind, target), rs in grouped.items():
        e = edges.get(target)
        name = f"{labels.get(e['source'], e['source'])} → {labels.get(e['target'], e['target'])}" if e else labels.get(target, target)
        counts = Counter(r["category"] for r in rs)
        problems = sum(n for c, n in counts.items() if c != "useful")
        d = decisions.get(target)
        status = d["status"] if d else "new"
        notes = []
        if d and status == "fixed_in_next_graph":
            if current and d.get("graph_version") and current != d["graph_version"]:
                status = "fixed"
                notes.append(f"graph changed {d['graph_version']} → {current}")
            else:
                notes.append("waiting for a rebuild")
        later = [r for r in rs if d and r.get("received_at", "") > d.get("decided_at", "") and r["category"] != "useful"]
        if later and status in ("rejected", "fixed", "fixed_in_next_graph"):
            notes.append(f"{len(later)} new report(s) since the decision")
        if not (target in labels or target in edges or kind == "gene"):
            notes.append("no longer in the graph")
        out.append({
            "target_kind": kind, "target_id": target, "name": name, "counts": dict(counts), "problems": problems,
            "status": status, "open": status in OPEN or bool(later), "notes": notes,
            "decision_note": d.get("note", "") if d else "",
            "last_seen": max(r.get("received_at", "") for r in rs),
        })
    out.sort(key=lambda x: x["last_seen"], reverse=True)     # newest first ...
    out.sort(key=lambda x: -x["problems"])                    # ... within the most-flagged ...
    return sorted(out, key=lambda x: not x["open"])           # ... with open items on top


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=str(DEFAULT), help="feedback JSONL written by api/server.py")
    parser.add_argument("--decisions", default=str(DECISIONS))
    parser.add_argument("--all", action="store_true", help="also list closed items")
    parser.add_argument("--set", nargs=2, metavar=("TARGET_ID", "STATUS"), help="record a decision")
    parser.add_argument("--note", default="", help="reviewer's note for --set (what the source showed)")
    args = parser.parse_args()
    graph = build_payload(read_csv(REPO_ROOT / "graph/nodes.csv"), read_csv(REPO_ROOT / "graph/edges.csv"), REPO_ROOT)
    version = graph["meta"]["graph_version"]
    rows = load(Path(args.file))

    if args.set:
        target, status = args.set
        kinds = [r.get("target_kind", "") for r in rows if r["target_id"] == target]
        kind = kinds[-1] if kinds else ("edge" if any(e["id"] == target for e in graph["edges"]) else "node")
        try:
            row = record_decision(Path(args.decisions), kind, target, status, version, args.note)
        except ValueError as error:
            parser.error(str(error))
        print(f"Recorded: {row['target_id']} -> {row['status']} (graph {version})")
        return 0

    if not rows:
        print(f"No feedback in {args.file}")
        return 0
    items = queue(rows, graph, load_decisions(Path(args.decisions)))
    shown = items if args.all else [i for i in items if i["open"]]
    print(f"{len(rows)} feedback records about {len(items)} items; {sum(i['open'] for i in items)} open; current graph {version}\n")
    for item in shown:
        counts = ", ".join(f"{c} {n}" for c, n in sorted(item["counts"].items(), key=lambda x: -x[1]))
        extra = "; ".join(item["notes"] + ([f"note: {item['decision_note']}"] if item["decision_note"] else []))
        print(f"- [{item['status']}] {item['name']} ({item['target_kind']} {item['target_id']}): {counts}{' · ' + extra if extra else ''}")
    if len(shown) < len(items):
        print(f"\n{len(items) - len(shown)} closed item(s) hidden; use --all to see them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
