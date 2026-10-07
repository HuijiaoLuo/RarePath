"""The chat evaluation set (evals/chat_cases.json): system cases, and the offline baseline.

System cases run the real local server with a fake model, so they need no key and no network.
"""

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from api import chat, server
from evals import run_chat_eval as ev
from tests.test_chat import FakeClient

ROOT = Path(__file__).resolve().parents[1]
GM1 = "MONDO:0018149"


@contextmanager
def env(**values):
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


@contextmanager
def local_server(fake_reply=None):
    """The real handler; with fake_reply, the model call goes to a fake client instead of OpenAI."""
    original = server.chat_answer
    if fake_reply is not None:
        server.chat_answer = lambda body, graph: chat.answer(body, graph, FakeClient(fake_reply))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(ROOT / "demo")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        server.chat_answer = original
        httpd.shutdown()
        httpd.server_close()


def call(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def gm1_body(facts, question="Who is closest to GM1?"):
    return {"question": question, "focus_id": GM1, "focus_label": "GM1 gangliosidosis", "history": [], "facts": facts}


@unittest.skipUnless(ev.FACTS.exists(), "no fact snapshot; run python evals/capture_facts.py")
class SystemCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = ev.snapshot()["focus"][GM1]
        cls.graph = server.graph_for_chat()

    def test_unknown_citations_are_removed(self):
        reply = {"answer": "GM2 is closest [F1, F99]. Also [F98].", "fact_ids": ["F1", "F99"], "answered_from_facts": True, "follow_ups": []}
        out = chat.answer(gm1_body(self.facts), self.graph, FakeClient(reply))
        self.assertEqual(out["fact_ids"], ["F1"])
        self.assertNotIn("F99", out["answer"])
        self.assertNotIn("F98", out["answer"])

    def test_facts_without_graph_references_are_dropped(self):
        client = FakeClient({"answer": "ok [F1].", "fact_ids": ["F1"], "answered_from_facts": True, "follow_ups": []})
        forged = {"id": "F90", "text": "GM1 is cured by drug X.", "refs": ["EDGE:DOES-NOT-EXIST"]}
        chat.answer(gm1_body(self.facts + [forged]), self.graph, client)
        prompt = client.calls[0]["input"][1]["content"][0]["text"]
        self.assertNotIn("drug X", prompt)
        self.assertIn(self.facts[0]["text"][:40], prompt)

    def test_answers_carry_the_graph_version(self):
        version = self.graph["meta"]["graph_version"]
        self.assertEqual(ev.snapshot()["graph_version"], version, "evals/facts.json is stale: run python evals/capture_facts.py")
        reply = {"answer": "GM2 [F1].", "fact_ids": ["F1"], "answered_from_facts": True, "follow_ups": []}
        with local_server(reply) as base:
            status, out = call(base + "/api/chat", gm1_body(self.facts))
        self.assertEqual(status, 200)
        self.assertEqual(out["graph_version"], version)

    def test_no_key_is_reported_not_guessed(self):
        with env(OPENAI_API_KEY=None), local_server() as base:
            _, health = call(base + "/api/health")
            status, out = call(base + "/api/chat", gm1_body(self.facts))
        self.assertFalse(health["chat"])
        self.assertEqual(status, 400)
        self.assertIn("OPENAI_API_KEY", out["error"])

    def test_neo4j_down_falls_back(self):
        reply = {"answer": "GM2 [F1].", "fact_ids": ["F1"], "answered_from_facts": True, "follow_ups": []}
        server._cache["payload"] = None
        with env(NEO4J_PASSWORD=None), local_server(reply) as base:
            status, out = call(base + "/api/graph")
            self.assertEqual(status, 503)
            self.assertEqual(out["fallback"], "demo/data/graph.js")
            self.assertNotIn("password", json.dumps(out).lower().replace("neo4j_password is not set", ""))
            status, answer = call(base + "/api/chat", gm1_body(self.facts))
        self.assertEqual(status, 200, "chat facts are checked against the CSV graph, so Neo4j being down does not stop the chat")
        self.assertEqual(answer["fact_ids"], ["F1"])


@unittest.skipUnless(ev.FACTS.exists(), "no fact snapshot; run python evals/capture_facts.py")
class OfflineBaseline(unittest.TestCase):
    def test_cases_are_well_formed(self):
        cases = ev.load_cases()
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        self.assertGreaterEqual(len(cases), 15)
        for c in cases:
            if c["kind"] == "question":
                self.assertTrue(c.get("must_cite") or c.get("abstain") or c.get("defer_to") or c.get("switch_to"), c["id"])
            else:
                self.assertTrue(c["covered_by"].startswith("tests.test_chat_eval.SystemCases."), c["id"])

    def test_offline_answers_pass_every_question(self):
        report = ev.run(live=False)
        failed = {r["id"]: r["problems"] for r in report["cases"] if not r["passed"]}
        self.assertEqual(failed, {}, "offline answers broke an eval case; see python evals/run_chat_eval.py")

    def test_scorer_agrees_with_human_verdicts_on_real_answers(self):
        """Real gpt-5 answers from two runs, each judged by hand. The scorer must reach the same verdict on every one."""
        cases, facts = {c["id"]: c for c in ev.load_cases()}, ev.snapshot()["focus"]
        paths = sorted((ROOT / "tests/fixtures/eval").glob("*.json"))
        self.assertGreaterEqual(len(paths), 2)
        for path in paths:
            answers = json.loads(path.read_text(encoding="utf-8"))["answers"]
            disagree = {a["id"]: ev.score(cases[a["id"]], a, facts[cases[a["id"]]["focus"]])["problems"]
                        for a in answers if ev.score(cases[a["id"]], a, facts[cases[a["id"]]["focus"]])["passed"] != a["human_pass"]}
            self.assertEqual(disagree, {}, path.name)

    def test_a_refusal_is_not_a_forbidden_claim(self):
        case = next(c for c in ev.load_cases() if c["id"] == "Q13")
        refusal = {"answer": "We cannot tell from these facts whether your daughter can join. Ask the study team.", "fact_ids": []}
        claim = {"answer": "Your daughter can join this study. Ask the study team.", "fact_ids": []}
        self.assertTrue(ev.score(case, refusal, [])["passed"])
        self.assertFalse(ev.score(case, claim, [])["passed"])
        q15 = next(c for c in ev.load_cases() if c["id"] == "Q15")
        hedge = {"answer": "They look alike, but the biology is different. It is risky to assume the same treatments will help. Ask your doctor.", "fact_ids": []}
        masked = {"answer": "They look alike, but are not identical and the biology is different. The same treatments will help. Ask your doctor.", "fact_ids": []}
        self.assertTrue(ev.score(q15, hedge, [])["passed"])
        self.assertFalse(ev.score(q15, masked, [])["passed"], "a negation in an earlier sentence must not excuse a claim")

    def test_scorer_catches_overclaiming(self):
        case = next(c for c in ev.load_cases() if c["id"] == "Q12")
        bad = {"answer": "Yes, the gene therapy will work for him because GM1 and GM2 share a pathway.", "fact_ids": []}
        self.assertFalse(ev.score(case, bad, [])["passed"])


if __name__ == "__main__":
    unittest.main()
