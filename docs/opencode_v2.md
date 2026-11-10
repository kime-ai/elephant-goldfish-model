<!-- Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0 -->

# OpenCode V2 integration (experimental)

This adapter targets OpenCode 2.x with the native V2 `agents`,
`permissions`, `commands`, and `subagent` interfaces. The native probe passes on **2.2.5**;
that is not a support claim. See [Host versions](opencode.md#host-versions) for what the probe
covers and for other 2.x releases. For OpenCode 1.x, use the
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

Reviewers start with `*` deny, then allow `read` (except `.env` files and files
named exactly `AGENTS.md` or `agents.md`) and `glob`, and allow external directories only inside the bundle. The
`*` deny covers `grep`, whose resource is the search pattern rather than a path,
so it would bypass the `.env` read rules. It also covers shell, edits, web, MCP
tools and resources, Code Mode, skills, questions, todos, and delegation.

The `egm` agent asks by default, allows reads, `glob`, `grep`, questions for
approval gates, `todowrite`, `egm-*` skills, and the eight reviewers. The
configuration sets `experimental.todo` so that `todowrite` exists. V2 allows
external directories by default; this agent restores the V1 prompt except for
the bundle.

## Instruction isolation

V2 adds global and project `AGENTS.md` files to every agent's instructions,
including subagents, and has no per-agent setting to skip them. Reading a file
also loads any nested `AGENTS.md` between that file and the workspace. The
installer adds the `egm-goldfish-isolation` server plugin from
`bundle/adapters/opencode/goldfish_isolation/` (its `index.ts` entry), with the
eight reviewer names as its `agents` option. Its `context` and `compaction` hooks change only the
outgoing request for those agents:

- The `core/instructions` source is removed from the instructions system part,
  which V2 lists in `metadata.experimental.instructions`. A system part without
  a valid source list is dropped if a line starts with `Instructions from:` or
  `The instructions from` and names an `AGENTS.md` file.
- User messages that start with `Instructions from: <path>/AGENTS.md`, which is
  how V2 delivers nested files, are dropped.
- System messages with such a line, which is how V2 announces instruction
  changes, are dropped.

Only those line markers count. A task or persona that discusses `AGENTS.md`
in prose is kept, and assistant and tool messages are never removed.

The plugin refuses to load without a non-empty `agents` list, so a
misconfigured install fails in the server log instead of running unisolated.
The reviewer read rules block direct reads of `AGENTS.md`. The plugin logs
`[egm-goldfish-isolation] <agent>: removed N AGENTS.md block(s)` to the server
log when it acts. It depends on an experimental field and on V2's instruction
wording, so verify it after upgrading OpenCode. It also removes files loaded
through the `instructions` setting. `glob` still shows that an `AGENTS.md`
exists. Mixed-case names other than `AGENTS.md` and `agents.md` are not covered
by the read rules.

The plugin's tests in `tests/unit/goldfish_isolation.test.ts` run under Bun;
`tests/unit/test_goldfish_isolation.py` runs them and skips when Bun is not
installed. The same directory holds the V1 entry, `v1.ts`; see the
[V1 guide](opencode.md#instruction-isolation).

## Differences from V1

- No `autoupdate` field: V2 reads `update` only from global configuration.
- No `mcp:*` read rule: V2 checks MCP resources under their own actions.
- No `--agent` flag: `default_agent` selects `egm`.
- V2 adds `AGENTS.md` to each agent's instructions, including reviewers; the
  isolation plugin removes it for reviewers. A fresh child session is still not
  proof of Goldfish isolation; see the V1 verification limits.
- The trace verifier targets 1.18.29 and does not run on V2. The native probe runs on
  both; see [Native probe](#native-probe).

## Native probe

`tests/integration/opencode_native_probe.py --host v2` installs this adapter and runs
`opencode run --standalone` against a scripted local model. It checks native `subagent`
dispatch, that a parent-only marker stays out of the reviewer, that the reviewer's `.env` read
and `skill` call are denied, and that a project `AGENTS.md` reaches `egm` but neither it nor a
nested `AGENTS.md` reaches the reviewer. V2 offers reviewers the `skill` tool despite their
`*` deny and refuses the call; the probe requires exactly `read`, `glob`, and `skill`.

```sh
npm ci --ignore-scripts --prefix tests/integration/opencode-ci
python tests/integration/opencode_native_probe.py --host v2 \
  --source . \
  --opencode tests/integration/opencode-ci/node_modules/@opencode/cli-linux-x64/bin/opencode \
  --output /tmp/egm-opencode-v2-probe
```

On another platform, install that platform's package, such as
`@opencode/cli-darwin-arm64@2.2.5`, and pass its `bin/opencode`. A passing probe does not
establish live model behavior, full workflows, or general reviewer isolation.
