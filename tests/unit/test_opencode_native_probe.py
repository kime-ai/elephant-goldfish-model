# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Offline checks for the OpenCode native probe's host handling."""

import json
from pathlib import Path
import runpy

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PROBE = runpy.run_path(str(ROOT / "tests/integration/opencode_native_probe.py"))
INSTALLER = runpy.run_path(str(ROOT / "adapters/opencode/install.py"))


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


def native_workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/opencode-native.yml").read_text())


def test_ci_probes_each_host_at_its_pinned_and_latest_version() -> None:
    workflow = native_workflow()
    job = workflow["jobs"]["native-probe"]
    matrix = job["strategy"]["matrix"]
    assert set(matrix["host"]) == set(PROBE["HOSTS"])
    assert set(matrix["channel"]) == {"pinned", "latest"}
    assert {item["host"]: item["major"] for item in matrix["include"]} == {
        name: str(host.major) for name, host in PROBE["HOSTS"].items()
    }
    # A new upstream release must not block unrelated changes; it reports instead.
    assert job["continue-on-error"] == "${{ matrix.channel == 'latest' }}"
    # PyYAML reads the "on" key as True.
    assert workflow[True]["schedule"]


def test_pinned_executables_are_the_verified_host_versions() -> None:
    pins = json.loads((ROOT / "tests/integration/opencode-ci/package.json").read_text())["dependencies"]
    packages = {item["host"]: item["package"] for item in native_workflow()["jobs"]["native-probe"]["strategy"]["matrix"]["include"]}
    verified = {name: host.verified for name, host in INSTALLER["HOSTS"].items()}
    assert {host: pins[package] for host, package in packages.items()} == verified
