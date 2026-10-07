"""The fetch step must reuse local downloads and never silently re-download Mondo."""

import shutil
import unittest
from pathlib import Path
from unittest import mock

from pipelines import fetch_cluster_expansion as fetch
from tests._support import make_tmp, needs_networkx, remove_tmp

FIXTURES = Path(__file__).parent / "fixtures" / "cluster"


class LocalFirstTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp()
        self.repo_raw = self.tmp / "repo" / "data" / "raw"
        self.sibling_raw = self.tmp / "data" / "raw"

    def tearDown(self):
        remove_tmp(self.tmp)

    def test_truncated_mondo_is_skipped_and_sibling_copy_used(self):
        broken = self.repo_raw / "mondo" / "v2" / "mondo.json"
        broken.parent.mkdir(parents=True)
        broken.write_text('{"graphs": [', encoding="utf-8")
        good = self.sibling_raw / "mondo" / "v1" / "mondo.json"
        good.parent.mkdir(parents=True)
        shutil.copy(FIXTURES / "mondo.json", good)
        with mock.patch.object(fetch, "request_bytes") as network:
            mondo, tag, path = fetch.load_mondo([self.repo_raw, self.sibling_raw])
        network.assert_not_called()
        self.assertEqual(path, good)
        self.assertEqual(tag, "v1")
        self.assertIn("graphs", mondo)

    def test_no_local_mondo_and_no_flag_means_no_download(self):
        with mock.patch.object(fetch, "request_bytes") as network:
            with self.assertRaises(fetch.FetchError) as ctx:
                fetch.load_mondo([self.repo_raw])
        network.assert_not_called()
        self.assertIn("--download-mondo", str(ctx.exception))

    def test_local_hpo_is_reused_without_network(self):
        target = self.sibling_raw / "hpo" / "v2026-09-01"
        target.mkdir(parents=True)
        for name in fetch.HPO_ASSETS:
            shutil.copy(FIXTURES / name, target / name)
        with mock.patch.object(fetch, "request_bytes") as network:
            tag, paths, _ = fetch.hpo_release([self.repo_raw, self.sibling_raw])
        network.assert_not_called()
        self.assertEqual(tag, "v2026-09-01")
        self.assertEqual(paths["hp.obo"], target / "hp.obo")

    def test_api_responses_are_cached(self):
        cache = self.tmp / "reactome"
        payload = b'[{"stId": "R-HSA-1", "displayName": "x", "isInDisease": false}]'
        with mock.patch.object(fetch, "request_bytes", return_value=(payload, {})) as network:
            first = fetch.reactome_pathways("P1", cache)
            second = fetch.reactome_pathways("P1", cache)
        self.assertEqual(network.call_count, 1)
        self.assertEqual(first, second)
        self.assertFalse(list(cache.glob("*.part")))


if __name__ == "__main__":
    unittest.main()
