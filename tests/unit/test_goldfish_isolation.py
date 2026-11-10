# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Run the OpenCode V2 Goldfish isolation plugin's Bun tests."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).with_name("goldfish_isolation.test.ts")


@pytest.mark.skipif(shutil.which("bun") is None, reason="Install Bun to test the V2 isolation plugin")
def test_goldfish_isolation_plugin() -> None:
    result = subprocess.run(
        ["bun", "test", f"./{TESTS.relative_to(ROOT)}"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
