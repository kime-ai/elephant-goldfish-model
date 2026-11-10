# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Run the OpenCode Goldfish isolation plugins' Bun tests."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("bun") is None, reason="Install Bun to test the isolation plugins")
@pytest.mark.parametrize("tests", ["goldfish_isolation.test.ts", "goldfish_isolation_v1.test.ts"])
def test_goldfish_isolation_plugin(tests: str) -> None:
    path = Path(__file__).with_name(tests)
    result = subprocess.run(
        ["bun", "test", f"./{path.relative_to(ROOT)}"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
