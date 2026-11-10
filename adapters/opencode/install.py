# Copyright 2026 Google LLC.
# SPDX-License-Identifier: Apache-2.0

"""Install an experimental OpenCode V1 or V2 bundle without changing user config."""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
ISOLATION_PLUGIN = Path("adapters/opencode/goldfish_isolation")
# Instruction files the host injects into every agent. Goldfish reviewers must not read them;
# each name is matched at the worktree root and in any directory, never as a suffix.
INSTRUCTION_FILES = {
    "v1": ("AGENTS.md", "agents.md", "CLAUDE.md", "claude.md", "CONTEXT.md", "context.md"),
    "v2": ("AGENTS.md", "agents.md"),
}
REVIEWERS = (
    "codebase_details", "comprehension", "design_critic",
    "implementation_readiness", "inventive_catalyst", "structural", "style", "zoom_out",
)


def name(path: Path) -> str:
    """Read the canonical name without a runtime YAML dependency."""
    header = path.read_text(encoding="utf-8").split("---", 2)[1]
    match = re.search(r"^name: (egm-[a-z-]+)$", header, re.MULTILINE)
    if not match:
        raise ValueError(f"Missing canonical name: {path}")
    return match[1]


def install(destination: Path, interface: str = "v1") -> Path:
    """Create a new installation; refuse to overwrite any existing path."""
    if interface not in INTERFACES:
        raise ValueError(f"Unknown OpenCode interface: {interface}")
    target = INTERFACES[interface]
    destination = checked_destination(destination)
    destination.mkdir(parents=True)
    bundle = copy_bundle(destination / "bundle", target.extras)
    guide = bundle / target.guide
    context = (
        f"Read {guide} first. EGM bundle root: {bundle}. "
        "Resolve agents/, resources/, and docs/ against this root. "
        "Resolve references/ against the canonical skill directory. "
        "Resolve user files and outputs against the project working directory. "
    )
    skills = destination / "skills"
    commands = link_skills(bundle, skills, context)
    config = destination / "opencode.json"
    config.write_text(json.dumps(
        target.build(bundle, skills, context, commands), indent=2,
    ) + "\n", encoding="utf-8")
    write_identity(destination, bundle, target.probed)
    return config


def checked_destination(destination: Path) -> Path:
    """Return the resolved destination, or raise if it is unsafe to install into."""
    destination = destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination = destination.resolve()
    # Check resolved parents too: paths enter glob rules and prompt templates.
    if "\\" in destination.as_posix() or any(
        c in str(destination) for c in '*?[]{}!@`$\n\r'
    ):
        raise ValueError("Installation path contains template or glob characters")
    # Read rules match worktree-relative paths and "*" spans "/", so "*.env.*"
    # would deny every bundle read below such a path.
    if ".env." in str(destination).lower():
        raise ValueError("Installation path matches the .env read rules")
    if destination.is_relative_to(ROOT):
        raise ValueError("Install outside the source tree")
    return destination


def copy_bundle(bundle: Path, extras: tuple[Path, ...]) -> Path:
    """Copy the canonical resources, plus interface-specific trees, into a new bundle."""
    bundle.mkdir()
    for directory in ("skills", "agents", "resources", "docs", *extras):
        shutil.copytree(ROOT / directory, bundle / directory)
    for filename in ("plugin.json", "LICENSE", "README.md", "TESTING.md"):
        shutil.copy2(ROOT / filename, bundle / filename)
    return bundle


def link_skills(bundle: Path, skills: Path, context: str) -> dict:
    """Link each bundled skill under its canonical name and return its command."""
    skills.mkdir()
    commands = {}
    for skill in sorted((bundle / "skills").glob("*/SKILL.md")):
        skill_name = name(skill)
        (skills / skill_name).symlink_to(skill.parent, target_is_directory=True)
        commands[skill_name] = {
            "description": f"Run {skill_name} (experimental)",
            "agent": "egm",
            "template": context + f"Read and execute {skill}.\nUser request: $ARGUMENTS",
        }
    return commands


