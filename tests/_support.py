"""Shared test helpers: optional-dependency skips and temporary folders that work on locked-down machines."""

import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HAS_NETWORKX = importlib.util.find_spec("networkx") is not None

# Clustering needs networkx. Without it these tests are reported as skipped (an environment issue),
# not as errors that look like defects in RarePath.
needs_networkx = unittest.skipUnless(HAS_NETWORKX, "networkx is not installed: python -m pip install networkx")


def make_tmp() -> Path:
    """A fresh temporary folder. Set RAREPATH_TEST_TMP to a writable folder if the system temp folder is not."""
    base = os.environ.get("RAREPATH_TEST_TMP") or None
    if base:
        os.makedirs(base, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="rarepath-test-", dir=base))


def remove_tmp(path: Path) -> None:
    # Windows can briefly lock files (antivirus, indexers); a leftover temp folder is not a test failure.
    shutil.rmtree(path, ignore_errors=True)
