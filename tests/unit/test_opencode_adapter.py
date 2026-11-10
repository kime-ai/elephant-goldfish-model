# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Offline checks for the experimental OpenCode V1 installer."""

import hashlib
import json
import os
from pathlib import Path
import re
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = runpy.run_path(str(ROOT / "adapters/opencode/install.py"))


def test_install_preserves_resources_and_native_contract(tmp_path: Path) -> None:
    destination = tmp_path / "EGM candidate ü"
    config_path = ADAPTER["install"](destination)
    config = json.loads(config_path.read_text())
    identity = json.loads((destination / "installation.json").read_text())
    canonical = json.loads((ROOT / "plugin.json").read_text())
    assert (identity["name"], identity["version"]) == (canonical["name"], canonical["version"])
    assert identity["host_version"] == "1.18.29"
    for relative, digest in identity["sha256"].items():
        installed = destination / relative
        source = ROOT / installed.relative_to(destination / "bundle")
        assert installed.read_bytes() == source.read_bytes()
        assert hashlib.sha256(installed.read_bytes()).hexdigest() == digest
    for directory in ("skills", "agents", "resources", "docs"):
        for source in (ROOT / directory).rglob("*"):
            if source.is_file():
                assert (Path("bundle") / source.relative_to(ROOT)).as_posix() in identity["sha256"]

    assert config["default_agent"] == "egm"
    assert config["autoupdate"] is False
    assert "model" not in config
    assert len(config["command"]) == 7
    for skill in (ROOT / "skills").glob("*/SKILL.md"):
        key = ADAPTER["name"](skill)
        alias = Path(config["skills"]["paths"][0]) / key
        assert alias.resolve() == destination / "bundle/skills" / skill.parent.name
        assert (alias / "SKILL.md").read_bytes() == skill.read_bytes()
        command = config["command"][key]
        assert command["agent"] == "egm"
        assert str(alias.resolve() / "SKILL.md") in command["template"]
        assert "$ARGUMENTS" in command["template"]

    assert len(config["agent"]) == 9
    for filename in ADAPTER["REVIEWERS"]:
        persona = destination / "bundle/agents" / f"{filename}.md"
        agent = config["agent"][ADAPTER["name"](persona)]
        assert agent["mode"] == "subagent"
        assert agent["permission"] == {
            "*": "deny",
            "read": {
                "*": "allow", "*.env": "deny", "*.env.*": "deny",
                "*.env.example": "allow", "mcp:*": "deny",
            },
            "glob": "allow", "grep": "deny",
            "external_directory": {"*": "deny", f"{destination / 'bundle'}/**": "allow"},
        }
        # V1 maps resource reads and both list tools to read. Last match wins.
        assert list(agent["permission"]["read"].items()) == [
            ("*", "allow"), ("*.env", "deny"), ("*.env.*", "deny"),
            ("*.env.example", "allow"), ("mcp:*", "deny"),
        ]
        assert str(persona) in agent["prompt"]
        assert "Read-Only Protocol" not in agent["prompt"]
    primary = config["agent"]["egm"]
    assert primary["permission"]["*"] == "ask"
    assert list(primary["permission"]["read"].items()) == [
        ("*", "allow"), ("*.env", "ask"), ("*.env.*", "ask"), ("*.env.example", "allow"),
    ]
    assert set(primary["permission"]["task"]) == {"*", *set(config["agent"]) - {"egm"}}
    assert "Omit task_id" in primary["prompt"]
    assert "foreground completion" in primary["prompt"]