def write_identity(destination: Path, bundle: Path, host_version: str) -> None:
    """Record the plugin identity, target OpenCode release, and a digest of every bundled file."""
    metadata = json.loads((bundle / "plugin.json").read_text(encoding="utf-8"))
    (destination / "installation.json").write_text(json.dumps({
        "name": metadata["name"], "version": metadata["version"],
        "host_version": host_version,
        "status": "experimental",
        "sha256": {
            path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(bundle.rglob("*")) if path.is_file()
        },
    }, indent=2) + "\n", encoding="utf-8")


REVIEWER_RULES = (
    "Return findings to the caller. Do not write reports or delegate. "
    "Read prior reports only when explicitly supplied and required by the canonical stage. "
    "Do not retrieve unsolicited history, memory, or earlier reviewer findings. "
    "Report inaccessible required files as an incomplete review."
)
ORCHESTRATOR_RULES = (
    "Wait for foreground completion. Pass only the task, absolute resource paths, "
    "target, standards, and selected reading list, not conversation history. "
    "Stop if delegation or a required completion is missing. "
    "When running brainstorm before draft, complete all seven brainstorm "
    "reviewers and synthesize their findings into concepts_brief.md before drafting. "
    "In review, write each completed stage report before starting the next stage. "
    "Before Step 8, verify zoom_out_report.md exists in the artifact directory "
    "and pass its absolute path to the reviewer; stop if it is missing. "
    "Write reports yourself. Preserve every human approval gate."
)


def v1_config(bundle: Path, skills: Path, context: str, commands: dict) -> dict:
    """Build the V1 `agent`/`permission`/`command` configuration."""
    agents = {}
    for reviewer in REVIEWERS:
        persona = bundle / "agents" / f"{reviewer}.md"
        agents[name(persona)] = {
            "description": f"EGM read-only {reviewer} reviewer (experimental)",
            "mode": "subagent",
            "color": "#E86E00",
            "permission": {
                "*": "deny",
                # Later rules win, so "*" alone would override OpenCode's default .env rules.
                "read": {
                    "*": "allow", "*.env": "deny", "*.env.*": "deny",
                    "*.env.example": "allow", "mcp:*": "deny",
                    **{pattern: "deny" for pattern in instruction_patterns("v1")},
                },
                # grep does not enforce read rules, so it could expose .env files.
                "glob": "allow", "grep": "deny",
                "external_directory": {"*": "deny", f"{bundle}/**": "allow"},
            },
            "prompt": context + f"Read {persona} before the target and supplied standards. "
            + REVIEWER_RULES,
        }
    agents["egm"] = {
        "description": "EGM orchestrator (experimental OpenCode V1)",
        "mode": "primary",
        "color": "#1B6EF3",
        "permission": {
            "*": "ask",
            "read": {"*": "allow", "*.env": "ask", "*.env.*": "ask", "*.env.example": "allow"},
            "glob": "allow", "grep": "allow",
            "skill": {"*": "deny", "egm-*": "allow"},
            "task": {"*": "deny", **{key: "allow" for key in agents}},
            "external_directory": {"*": "ask", f"{bundle}/**": "allow"},
        },
        "prompt": context + "Follow the canonical skill. Dispatch reviewers directly "
        "with task and the registered persona name as subagent_type. "
        "Omit task_id for every independent review; never resume a reviewer. "
        + ORCHESTRATOR_RULES,
    }
    return {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "default_agent": "egm",
        "skills": {"paths": [str(skills)]},
        "plugin": [[str(bundle / ISOLATION_PLUGIN / "v1.ts"), {"agents": sorted(set(agents) - {"egm"})}]],
        "agent": agents,
        "command": commands,
    }


def instruction_patterns(interface: str) -> list[str]:
    """Read patterns for the interface's instruction files, at the root and in any directory."""
    return [pattern for filename in INSTRUCTION_FILES[interface] for pattern in (filename, f"*/{filename}")]


def rule(action: str, resource: str, effect: str) -> dict:
    return {"action": action, "resource": resource, "effect": effect}


