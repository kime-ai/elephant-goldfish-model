# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Offline checks for the OpenCode native probe's interface handling."""

import json
from pathlib import Path
import re
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
def test_version_of_the_interface_major_is_accepted(output: str, major: int, version: str) -> None:
    assert PROBE["parse_version"](output, major) == version


@pytest.mark.parametrize(("output", "major"), [
    ("opencode v2.2.7", 1),
    ("1.18.29", 2),
    ("12.0.0", 2),
    ("opencode dev", 2),
])
def test_version_outside_the_interface_major_is_rejected(output: str, major: int) -> None:
    with pytest.raises(AssertionError):
        PROBE["parse_version"](output, major)


def test_each_interface_names_its_major() -> None:
    assert {name: item.major for name, item in PROBE["INTERFACES"].items()} == {"v1": 1, "v2": 2}


def workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text())


def matrix(name: str) -> dict:
    return workflow(name)["jobs"]["native-probe"]["strategy"]["matrix"]


def interfaces(name: str) -> dict[str, dict]:
    return {item["interface"]: item for item in matrix(name)["include"]}


def test_gating_workflow_probes_every_interface_at_its_pinned_version() -> None:
    assert set(interfaces("opencode-native")) == set(PROBE["INTERFACES"])
    # Each job installs from the lockfile; nothing here follows upstream releases.
    steps = workflow("opencode-native")["jobs"]["native-probe"]["steps"]
    assert any("npm ci" in step.get("run", "") for step in steps)
    assert "schedule" not in workflow("opencode-native")[True]


def test_pinned_executables_are_the_probed_host_versions() -> None:
    pins = json.loads((ROOT / "tests/integration/opencode-ci/package.json").read_text())["dependencies"]
    probed = {name: item.probed for name, item in INSTALLER["INTERFACES"].items()}
    assert {name: pins[item["package"]] for name, item in interfaces("opencode-native").items()} == probed


def test_pinned_binary_paths_lie_inside_their_packages() -> None:
    for item in interfaces("opencode-native").values():
        assert item["binary"] == f"node_modules/{item['package']}/bin/opencode"


def test_latest_workflow_probes_the_newest_release_of_each_major_on_a_schedule() -> None:
    triggers = workflow("opencode-latest")[True]
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert {name: item["major"] for name, item in interfaces("opencode-latest").items()} == {
        name: str(item.major) for name, item in PROBE["INTERFACES"].items()
    }
    # The latest packages are the pinned ones, floated to the newest of their major version.
    assert {name: item["package"] for name, item in interfaces("opencode-latest").items()} == {
        name: item["package"] for name, item in interfaces("opencode-native").items()
    }


def test_neither_workflow_needs_conditional_steps_or_failure_overrides() -> None:
    for name in ("opencode-native", "opencode-latest"):
        job = workflow(name)["jobs"]["native-probe"]
        assert "continue-on-error" not in job
        assert not [step for step in job["steps"] if "if" in step]


def test_probe_and_installer_select_the_same_interfaces() -> None:
    assert set(PROBE["INTERFACES"]) == set(INSTALLER["INTERFACES"]) == {"v1", "v2"}


def test_each_guide_targets_the_host_release_the_installer_names() -> None:
    # #146 scopes the adapter to one host release; other releases are not claimed.
    for name, host in INSTALLER["INTERFACES"].items():
        guide = (ROOT / host.guide).read_text().split("\n## ")[0]
        assert re.search(rf"targets OpenCode (CLI )?\*\*{re.escape(host.probed)}\*\*", guide), name
