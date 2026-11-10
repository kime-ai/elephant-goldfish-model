# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Run the OpenCode Goldfish isolation plugins' Bun tests."""

import json
import os
from pathlib import Path
import runpy
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


@pytest.mark.skipif(
    shutil.which("bun") is None and not os.environ.get("CI"), reason="Install Bun to test the isolation plugins",
)
@pytest.mark.parametrize("interface", ["v1", "v2"])
def test_installer_options_load_in_the_plugin(interface: str, tmp_path: Path) -> None:
    # OpenCode skips a plugin that fails to load and runs the reviewer unisolated, so the
    # options the installer writes must satisfy the plugin's own parser.
    install = runpy.run_path(str(ROOT / "adapters/opencode/install.py"))["install"]
    config = json.loads(install(tmp_path / "candidate", interface).read_text())
    options = config["plugin"][0][1] if interface == "v1" else config["plugins"][0]["options"]
    script = (
        "import { parseReviewers } from './adapters/opencode/plugin/options.ts';"
        "console.log(JSON.stringify([...parseReviewers(JSON.parse(process.env.OPTIONS ?? '')) ].sort()))"
    )
    result = subprocess.run(
        ["bun", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=60,
        env={**os.environ, "OPTIONS": json.dumps(options)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == sorted(options["reviewers"])
    assert len(options["reviewers"]) == 8
