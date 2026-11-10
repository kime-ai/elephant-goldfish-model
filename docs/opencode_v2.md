<!-- Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0 -->

# OpenCode V2 integration (experimental)

This adapter targets OpenCode **2.2.6** with the native V2 `agents`,
`permissions`, `commands`, and `subagent` interfaces. The native probe passes on that release,
which is not a support claim. Other 2.x releases are not claimed; see
[Host versions](opencode.md#host-versions). For OpenCode 1.x, use the
[V1 integration](opencode.md). Installation checks do not establish workflow or
isolation support; the verification steps in the V1 guide still apply.

## Install

Use Python 3.10+ and a POSIX filesystem with symbolic links. The installer copies
the canonical resource trees, does not change global or project configuration,
and refuses an existing destination.

```sh
git rev-parse HEAD
python3 adapters/opencode/install.py --interface v2 /absolute/egm-opencode-v2
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

V2 adds every instruction source to every agent's request, including subagents,
and has no per-agent setting to skip them: the global and project `AGENTS.md`
files, files in the `instructions` setting, and Code Mode, MCP, skill, and
reference guidance. Reading a file also loads any nested `AGENTS.md` between that
file and the workspace, as an injected message. V2 also offers every agent the
`skill` tool, even when its rules deny it.

The installer adds the `egm-guard` server plugin from `bundle/adapters/opencode/plugin/`
(its `index.ts` entry). Its options are `primary`, `bundle`, and `reviewers`, which maps each
reviewer's agent ID to its persona path; the plugin reads only the IDs. The `egm-guard` ID and
these options are the installer contract proposed on
[#282](https://github.com/google/elephant-goldfish-model/issues/282), so a fuller guard can
replace this plugin without installer changes. Its `context`, `compaction`, and `generate`
hooks change only the outgoing request for the reviewers, and keep an allowlist:

- **System prompt.** The agent's own prompt, and the `core/date` and `core/environment`
  sources, which V2 lists in `metadata.experimental.instructions`. Every other source is
  removed, including kinds that V2 adds later. A system part with no valid source list is
  removed unless it is the agent's own prompt.
- **Transcript.** V2's injected messages are removed: `synthetic` messages, which carry nested
  `AGENTS.md` files and notices, and system messages with text, which announce instruction
  changes. The reviewer's own user, assistant, and tool messages stay, whatever they say.
- **Tools.** Only `read` and `glob`. Because `skill` is not offered, a reviewer's attempt to
  use it is an unavailable tool, not a denied call; the native probe checks the exact toolset.

Each request fails closed. If a reviewer's request has no copy of its own prompt, which means V2
changed how it builds requests, the plugin throws, the subagent ends in an error, and no request
reaches the model. When the plugin removes something, it logs
`[egm-guard] <agent>: removed N injected item(s)` to the server log.

A plugin that fails to load does not fail closed. V2 2.2.6 logs a warning, `failed to load
plugin plugin.id=egm-guard`, and runs the reviewer with OpenCode's default instructions: the
project and nested `AGENTS.md` reach it, and it is offered `skill`. The plugin rejects a missing
or malformed `reviewers` map, so that is how a bad configuration fails, and no other check
catches it. A unit test installs both interfaces and passes the generated options to the
plugin's own parser, so an installer that drifts from the plugin fails the test. After a manual
edit to the generated configuration, look for that warning in the server log
(`opencode --standalone --print-logs`). The native probe installs its own copy, so it checks the
installer's output, not a file edited by hand. Making a missing plugin fatal means making
reviewer dispatch depend on it, which is part of the guard on #282.

The reviewer read rules also deny direct reads of `AGENTS.md` and `agents.md`. This goes beyond
the guard proposed on #282, and it blocks a review whose target is an `AGENTS.md` file.
`glob` still shows that an `AGENTS.md` exists. Mixed-case names other than `AGENTS.md` and
`agents.md` are not covered by the read rules.

The plugin depends on an experimental field, the `metadata.experimental.instructions` list,
and on V2 giving `synthetic` messages the ID of the session message they came from. The native
probe checks both on each probed release; repeat it after upgrading OpenCode.

The plugin does not control reviewer dispatch, required reads, or the permissions of reviewers
that project configuration or session rules might widen. The design on #282 covers those.

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

`tests/integration/opencode_native_probe.py --interface v2` installs this adapter and runs
`opencode run --standalone` against a scripted local model. It checks native `subagent`
dispatch, that a parent-only marker stays out of the reviewer, that the reviewer's `.env` read
is denied, and that a project `AGENTS.md` reaches `egm` but neither it nor a nested `AGENTS.md`
reaches the reviewer. It requires reviewers to be offered exactly `read` and
`glob`, and checks that they keep their persona prompt and environment.

```sh
npm ci --ignore-scripts --prefix tests/integration/opencode-ci
python tests/integration/opencode_native_probe.py --interface v2 \
  --source . \
  --opencode tests/integration/opencode-ci/node_modules/@opencode/cli-linux-x64/bin/opencode \
  --output /tmp/egm-opencode-v2-probe
```

On another platform, install that platform's package, such as
`@opencode/cli-darwin-arm64@2.2.6`, and pass its `bin/opencode`. A passing probe does not
establish live model behavior, full workflows, or general reviewer isolation.

## Interface sources

Read at the `v2.2.6` tag on 2026-11-10. These source files define the agent, command, skill,
permission, `subagent`, and instruction interfaces this adapter uses. The plugin hooks that the
isolation plugin uses are typed in the `@opencode/plugin` package, which the plugin's type check
runs against:

- [Agent schema](https://github.com/anomalyco/opencode/blob/v2.2.6/packages/schema/src/agent.ts): the fields of an agent, including `system`, `mode`, and `permissions`
- [Agent configuration](https://github.com/anomalyco/opencode/blob/v2.2.6/packages/core/src/config/plugin/agent.ts)
- [Command configuration](https://github.com/anomalyco/opencode/blob/v2.2.6/packages/core/src/config/plugin/command.ts)
- [Skill discovery](https://github.com/anomalyco/opencode/blob/v2.2.6/packages/core/src/config/plugin/skill.ts)
- [Permission evaluation](https://github.com/anomalyco/opencode/blob/v2.2.6/packages/core/src/permission.ts)
- [`subagent` tool](https://github.com/anomalyco/opencode/blob/v2.2.6/packages/core/src/tool/plugin/subagent.ts)
- [Request assembly and instruction sources](https://github.com/anomalyco/opencode/blob/v2.2.6/packages/core/src/session/model-request.ts)
- [Nested instruction loading](https://github.com/anomalyco/opencode/blob/v2.2.6/packages/core/src/session/instructions.ts)
