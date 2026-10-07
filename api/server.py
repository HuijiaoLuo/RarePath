#!/usr/bin/env python3
"""Serve the explorer with live data from Neo4j and a grounded chat.

    python api/server.py            # http://127.0.0.1:8000/explore.html

Reads NEO4J_URI, NEO4J_USER (or NEO4J_USERNAME), NEO4J_PASSWORD and
NEO4J_DATABASE from the environment, exactly like graph/load_neo4j.py. The
password stays on the server; the browser only ever calls /api/graph.

If Neo4j is unreachable, /api/graph returns 503 and the page falls back to the
exported snapshot in demo/data/graph.js, so the demo never breaks.

The chat (POST /api/chat) uses OPENAI_API_KEY and optional OPENAI_MODEL from the
same environment. The key never reaches the browser. Questions and the facts on
screen are sent to OpenAI with store=False; see api/chat.py for the rules.

Feedback (POST /api/feedback) is a fixed category about one graph record. It has
no free text and the server stores no IP address, so no health information is
collected. Records are appended to data/feedback/feedback.jsonl (git-ignored) for
review with pipelines/review_feedback.py; feedback never changes the graph itself.

Endpoints
  GET  /api/health    -> {"neo4j": bool, "chat": bool, "feedback": true, "graph_version": ...}
  GET  /api/graph     -> same JSON shape as demo/data/graph.json, with meta.source = "neo4j"
  POST /api/chat      -> {"answer", "fact_ids", "follow_ups", "graph_version", ...} grounded in graph facts
  POST /api/feedback  -> {"ok": true} for a validated category about a known record
  GET  /*           -> static files from demo/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from api.chat import ChatError, answer as chat_answer, known_ids  # noqa: E402
from graph.export_graph_json import build_payload, read_csv  # noqa: E402

CACHE_SECONDS = 30
_cache: dict[str, Any] = {"at": 0.0, "payload": None}


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def fetch_from_neo4j() -> dict[str, Any]:
    from neo4j import GraphDatabase  # imported lazily so the static fallback works without the driver

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", os.getenv("NEO4J_USERNAME", "neo4j"))
    password = os.getenv("NEO4J_PASSWORD", "")
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    if not password:
        raise RuntimeError("NEO4J_PASSWORD is not set")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            node_rows = []
            for record in session.run("MATCH (n:Entity) RETURN properties(n) AS p"):
                p = record["p"]
                node_rows.append(
                    {
                        "node_id": p.get("node_id", ""),
                        "node_type": p.get("kind", ""),
                        "label": stringify(p.get("label")),
                        "external_id": stringify(p.get("external_id")),
                        "source_url": stringify(p.get("source_url")),
                        "status": stringify(p.get("status")),
                        "properties_json": p.get("properties_json", ""),
                    }
                )
            edge_rows = []
            query = (
                "MATCH (a:Entity)-[r]->(b:Entity) "
                "RETURN a.node_id AS source, b.node_id AS target, type(r) AS type, properties(r) AS p"
            )
            for record in session.run(query):
                p = dict(record["p"])
                row = {k: stringify(v) for k, v in p.items() if k != "properties_json"}
                row.update(
                    {
                        "edge_id": p.get("edge_id", f"{record['source']}-{record['type']}-{record['target']}"),
                        "source_id": record["source"],
                        "target_id": record["target"],
                        "edge_type": record["type"],
                        "properties_json": p.get("properties_json", ""),
                    }
                )
                edge_rows.append(row)
    finally:
        driver.close()
    payload = build_payload(node_rows, edge_rows, REPO_ROOT, source="neo4j")
    payload["meta"]["neo4j_uri_host"] = uri.split("@")[-1].split("//")[-1].split("/")[0]
    return payload


_csv_cache: dict[str, Any] = {"payload": None}


def graph_for_chat() -> dict[str, Any]:
    """Facts are checked against the source-controlled CSV graph (the source of truth).

    Neo4j is a copy of these CSVs and can lag behind a rebuild, so it is not used here.
    The CSVs are re-read when they change on disk.
    """
    paths = [REPO_ROOT / "graph" / "nodes.csv", REPO_ROOT / "graph" / "edges.csv"]
    stamp = tuple(p.stat().st_mtime for p in paths)
    if _csv_cache["payload"] is None or _csv_cache.get("stamp") != stamp:
        _csv_cache["payload"] = build_payload(read_csv(paths[0]), read_csv(paths[1]), REPO_ROOT)
        _csv_cache["stamp"] = stamp
    return _csv_cache["payload"]


def chat_available() -> bool:
    if not os.getenv("OPENAI_API_KEY"):
        return False
    try:
        import openai  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------- feedback
FEEDBACK_CATEGORIES = {
    "useful": "This helped",
    "relationship_wrong": "The relationship looks wrong",
    "source_broken": "A source link is broken or out of date",
    "missing_resource": "A disease, study or patient group is missing",
    "display_issue": "The protein or variant view looks wrong",
    "answer_unsupported": "The answer says more than its sources",
}
FEEDBACK_TARGETS = {"link", "edge", "gene", "resource", "answer"}
FACT_ID = re.compile(r"^F\d{1,3}$")
VERSION = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
FEEDBACK_PER_MINUTE = 20
_feedback_lock = threading.Lock()
_feedback_times: deque[float] = deque()


def feedback_file() -> Path:
    return Path(os.getenv("RAREPATH_FEEDBACK_FILE", REPO_ROOT / "data" / "feedback" / "feedback.jsonl"))


def validate_feedback(body: Any, graph_payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only fixed fields with known values. Anything else is dropped, never stored."""
    if not isinstance(body, dict):
        raise ChatError("Feedback must be a JSON object")
    category, kind = body.get("category"), body.get("target_kind")
    if category not in FEEDBACK_CATEGORIES:
        raise ChatError("Unknown feedback category")
    if kind not in FEEDBACK_TARGETS:
        raise ChatError("Unknown feedback target")
    known = known_ids(graph_payload)
    gene_labels = {n["label"] for n in graph_payload.get("nodes", []) if n.get("kind") == "Gene"}
    target, focus = str(body.get("target_id", "")), str(body.get("focus_id", ""))
    if not (target in known or (kind == "gene" and target in gene_labels)):
        raise ChatError("Feedback must be about a record in the graph")
    record: dict[str, Any] = {
        "received_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "category": category,
        "target_kind": kind,
        "target_id": target,
        "focus_id": focus if focus in known else "",
        "page_graph_version": str(body.get("graph_version", "")) if VERSION.match(str(body.get("graph_version", ""))) else "",
        "server_graph_version": graph_payload.get("meta", {}).get("graph_version", ""),
    }
    if kind == "answer":
        facts = body.get("fact_ids") if isinstance(body.get("fact_ids"), list) else []
        record["fact_ids"] = [f for f in facts if isinstance(f, str) and FACT_ID.match(f)][:20]
        record["answer_source"] = body.get("answer_source") if body.get("answer_source") in ("openai", "offline") else ""
    return record


