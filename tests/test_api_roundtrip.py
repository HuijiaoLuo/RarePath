"""The Neo4j-backed API must return the same payload shape as the CSV export.

Neo4j is simulated: node/edge properties are produced with the loader's own
flatten_properties(), i.e. exactly what graph/load_neo4j.py writes.
"""

import sys
import types
import unittest
from pathlib import Path

from graph.export_graph_json import build_payload, read_csv
from graph.load_neo4j import STRUCTURAL_EDGE_FIELDS, flatten_properties

REPO = Path(__file__).resolve().parents[1]


class FakeSession:
    def __init__(self, nodes, edges):
        self.nodes, self.edges = nodes, edges

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, *args):
        if query.startswith("MATCH (n:Entity)"):
            out = []
            for row in self.nodes:
                props = flatten_properties(row, {"node_type"})
                props["kind"] = row["node_type"]
                out.append({"p": props})
            return out
        return [
            {"source": r["source_id"], "target": r["target_id"], "type": r["edge_type"],
             "p": flatten_properties(r, STRUCTURAL_EDGE_FIELDS)}
            for r in self.edges
        ]


class ApiRoundTripTests(unittest.TestCase):
    def test_neo4j_payload_matches_csv_payload(self):
        nodes = read_csv(REPO / "graph" / "nodes.csv")
        edges = read_csv(REPO / "graph" / "edges.csv")
        driver = types.SimpleNamespace(session=lambda database=None: FakeSession(nodes, edges), close=lambda: None)
        fake = types.ModuleType("neo4j")
        fake.GraphDatabase = types.SimpleNamespace(driver=lambda *a, **k: driver)
        sys.modules["neo4j"] = fake
        import os
        os.environ["NEO4J_PASSWORD"] = "x"
        try:
            from api import server
            live = server.fetch_from_neo4j()
        finally:
            del sys.modules["neo4j"]
        snapshot = build_payload(nodes, edges, REPO)
        self.assertEqual(live["meta"]["source"], "neo4j")
        strip = lambda p: sorted(({**x} for x in p), key=lambda x: x["id"])
        self.assertEqual(strip(live["nodes"]), strip(snapshot["nodes"]))
        self.assertEqual(strip(live["edges"]), strip(snapshot["edges"]))
        # Same content, same version: an answer or a feedback record names the graph it came from.
        self.assertEqual(live["meta"]["graph_version"], snapshot["meta"]["graph_version"])


if __name__ == "__main__":
    unittest.main()
