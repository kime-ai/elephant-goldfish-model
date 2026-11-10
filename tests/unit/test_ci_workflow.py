# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Exercise the workflow's required-result gate without running hosted jobs."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


def workflow() -> dict:
  return yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())


def test_ci_waits_for_all_validation_jobs() -> None:
  jobs = workflow()["jobs"]
  assert set(jobs["ci"]["needs"]) == set(jobs) - {"ci"}
  assert jobs["ci"]["name"] == "CI"
  assert jobs["ci"]["if"] == "${{ always() }}"
  assert jobs["unit"]["strategy"]["fail-fast"] is False
  assert set(jobs["unit"]["strategy"]["matrix"]["os"]) == {
      "ubuntu-24.04", "windows-2025",
  }


def test_unit_job_installs_bun_for_the_isolation_plugin_tests() -> None:
  # Without Bun, tests/unit/test_goldfish_isolation.py has no plugin to run.
  steps = workflow()["jobs"]["unit"]["steps"]
  bun = [step for step in steps if step.get("uses", "").startswith("oven-sh/setup-bun@")]
  assert len(bun) == 1
  assert bun[0]["with"]["bun-version"]
  pytest_index = next(i for i, step in enumerate(steps) if "pytest" in step.get("run", ""))
  assert steps.index(bun[0]) < pytest_index


def test_release_installs_shared_test_group_before_tag_checkout() -> None:
  release = yaml.safe_load(
      (ROOT / ".github/workflows/release.yml").read_text())
  release_steps = release["jobs"]["build"]["steps"]
  install = "python -m pip install --group test"
  unit_steps = workflow()["jobs"]["unit"]["steps"]
  assert install in [step.get("run") for step in unit_steps]
  install_index = next(i for i, step in enumerate(release_steps)
                       if step.get("run") == install)
  tag_index = next(i for i, step in enumerate(release_steps)
                   if step.get("id") == "source")
  assert install_index < tag_index, "Older tags may not define the test group"


@pytest.mark.parametrize("results,success", [
    ({"unit": "success"}, True),
    ({"unit": "failure"}, False),
    ({"unit": "cancelled"}, False),
    ({"unit": "skipped"}, False),
    ({"unit": "success", "site-validation": "success"}, True),
    ({"unit": "success", "site-validation": "failure"}, False),
    ({"unit": "success", "site-validation": "cancelled"}, False),
    ({"unit": "success", "site-validation": "skipped"}, False),
])
def test_ci_requires_successful_results(results: dict, success: bool) -> None:
  step = workflow()["jobs"]["ci"]["steps"][0]
  assert step["env"]["NEEDS_JSON"] == "${{ toJSON(needs) }}"
  shell = shutil.which("bash")
  assert shell, "POSIX bash is required for workflow shell checks"
  completed = subprocess.run(
      [shell, "-e", "-c", step["run"]],
      env={**os.environ, "NEEDS_JSON": json.dumps({
          name: {"result": result} for name, result in results.items()
      })},
      text=True, capture_output=True, timeout=10,
  )
  assert (completed.returncode == 0) is success, (
      completed.stdout + completed.stderr
  )
