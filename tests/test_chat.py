"""Grounded chat: unknown facts are dropped, citations are validated, no network is used."""

import json
import types
import unittest

from api import chat

GRAPH = {"nodes": [{"id": "MONDO:1"}, {"id": "GENE_SYMBOL:GLB1"}], "edges": [{"id": "EDGE:A"}, {"id": "EDGE:B"}]}


class FakeClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.responses = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(output_text=json.dumps(self.reply))


def body(**extra):
    return {
        "question": "Who is closest to GM1?",
        "focus_label": "GM1 gangliosidosis",
        "facts": [
            {"id": "F1", "text": "GM1 is caused by GLB1.", "refs": ["EDGE:A"]},
            {"id": "F2", "text": "Shares pathways with GM2.", "refs": ["EDGE:B"], "computed": True},
            {"id": "F3", "text": "Invented fact.", "refs": ["EDGE:NOT_IN_GRAPH"]},
        ],
        **extra,
    }


class ChatTests(unittest.TestCase):
    def test_only_graph_backed_facts_reach_the_model(self):
        client = FakeClient({"answer": "GLB1 [F1].", "fact_ids": ["F1"], "answered_from_facts": True, "follow_ups": []})
        chat.answer(body(), GRAPH, client)
        prompt = client.calls[0]["input"][1]["content"][0]["text"]
        self.assertIn("[F1]", prompt)
        self.assertIn("(computed by RarePath) Shares pathways", prompt)
        self.assertNotIn("Invented fact", prompt)
        self.assertFalse(client.calls[0]["store"])
        self.assertTrue(client.calls[0]["text"]["format"]["strict"])

    def test_citations_to_unknown_facts_are_removed(self):
        client = FakeClient({"answer": "Close to GM2 [F2, F9]. Made up [F7].", "fact_ids": ["F2", "F9"],
                             "answered_from_facts": True, "follow_ups": ["a", "b", "c", "d"]})
        out = chat.answer(body(), GRAPH, client)
        self.assertEqual(out["answer"], "Close to GM2 [F2]. Made up .")
        self.assertEqual(out["fact_ids"], ["F2"])
        self.assertEqual(len(out["follow_ups"]), 3)

    def test_no_verifiable_facts_is_an_error_not_a_guess(self):
        with self.assertRaises(chat.ChatError):
            chat.answer({"question": "hi", "facts": [{"id": "F1", "text": "x", "refs": ["nope"]}]}, GRAPH, FakeClient({}))

    def test_missing_key_is_reported(self):
        import os
        old = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with self.assertRaises(chat.ChatError):
                chat.answer(body(), GRAPH)
        finally:
            if old is not None:
                os.environ["OPENAI_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
