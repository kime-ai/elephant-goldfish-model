# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Run the OpenCode Goldfish isolation plugins' Bun tests."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


# CI installs Bun, so a missing Bun there is a failure rather than a skip.
@pytest.mark.skipif(
    shutil.which("bun") is None and not os.environ.get("CI"), reason="Install Bun to test the isolation plugins",
)
@pytest.mark.parametrize("tests", ["goldfish_isolation.test.ts", "goldfish_isolation_v1.test.ts"])
def test_goldfish_isolation_plugin(tests: str) -> None:
    path = Path(__file__).with_name(tests)
    result = subprocess.run(
        ["bun", "test", f"./{path.relative_to(ROOT).as_posix()}"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
