"""A frozen demo candidate detects any change to the files a visitor sees or a result depends on."""

import io
import json
import unittest
from contextlib import redirect_stdout

from pipelines import freeze_candidate as fc
from tests._support import make_tmp, remove_tmp


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp()
        self.record = self.tmp / "candidate.json"
        files = fc.tracked_files()
        self.record.write_text(json.dumps({"name": "test", "frozen_at": "now", "graph": fc.graph_summary(), "files": files}), encoding="utf-8")

    def tearDown(self):
        remove_tmp(self.tmp)

    def check(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = fc.check(self.record)
        return code, out.getvalue()

    def test_unchanged_build_is_intact(self):
        code, text = self.check()
        self.assertEqual(code, 0, text)

    def test_a_changed_file_is_reported(self):
        data = json.loads(self.record.read_text(encoding="utf-8"))
        data["files"]["demo/explore.html"] = "0" * 64
        data["graph"]["graph_version"] = "gold"
        self.record.write_text(json.dumps(data), encoding="utf-8")
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("changed: demo/explore.html", text)
        self.assertIn("graph version gold ->", text)

    def test_the_page_carries_the_graph_version(self):
        self.assertEqual(fc.page_graph_version(), fc.graph_summary()["graph_version"],
                         "demo/data/graph.js is out of date: run python graph/export_graph_json.py")


if __name__ == "__main__":
    unittest.main()