def test_stage_required_reports_preserve_context_boundary(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"
    config = json.loads(ADAPTER["install"](destination).read_text())
    bundle = destination / "bundle"
    canonical = (bundle / "skills/egm-review/SKILL.md").read_text()
    assert "include `zoom_out_report.md` path in" in canonical
    guide = " ".join((bundle / "docs/opencode.md").read_text().split())
    prompt = config["agent"]["egm-zoom-out"]["prompt"]
    for instructions in (prompt, guide):
        assert (
            "Read prior reports only when explicitly supplied and required by the canonical stage."
        ) in instructions
        assert "Do not retrieve unsolicited history, memory, or earlier reviewer findings." in instructions
    assert "Do not pass parent history, private reasoning, or memory." in guide


def test_existing_destination_is_untouched(tmp_path: Path) -> None:
    sentinel = tmp_path / "existing.txt"
    sentinel.write_text("other worker")
    with pytest.raises(FileExistsError):
        ADAPTER["install"](tmp_path)
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_text() == "other worker"


@pytest.mark.parametrize("suffix", ["bad*", "bad?", "bad[glob]", "{env:HOME}", "bad\npath", r"bad\path"])
def test_template_paths_are_rejected(tmp_path: Path, suffix: str) -> None:
    if "\\" in suffix and Path(suffix).name != suffix:
        pytest.skip("Requires a literal backslash in a POSIX filename")
    with pytest.raises(ValueError):
        ADAPTER["install"](tmp_path / suffix)
    assert not list(tmp_path.iterdir())


def test_source_destination_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside the source"):
        ADAPTER["install"](ROOT / "unused-opencode-test-destination")


def test_command_interpolation_paths_are_rejected(tmp_path: Path) -> None:
    # V1 replaces positional placeholders and $ARGUMENTS across the template.
    for component in ("$ARGUMENTS", "$1"):
        with pytest.raises(ValueError, match="template or glob"):
            ADAPTER["install"](tmp_path / component / "candidate")
    assert not list(tmp_path.iterdir())


def test_symlink_parent_cannot_bypass_path_validation(tmp_path: Path) -> None:
    target = tmp_path / "unsafe[glob]"
    target.mkdir()
    alias = tmp_path / "safe"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        ADAPTER["install"](alias / "candidate")
    assert not list(target.iterdir())


def test_dangling_destination_is_untouched(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"
    destination.symlink_to(tmp_path / "absent")
    with pytest.raises(FileExistsError):
        ADAPTER["install"](destination)
    assert destination.is_symlink()
    assert not (tmp_path / "absent").exists()


def v1_match(pattern: str, value: str) -> bool:
    """Port of V1 Wildcard.match (anomalyco/opencode@1674747): "*" spans "/"."""
    escaped = re.escape(pattern.replace("\\", "/")).replace(r"\*", ".*").replace(r"\?", ".")
    flags = re.S | (re.I if os.name == "nt" else 0)
    return re.fullmatch(escaped, value.replace("\\", "/"), flags) is not None


def v1_read_effect(rules: dict, path: str) -> str | None:
    effect = None
    for pattern, action in rules.items():
        if v1_match(pattern, path):
            effect = action
    return effect


def test_required_reads_pass_env_rules(tmp_path: Path) -> None:
    # V1 checks reads against the path relative to the worktree.
    worktree = tmp_path / "project"
    worktree.mkdir()
    destination = tmp_path / "candidate"
    config = json.loads(ADAPTER["install"](destination).read_text())
    bundle = destination / "bundle"
    required = [
        bundle / "docs/opencode.md",
        *(bundle / "agents").glob("*.md"),
        *(bundle / "resources").rglob("*.md"),
    ]
    for name, agent in config["agent"].items():
        rules = agent["permission"]["read"]
        for path in required:
            assert v1_read_effect(rules, os.path.relpath(path, worktree)) == "allow", (name, path)
        secret = "ask" if name == "egm" else "deny"
        for path in (".env", "app/.env", ".env.local", "app/.env.production", "prod.env"):
            assert v1_read_effect(rules, path) == secret, (name, path)
        assert v1_read_effect(rules, "app/.env.example") == "allow"


@pytest.mark.parametrize("suffix", ["egm.env.candidate", "staging.ENV.d/candidate"])
def test_env_matching_destination_is_rejected(tmp_path: Path, suffix: str) -> None:
    with pytest.raises(ValueError, match="read rules"):
        ADAPTER["install"](tmp_path / suffix)
    assert not list(tmp_path.iterdir())


def test_unknown_host_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown OpenCode host"):
        ADAPTER["install"](tmp_path / "candidate", "v3")
    assert not list(tmp_path.iterdir())


# V2 base policy every agent starts with; agent rules are appended after it.
V2_BASE = [
    {"action": "*", "resource": "*", "effect": "allow"},
    {"action": "read", "resource": "*.env", "effect": "ask"},
    {"action": "read", "resource": "*.env.*", "effect": "ask"},
    {"action": "read", "resource": "*.env.example", "effect": "allow"},
]


def v2_effect(rules: list, action: str, resource: str) -> str:
    """V2 evaluation: whole-value wildcards on action and resource, last match wins."""
    effect = "ask"
    for item in V2_BASE + rules:
        if v1_match(item["action"], action) and v1_match(item["resource"], resource):
            effect = item["effect"]
    return effect


def test_v2_install_native_contract(tmp_path: Path) -> None:
    destination = tmp_path / "EGM v2 ü"
    config = json.loads(ADAPTER["install"](destination, "v2").read_text())
    identity = json.loads((destination / "installation.json").read_text())
    bundle = destination / "bundle"
    assert identity["host_version"] == "2.2.5"
    assert not {"agent", "command", "permission", "autoupdate"} & set(config)
    assert config["default_agent"] == "egm"
    assert config["skills"] == [str(destination / "skills")]
    assert len(config["commands"]) == 7
    for skill in (ROOT / "skills").glob("*/SKILL.md"):
        key = ADAPTER["name"](skill)
        assert (destination / "skills" / key / "SKILL.md").read_bytes() == skill.read_bytes()
        command = config["commands"][key]
        assert command["agent"] == "egm"
        assert "$ARGUMENTS" in command["template"]
        assert str(bundle / "docs/opencode_v2.md") in command["template"]

    assert len(config["agents"]) == 9
    reviewers = set(config["agents"]) - {"egm"}
    for filename in ADAPTER["REVIEWERS"]:
        persona = bundle / "agents" / f"{filename}.md"
        agent = config["agents"][ADAPTER["name"](persona)]
        assert agent["mode"] == "subagent"
        assert not {"prompt", "permission", "tools"} & set(agent)
        assert str(persona) in agent["system"]
        assert agent["permissions"][0] == {"action": "*", "resource": "*", "effect": "deny"}
    primary = config["agents"]["egm"]
    assert primary["mode"] == "primary"
    assert "Omit sessionID" in primary["system"]
    assert "task_id" not in primary["system"]
    allowed = {r["resource"] for r in primary["permissions"]
               if r["action"] == "subagent" and r["effect"] == "allow"}
    assert allowed == reviewers
    guide = " ".join((bundle / "docs/opencode_v2.md").read_text().split())
    assert "Do not pass parent history, private reasoning, or memory." in guide

    assert config["experimental"] == {"todo": True}
    plugin = bundle / "adapters/opencode/goldfish_isolation"
    assert config["plugins"] == [{"package": str(plugin), "options": {"agents": sorted(reviewers)}}]
    sources = sorted((ROOT / "adapters/opencode/goldfish_isolation").glob("*.ts"))
    assert {path.name for path in sources} >= {"index.ts", "isolate.ts"}
    for source in sources:
        assert (plugin / source.name).read_bytes() == source.read_bytes()
        key = f"bundle/adapters/opencode/goldfish_isolation/{source.name}"
        assert identity["sha256"][key] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_v1_install_omits_isolation_plugin(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"
    config = json.loads(ADAPTER["install"](destination).read_text())
    assert not {"plugins", "experimental"} & set(config)
    assert not (destination / "bundle/adapters").exists()


def test_v2_permissions_enforce_reviewer_boundary(tmp_path: Path) -> None:
    destination = tmp_path / "candidate"
    config = json.loads(ADAPTER["install"](destination, "v2").read_text())
    bundle = destination / "bundle"
    required = [
        bundle / "docs/opencode_v2.md",
        *(bundle / "agents").glob("*.md"),
        *(bundle / "resources").rglob("*.md"),
    ]
    for name, agent in config["agents"].items():
        rules = agent["permissions"]
        reviewer = name != "egm"
        # External reads are checked as canonical absolute paths plus a "/*" boundary.
        for path in required:
            assert v2_effect(rules, "read", str(path)) == "allow", (name, path)
            assert v2_effect(rules, "external_directory", f"{path.parent}/*") == "allow"
        assert v2_effect(rules, "external_directory", "/etc/*") == ("deny" if reviewer else "ask")
        secret = "deny" if reviewer else "ask"
        for path in (".env", "app/.env", ".env.local", "app/.env.production", "prod.env"):
            assert v2_effect(rules, "read", path) == secret, (name, path)
        assert v2_effect(rules, "read", "app/.env.example") == "allow"
        assert v2_effect(rules, "subagent", "general") == "deny"
        assert v2_effect(rules, "skill", "browser") == "deny"
        if reviewer:
            for action, resource in (
                ("grep", ".*"), ("shell", "cat .env"), ("edit", "x.md"),
                ("webfetch", "https://example.com"), ("question", "*"),
                ("subagent", "egm-style"), ("opencode_read_mcp_resource", "s:u"), ("execute", "*"),
            ):
                assert v2_effect(rules, action, resource) == "deny", (name, action)
        instructions = ("AGENTS.md", "pkg/AGENTS.md", "/home/u/.config/opencode/AGENTS.md", "agents.md")
        for path in instructions:
            assert v2_effect(rules, "read", path) == ("deny" if reviewer else "allow"), (name, path)
        assert v2_effect(rules, "read", "SUBAGENTS.md") == "allow", name
        assert v2_effect(rules, "todowrite", "*") == ("deny" if reviewer else "allow")
        if reviewer:
            assert v2_effect(rules, "read", "README.md") == "allow"
        else:
            assert v2_effect(rules, "question", "*") == "allow"
            assert v2_effect(rules, "edit", "design_draft.md") == "ask"
            assert v2_effect(rules, "skill", "egm-review") == "allow"