def v2_config(bundle: Path, skills: Path, context: str, commands: dict) -> dict:
    """Build the native V2 `agents`/`permissions`/`commands` configuration."""
    # V2 matches the canonical directory boundary, which ends in "/*"; "*" spans "/".
    bundle_dir = f"{bundle}/*"
    agents = {}
    for reviewer in REVIEWERS:
        persona = bundle / "agents" / f"{reviewer}.md"
        agents[name(persona)] = {
            "description": f"EGM read-only {reviewer} reviewer (experimental)",
            "mode": "subagent",
            "color": "#E86E00",
            # Last match wins. "*" deny also covers grep (its resource is the regex, so
            # it bypasses the .env read rules), shell, edits, MCP, skills, and subagents.
            "permissions": [
                rule("*", "*", "deny"),
                rule("read", "*", "allow"),
                rule("read", "*.env", "deny"),
                rule("read", "*.env.*", "deny"),
                rule("read", "*.env.example", "allow"),
                # Goldfish isolation; the plugin removes injected AGENTS.md, this blocks
                # direct reads. The lowercase rule covers case-insensitive filesystems.
                *(rule("read", pattern, "deny") for pattern in instruction_patterns("v2")),
                rule("glob", "*", "allow"),
                rule("external_directory", "*", "deny"),
                rule("external_directory", bundle_dir, "allow"),
            ],
            "system": context + f"Read {persona} before the target and supplied standards. "
            + REVIEWER_RULES,
        }
    agents["egm"] = {
        "description": "EGM orchestrator (experimental OpenCode V2)",
        "mode": "primary",
        "color": "#1B6EF3",
        "permissions": [
            rule("*", "*", "ask"),
            rule("read", "*", "allow"),
            rule("read", "*.env", "ask"),
            rule("read", "*.env.*", "ask"),
            rule("read", "*.env.example", "allow"),
            rule("glob", "*", "allow"),
            rule("grep", "*", "allow"),
            # Approval gates use the question tool.
            rule("question", "*", "allow"),
            # Requires experimental.todo, set below.
            rule("todowrite", "*", "allow"),
            rule("skill", "*", "deny"),
            rule("skill", "egm-*", "allow"),
            rule("subagent", "*", "deny"),
            *(rule("subagent", key, "allow") for key in agents),
            # V2 allows external directories by default; restore the V1 prompt.
            rule("external_directory", "*", "ask"),
            rule("external_directory", bundle_dir, "allow"),
        ],
        "system": context + "Follow the canonical skill. Dispatch reviewers directly "
        "with the subagent tool and the registered persona name as agent. "
        "Omit sessionID for every independent review; never resume a reviewer. "
        "Do not set background. "
        + ORCHESTRATOR_RULES,
    }
    return {
        "$schema": "https://opencode.ai/config.json",
        "default_agent": "egm",
        "skills": [str(skills)],
        "experimental": {"todo": True},
        "plugins": [{
            "package": str(bundle / ISOLATION_PLUGIN),
            "options": {"agents": sorted(set(agents) - {"egm"})},
        }],
        "agents": agents,
        "commands": commands,
    }


@dataclass(frozen=True)
class Interface:
    """What one OpenCode configuration interface needs from the installer."""

    # The newest host release the scripted native probe passed on. This is not a support claim:
    # support needs the installation, workflow, and isolation checks in docs/opencode.md.
    probed: str
    guide: str
    build: Callable[[Path, Path, str, dict], dict]
    extras: tuple[Path, ...] = ()


INTERFACES = {
    "v1": Interface("1.18.29", "docs/opencode.md", v1_config, (ISOLATION_PLUGIN,)),
    "v2": Interface("2.2.5", "docs/opencode_v2.md", v2_config, (ISOLATION_PLUGIN,)),
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New, fixed installation directory")
    parser.add_argument(
        "--interface", choices=tuple(INTERFACES), default="v1", help="OpenCode configuration interface",
    )
    args = parser.parse_args()
    print(install(args.destination, args.interface))
