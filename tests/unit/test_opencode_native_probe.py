# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Offline checks for the OpenCode native probe's host handling."""

from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = runpy.run_path(str(ROOT / "tests/integration/opencode_native_probe.py"))


@pytest.mark.parametrize(("output", "major", "version"), [
    ("1.18.29\n", 1, "1.18.29"),
    ("1.19.5", 1, "1.19.5"),
    ("opencode v2.2.5\n", 2, "2.2.5"),
    ("opencode v2.10.0", 2, "2.10.0"),
])
def test_version_of_the_host_major_is_accepted(output: str, major: int, version: str) -> None:
    assert PROBE["parse_version"](output, major) == version


@pytest.mark.parametrize(("output", "major"), [
    ("opencode v2.2.7", 1),
    ("1.18.29", 2),
    ("12.0.0", 2),
    ("opencode dev", 2),
])
def test_version_outside_the_host_major_is_rejected(output: str, major: int) -> None:
    with pytest.raises(AssertionError):
        PROBE["parse_version"](output, major)


def test_each_host_names_its_major() -> None:
    assert {name: host.major for name, host in PROBE["HOSTS"].items()} == {"v1": 1, "v2": 2}

