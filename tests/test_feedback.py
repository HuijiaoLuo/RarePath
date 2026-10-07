"""Feedback is a fixed category about a known record: no free text, no identity, never written to the graph."""

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from api import server
from graph.export_graph_json import build_payload, read_csv
from pipelines.review_feedback import load, load_decisions, queue, record_decision
from tests._support import make_tmp, remove_tmp

REPO = Path(__file__).resolve().parents[1]


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = build_payload(read_csv(REPO / "graph" / "nodes.csv"), read_csv(REPO / "graph" / "edges.csv"), REPO)
        cls.edge = cls.graph["edges"][0]["id"]
        cls.disease = next(n["id"] for n in cls.graph["nodes"] if n["kind"] == "Disease")

    def setUp(self):
        self.tmp = make_tmp()
        self.file = self.tmp / "feedback.jsonl"
        os.environ["RAREPATH_FEEDBACK_FILE"] = str(self.file)
        server._feedback_times.clear()

    def tearDown(self):
        os.environ.pop("RAREPATH_FEEDBACK_FILE", None)
        remove_tmp(self.tmp)

    def test_only_fixed_fields_are_kept(self):
        body = {"category": "relationship_wrong", "target_kind": "edge", "target_id": self.edge, "focus_id": self.disease,
                "graph_version": "g123", "comment": "my son has seizures", "email": "a@b.c", "question": "is it treatable?"}
        record = server.validate_feedback(body, self.graph)
        self.assertEqual(set(record), {"received_at", "category", "target_kind", "target_id", "focus_id",
                                       "page_graph_version", "server_graph_version"})
        self.assertNotIn("seizures", json.dumps(record))
        self.assertEqual(record["server_graph_version"], self.graph["meta"]["graph_version"])

    def test_unknown_category_or_record_is_rejected(self):
        with self.assertRaises(server.ChatError):
            server.validate_feedback({"category": "free_text", "target_kind": "edge", "target_id": self.edge}, self.graph)
        with self.assertRaises(server.ChatError):
            server.validate_feedback({"category": "useful", "target_kind": "edge", "target_id": "my child's name"}, self.graph)

    def test_answer_feedback_keeps_fact_ids_not_text(self):
        record = server.validate_feedback({"category": "answer_unsupported", "target_kind": "answer", "target_id": self.disease,
                                           "fact_ids": ["F1", "F12", "the answer text", 7], "answer_source": "openai"}, self.graph)
        self.assertEqual(record["fact_ids"], ["F1", "F12"])

    def test_saved_records_feed_the_review_queue(self):
        for cat in ("relationship_wrong", "relationship_wrong", "useful"):
            server.save_feedback(server.validate_feedback({"category": cat, "target_kind": "edge", "target_id": self.edge}, self.graph))
        items = queue(load(self.file), self.graph)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["counts"], {"relationship_wrong": 2, "useful": 1})
        self.assertEqual(items[0]["problems"], 2)

    def test_review_loop_closes_when_the_graph_version_changes(self):
        record = server.validate_feedback({"category": "relationship_wrong", "target_kind": "edge", "target_id": self.edge}, self.graph)
        server.save_feedback(record)
        decisions = self.tmp / "decisions.csv"
        status = lambda graph: queue(load(self.file), graph, load_decisions(decisions))[0]
        self.assertEqual(status(self.graph)["status"], "new")
        record_decision(decisions, "edge", self.edge, "confirmed_issue", self.graph["meta"]["graph_version"], "HPO term wrong")
        self.assertEqual(status(self.graph)["status"], "confirmed_issue")
        record_decision(decisions, "edge", self.edge, "fixed_in_next_graph", self.graph["meta"]["graph_version"])
        waiting = status(self.graph)
        self.assertEqual(waiting["status"], "fixed_in_next_graph")
        self.assertTrue(waiting["notes"] and "rebuild" in waiting["notes"][0])
        rebuilt = {**self.graph, "meta": {**self.graph["meta"], "graph_version": "gnewversion"}}
        done = status(rebuilt)
        self.assertEqual(done["status"], "fixed")
        self.assertFalse(done["open"])
        with self.assertRaises(ValueError):
            record_decision(decisions, "edge", self.edge, "deleted", "g1")

    def test_rate_limit(self):
        record = server.validate_feedback({"category": "useful", "target_kind": "edge", "target_id": self.edge}, self.graph)
        for _ in range(server.FEEDBACK_PER_MINUTE):
            server.save_feedback(record)
        with self.assertRaises(server.ChatError):
            server.save_feedback(record)

    def test_graph_version_ignores_build_time_and_tracks_content(self):
        again = build_payload(read_csv(REPO / "graph" / "nodes.csv"), read_csv(REPO / "graph" / "edges.csv"), REPO)
        self.assertEqual(again["meta"]["graph_version"], self.graph["meta"]["graph_version"])
        edges = read_csv(REPO / "graph" / "edges.csv")[1:]
        changed = build_payload(read_csv(REPO / "graph" / "nodes.csv"), edges, REPO)
        self.assertNotEqual(changed["meta"]["graph_version"], self.graph["meta"]["graph_version"])

    def test_http_endpoint_and_health(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(REPO / "demo")))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        post = lambda body: urllib.request.urlopen(urllib.request.Request(
            base + "/api/feedback", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}), timeout=10)
        try:
            ok = json.loads(post({"category": "source_broken", "target_kind": "edge", "target_id": self.edge}).read())
            self.assertTrue(ok["ok"])
            with self.assertRaises(urllib.error.HTTPError) as bad:
                post({"category": "source_broken", "target_kind": "edge", "target_id": "not-a-record"})
            self.assertEqual(bad.exception.code, 400)
            self.assertEqual(len(load(self.file)), 1)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
