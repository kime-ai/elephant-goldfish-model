<!-- Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0 -->

# OpenCode V1 integration (experimental)

This adapter targets OpenCode CLI 1.x, with V1 `task` and `permission` interfaces.
The native probe passes on **1.18.29**. That is not a support claim; see
[Host versions](#host-versions) for what the probe covers and for other 1.x releases.
It does not target V2 `subagent` or `permissions` interfaces; for OpenCode 2.x, see the [V2 integration](opencode_v2.md).
Installation checks do not establish workflow or isolation support.
Maintainer approval, live workflows, and isolation verification remain pending under [#146](https://github.com/google/elephant-goldfish-model/issues/146).
The proposed architecture is in [the additional harness design](designs/additional-harnesses.md).

## Install

Use Python 3.10+ and a POSIX filesystem with symbolic links.
Select a fixed candidate commit before installation. Keep the installation at its original path.
The installer copies the complete canonical resource trees. It does not change global or project configuration.
It refuses an existing destination. Use a new destination for each candidate.

```sh
git rev-parse HEAD
python3 adapters/opencode/install.py /absolute/egm-opencode-candidate
opencode --version
```

Use the probed release unless the native probe has passed on yours. To install it:

```sh
npm install --prefix /absolute/opencode-v1 opencode-ai@1.18.29
/absolute/opencode-v1/node_modules/.bin/opencode --version
```

Inspect the generated `opencode.json` and `installation.json` before use.
The latter records package identity, the probed host release as `host_version`, and SHA-256
hashes of all bundled files.
The native configuration contains seven commands, eight reviewers, the `egm` primary agent,
and the `egm-guard` plugin described under [Instruction isolation](#instruction-isolation).
Native skill aliases use the canonical frontmatter names and link to the unchanged skill directories.

Start OpenCode from the project directory with the candidate configuration:

```sh
OPENCODE_CONFIG=/absolute/egm-opencode-candidate/opencode.json opencode --agent egm
```

Model calls require separate user authorization. Installation and version checks do not require model calls.
Select `egm` before native skill use. Other primary agents do not receive this adapter's dispatch instructions.
For review text, use an ordinary message rather than a slash command. For example:

```text
Use the egm-review skill to review /absolute/path/design.md.
```

Paste material into that ordinary message, or save it in a file for the agent to read.
The generated `/egm-brainstorm`, `/egm-draft`, and `/egm-review` commands retain
OpenCode's native command syntax. Their arguments are not literal text: OpenCode
evaluates shell markers (an exclamation mark followed by a command in backticks)
before agent tool permissions apply. Do not paste untrusted review material into
slash-command arguments. Markdown fences do not disable this preprocessing.

To uninstall, stop sessions and remove only this candidate directory. Remove its environment override.

## Paths and dispatch

Use the absolute bundle root in the generated prompt.
Resolve `agents/`, `resources/`, and `docs/` against that root.
Resolve `references/` against the canonical skill directory, after resolving its alias.
Resolve user files against the project directory. Never substitute project files for bundled personas.

Dispatch reviewers directly from `egm` with the V1 `task` tool.
Set `subagent_type` to the persona's canonical frontmatter name.
Supply `description` and `prompt`. Omit `task_id` to create a fresh session.
Use foreground tasks. Do not enable background dispatch or reuse a reviewer session.
The primary agent performs synthesis and writes reports; no nested synthesizer adapter is installed.
Bootstrap worker and scout delegation is outside this adapter's scope. Although
all seven skills are discoverable, the task allowlist contains only the eight
reviewer types. Stop if bootstrap requires an orchestrator or scout; do not
substitute a reviewer or simulate the missing worker.

Pass absolute paths for the persona, target, standards, and selected sources.
Do not pass parent history, private reasoning, or memory.
Supply prior report paths only when the canonical stage requires them, such as
`zoom_out_report.md` for Step 8 (Intermediate Zoom Out).
Read prior reports only when explicitly supplied and required by the canonical stage.
Do not retrieve unsolicited history, memory, or earlier reviewer findings.
Require all specified reads and actual task completion before synthesis.
Report a missing start, completion, required read, or malformed result as incomplete.
Stop if native delegation is unavailable. Never simulate Goldfish reviewers in the parent conversation.

When brainstorm precedes draft, complete all seven brainstorm reviewers first.
Synthesize their findings into `concepts_brief.md` before drafting.
For review, write each completed stage report before starting the next stage.
Before Step 8, verify `zoom_out_report.md` exists in the artifact directory.
Pass its absolute path to the reviewer. Stop if the report is missing.

Reviewers deny every tool except `read` and `glob`.
`grep` is denied because its searches bypass the host's per-file `read` rules,
including the `.env` exclusions. Use permitted file reads for review context.
V1 maps MCP resource reads and resource lists to the `read` permission.
The reviewer `read` rules allow local reads, then deny `mcp:*` and the instruction files
`AGENTS.md`, `CLAUDE.md`, and `CONTEXT.md` (each also in lowercase) at the worktree root and in any
directory. Only those exact file names are denied; `SUBAGENTS.md` stays readable.
This denies `mcp:<server>:<uri>` reads and `mcp:<server>:*` resource or template lists.
MCP resource tool names can remain visible. Their resource access is denied at the permission check.
The adapter's external-directory exception covers only the installed bundle.
OpenCode also adds access to its tool-output directory in the resolved agent configuration.
Shell commands, edits, network tools, MCP tools, skills, and delegation remain denied.
The primary agent requests permission for other tools, including writes.
For an external target, move a fixture into the project or review a narrow permission change separately.

Honor `EGM artifact directory: <path>` in the user's prompt or loaded instructions.
Resolve a relative output directory against the project directory. Otherwise retain the canonical output filenames and working-directory default.
Preserve each readiness, section, and stage approval gate. Ask one plain-text question when the native question tool is unavailable.
Wait for the user's answer. Missing tools and elapsed time do not constitute approval.

## Instruction isolation

OpenCode 1.18.29 adds instruction files to every agent's system prompt, including reviewers:
the global `AGENTS.md` (or else `~/.claude/CLAUDE.md`); every project `AGENTS.md` from the
working directory up to the worktree root, or else every `CLAUDE.md` on that path, or else every
`CONTEXT.md`; and files or URLs in the `instructions` setting. Each is rendered as `Instructions from: <path>` followed by the file. When an agent
reads a file, the read tool also appends nearby instruction files to its output in a
`<system-reminder>` and lists their paths in `metadata.loaded`.

The installer copies `adapters/opencode/plugin/` into the bundle and lists its `v1.ts` entry
under `plugin`. Its options are `primary`, `bundle`, and `reviewers`, which maps each reviewer's
agent ID to its persona path; the plugin reads only the IDs. For those agents it removes every
instruction block, not only `AGENTS.md`:

- `experimental.chat.messages.transform` records each session's agent from its latest user
  message, and strips the reminder from reviewer sessions' read results.
- `experimental.chat.system.transform`, which runs later in the same step, re-reads each file
  named by an `Instructions from:` line in a reviewer session and removes the block only
  if it matches exactly.

The system hook does not name the agent. OpenCode 1.18.29 adds instructions in one place,
directly after the messages hook runs for the session, so every request that carries them
comes from a recorded session. Requests without instructions, such as title generation, can
come first and pass unchanged.

Changes apply only to the outgoing request; stored history keeps the read output. The `egm`
agent keeps its instructions.

The plugin fails closed. If it cannot verify a block, such as a remote `instructions` URL or a
file that changed during the request, it throws. OpenCode then ends the reviewer task with
`egm-guard: cannot remove the instructions from <path>; refusing the request`
instead of sending it. A request with instructions from a session it never recorded, which
would mean OpenCode changed the order above, is refused the same way for every agent. When the
plugin acts, it logs `[egm-guard] <agent>: removed N instruction block(s)` to stderr.

A plugin that fails to load does not fail closed. OpenCode 1.18.29 logs
`failed to load plugin` at error level, with the plugin's message, and runs the reviewer with
OpenCode's default instructions: the project and nested `AGENTS.md` reach it. The plugin rejects
a missing or malformed `reviewers` map, so that is how a bad configuration fails, and no other
check catches it. A unit test installs both interfaces and passes the generated options to the
plugin's own parser, so an installer that drifts from the plugin fails the test. After a manual
edit to the generated configuration, look for that error in the logs (`opencode --print-logs`).
The native probe installs its own copy, so it checks the installer's output, not a file edited
by hand.

It depends on two experimental hooks and on the rendering above, so repeat the native probe
after upgrading OpenCode. `glob` still shows that an instruction file exists.

## Verification limits

OpenCode merges custom, global, project, and managed configuration.
Inspect the effective configuration before a run; later settings can override these permissions.
Use a clean profile and a disposable project for verification.
Inspect inherited instructions, plugins, MCP services, memory, and shared files separately.
Read-only tool configuration is not process or filesystem isolation.
A fresh child session alone does not prove Goldfish isolation.

Run the offline checks:

```sh
pytest tests/unit/test_opencode_adapter.py
pytest tests/unit
```

These tests check installation, resource identity, native configuration, and refusal to overwrite files.
They do not simulate host completion records or prove enforcement by the host.
No live model test runs in ordinary CI.

The scoped OpenCode native probe uses a scripted local model, not a live model.
It checks native child dispatch, one parent marker, and denial of a synthetic
`.env` read. It also checks that a project `AGENTS.md` reaches the orchestrator but not the
reviewer, and that a nested `AGENTS.md` loaded by a reviewer read is removed while the file's
content arrives. `--interface v2` runs the same checks against the
[V2 adapter](opencode_v2.md#native-probe). The pinned Linux x64 executables are in
`tests/integration/opencode-ci`:

```sh
npm ci --ignore-scripts --prefix tests/integration/opencode-ci
python tests/integration/opencode_native_probe.py \
  --source . \
  --opencode tests/integration/opencode-ci/node_modules/opencode-linux-x64/bin/opencode \
  --output /tmp/egm-opencode-probe-new
```

On another platform, install that platform's package, such as `opencode-darwin-arm64@1.18.29`,
and pass its `bin/opencode`. Choose an output path that does not exist. A passing probe does not establish
live model behavior, full workflows, or general reviewer isolation.

On 2026-10-24, OpenCode `1.18.29` accepted the generated configuration through `debug config` and `debug agent egm-style`.
The historical reviewer toolset enabled `read`, `glob`, and `grep`. The current
candidate denies `grep` to preserve the `.env` read restriction.
The `debug skill` command discovered all seven skills from the installed candidate paths.
These commands made no model calls. This result does not prove task execution or runtime permission enforcement.
Separate XDG directories did not prevent discovery of home-directory skills. A clean verification profile must account for those locations too.
This historical note does not identify the tested EGM commit or installed bundle
checksum. Repeat discovery against the pinned candidate before relying on it for
that candidate.

Before a support claim, explicitly authorize and complete these checks:

1. Record the candidate SHA, installed hashes, host version, model identifier, surface, and date.
2. Run brainstorm, draft, and review with an actual human approval pause.
3. Retain native reviewer starts, completions, required reads, and produced artifacts.
4. Probe write denial against a disposable file and inspect the effective child permissions.
5. Place a random marker only in the parent conversation and inspect child context and output.
6. Report installation, workflow, and isolation outcomes separately. Mark missing evidence as unverified.

For OpenCode 1.18.29, the offline verifier checks one exported child session
against its parent JSONL trace. Supply each required absolute POSIX file path:

```sh
opencode export <child-session-id> > child.json
python tests/integration/opencode_trace_verifier.py \
  --parent-trace parent.jsonl --child-export child.json \
  --require /absolute/path/to/agents/zoom_out.md \
  --require /absolute/path/to/target.md \
  --require /absolute/path/to/standard.md
```

The verifier matches native child and parent session identities, the task
completion and time window, reviewer type, and each tool call's message and
session IDs. It requires a new task without `task_id`. It
requires a nonempty, successful file read for every supplied path before the
child's final response. It matches that response to the parent task result.
Missing, conflicting, malformed, or unsupported evidence
fails. Parent JSONL records are split on literal LF, not Unicode separators.
This does not verify every required path unless the caller supplies it. It does
not prove whole-file coverage, transcript authenticity, context isolation, or
that a running workflow stopped on missing evidence. Do not treat a parent
summary or an absent marker as sufficient isolation evidence.

## Host versions

Each adapter records one probed host release: the newest release the scripted native probe
passed on. It is `probed` in `adapters/opencode/install.py`, `host_version` in
`installation.json`, and the pinned package in `tests/integration/opencode-ci`; a unit test keeps
the three equal. The probe accepts any release of the adapter's major version and records the one
it ran.

A probed release is not a supported one. The probe uses a scripted model and checks one
delegation and its permission and instruction boundaries. Support needs installation, workflow,
and isolation checks to pass, as listed under [Verification limits](#verification-limits).

The isolation plugins depend on experimental hooks and on how OpenCode renders instructions,
and either can change in a minor or patch release. A matching major version is therefore not
evidence of support. Two workflows cover it:

- `OpenCode native probe` runs the probe on each probed release, on pull requests and pushes
  to `main`. It gates changes and does not follow upstream releases.
- `OpenCode latest releases` runs the probe on the newest release of each major version, weekly
  and on demand. It never runs on pull requests, so an upstream release cannot block a change.
  A red run means do not upgrade yet.

To move the probed release, run the probe on the new release, then update all three places
in one change and record the probe summary in the pull request.

## Interface sources

Reviewed on 2026-10-24. The versioned sources define this adapter's interface:

- [V1 agent configuration](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/web/src/content/docs/agents.mdx)
- [V1 config and merge order](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/web/src/content/docs/config.mdx)
- [V1 skill discovery](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/web/src/content/docs/skills.mdx)
- [V1 command syntax](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/web/src/content/docs/commands.mdx)
- [V1 command preprocessing](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/session/prompt.ts)
- [V1 task implementation](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/task.ts)
- [V1 permission evaluator](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/permission/index.ts)
- [V1 MCP resource permission paths](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/session/tools.ts)
- [Current official agent guide](https://opencode.ai/docs/agents/)
