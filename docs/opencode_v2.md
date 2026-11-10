<!-- Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0 -->

# OpenCode V2 integration (experimental)

This adapter targets OpenCode **2.2.5** with the native V2 `agents`,
`permissions`, `commands`, and `subagent` interfaces. For OpenCode 1.x, use the
[V1 integration](opencode.md). Installation checks do not establish workflow or
isolation support; the verification steps in the V1 guide still apply.

## Install

Use Python 3.10+ and a POSIX filesystem with symbolic links. The installer copies
the canonical resource trees, does not change global or project configuration,
and refuses an existing destination.

```sh
git rev-parse HEAD
python3 adapters/opencode/install.py --host v2 /absolute/egm-opencode-v2
opencode --version
```

Inspect the generated `opencode.json` and `installation.json` before use. The
configuration contains seven commands, eight reviewers, and the `egm` primary
agent, which is the default agent. Skill links use the canonical frontmatter
names, which V2 uses as skill IDs.

The shared V2 background service does not read the client's environment, so
start a private server from the project directory with the candidate
configuration:

```sh
OPENCODE_CONFIG=/absolute/egm-opencode-v2/opencode.json opencode --standalone
```

The command and shell-marker cautions in the V1 guide apply unchanged: do not
paste untrusted review material into slash-command arguments. Use an ordinary
message such as `Use the egm-review skill to review /absolute/path/design.md.`

To uninstall, stop sessions and remove the candidate directory.

## Paths and dispatch

Resolve `agents/`, `resources/`, and `docs/` against the absolute bundle root in
the generated prompt. Resolve `references/` against the canonical skill
directory. Resolve user files against the project directory.

Dispatch reviewers directly from `egm` with the V2 `subagent` tool. Set `agent`
to the persona's canonical frontmatter name and supply `description` and
`prompt`. Omit `sessionID` to create a fresh child session; never resume a
reviewer. Leave `background` unset so the review runs in the foreground. The
primary agent performs synthesis and writes reports; no nested synthesizer is
installed. Bootstrap worker and scout delegation is outside this adapter's
scope: the `subagent` allowlist contains only the eight reviewers.

Pass absolute paths for the persona, target, standards, and selected sources.
Do not pass parent history, private reasoning, or memory.
Supply prior report paths only when the canonical stage requires them, such as
`zoom_out_report.md` for Step 8 (Intermediate Zoom Out).
Read prior reports only when explicitly supplied and required by the canonical stage.
Do not retrieve unsolicited history, memory, or earlier reviewer findings.
Stop if native delegation is unavailable. Never simulate Goldfish reviewers in
the parent conversation.

## Permissions

V2 evaluates one ordered `permissions` list per agent; the last matching rule
wins and agent rules follow the base and global rules.

Reviewers start with `*` deny, then allow `read` (except `.env` files) and
`glob`, and allow external directories only inside the bundle. The `*` deny
covers `grep`, whose resource is the search pattern rather than a path, so it
would bypass the `.env` read rules. It also covers shell, edits, web, MCP tools
and resources, Code Mode, skills, questions, and delegation.

The `egm` agent asks by default, allows reads, `glob`, `grep`, questions for
approval gates, `egm-*` skills, and the eight reviewers. V2 allows external
directories by default; this agent restores the V1 prompt except for the bundle.

## Differences from V1

- No `autoupdate` field: V2 reads `update` only from global configuration.
- No `mcp:*` read rule: V2 checks MCP resources under their own actions.
- No `--agent` flag: `default_agent` selects `egm`.
- V2 still adds project instructions such as `AGENTS.md` to each agent's
  `system` prompt, including reviewers. A fresh child session is not proof of
  Goldfish isolation; see the V1 verification limits.
- The V1 native probe and trace verifier target 1.18.29 and do not run on V2.
