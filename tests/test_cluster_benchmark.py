"""The committed clusters must reproduce well-established biology (see pipelines/check_cluster_benchmark.py)."""

import unittest
from pathlib import Path

from pipelines.check_cluster_benchmark import run

PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed"


@unittest.skipUnless((PROCESSED / "disease_similarity.csv").exists(), "run the cluster pipeline first")
class ClusterBenchmarkTests(unittest.TestCase):
    def test_known_biology_is_reproduced(self):
        failed = [name for name, ok, _ in run(PROCESSED) if not ok]
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