def save_feedback(record: dict[str, Any]) -> None:
    now = time.time()
    with _feedback_lock:
        while _feedback_times and now - _feedback_times[0] > 60:
            _feedback_times.popleft()
        if len(_feedback_times) >= FEEDBACK_PER_MINUTE:
            raise ChatError("Too much feedback in the last minute; please try again shortly")
        _feedback_times.append(now)
        path = feedback_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


class Handler(SimpleHTTPRequestHandler):
    def _json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        path = self.path.split("?", 1)[0]
        if path not in ("/api/chat", "/api/feedback"):
            self._json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > (4_000 if path == "/api/feedback" else 200_000):
                raise ChatError("Request is empty or too large")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            graph = graph_for_chat()
            if path == "/api/feedback":
                save_feedback(validate_feedback(body, graph))
                self._json(200, {"ok": True, "graph_version": graph["meta"].get("graph_version", "")})
                return
            result = chat_answer(body, graph)
            result["graph_version"] = graph["meta"].get("graph_version", "")
            self._json(200, result)
        except (ChatError, json.JSONDecodeError, ValueError) as error:
            self._json(400, {"error": str(error)})
        except Exception as error:  # model/network failure: the page falls back to offline answers
            self._json(503, {"error": type(error).__name__ + ": " + str(error)[:300]})

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            body: dict[str, Any] = {"chat": chat_available(), "chat_model": os.getenv("OPENAI_MODEL", "gpt-5"), "feedback": True}
            try:
                body["graph_version"] = graph_for_chat()["meta"].get("graph_version", "")
            except Exception:  # noqa: BLE001 - health must always answer
                body["graph_version"] = ""
            try:
                payload = fetch_from_neo4j() if not _cache["payload"] else _cache["payload"]
                body.update({"neo4j": True, "node_count": payload["meta"]["node_count"]})
            except Exception as error:  # noqa: BLE001
                body.update({"neo4j": False, "neo4j_error": type(error).__name__})
            self._json(200, body)
            return
        if path in ("/api/graph",):
            try:
                if not _cache["payload"] or time.time() - _cache["at"] > CACHE_SECONDS:
                    _cache["payload"] = fetch_from_neo4j()
                    _cache["at"] = time.time()
                self._json(200, _cache["payload"])
            except Exception as error:  # report, never leak credentials
                message = type(error).__name__ + ": " + str(error).replace(os.getenv("NEO4J_PASSWORD", "\0"), "***")
                self._json(503, {"neo4j": False, "error": message, "fallback": "demo/data/graph.js"})
            return
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/explore.html")
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self) -> None:
        # Always revalidate, so a rebuilt page or data file shows up on a normal refresh.
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv  # optional: a local, git-ignored .env

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass
    handler = partial(Handler, directory=str(REPO_ROOT / "demo"))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"RarePath guide: http://{args.host}:{args.port}/explore.html  (Ctrl+C to stop)")
    print(f"Chat: {'on, model ' + os.getenv('OPENAI_MODEL', 'gpt-5') if chat_available() else 'offline answers only (set OPENAI_API_KEY and pip install openai)'}")
    print(f"Neo4j: {'NEO4J_PASSWORD set' if os.getenv('NEO4J_PASSWORD') else 'not configured, using the CSV snapshot'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
