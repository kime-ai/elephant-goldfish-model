# OpenCode reviewer instruction isolation

*   **Author:** [@danielsteinotto](https://github.com/danielsteinotto)
*   **Status:** Proposed. Maintainer scope approval and design review pending.
*   **Date:** 2026-11-10
*   **Tracking:** [OpenCode V1 #146](https://github.com/google/elephant-goldfish-model/issues/146), [OpenCode V2 #282](https://github.com/google/elephant-goldfish-model/issues/282)

--------------------------------------------------------------------------------

## Overview

EGM's Goldfish reviewers must not see the parent conversation, and
[Additional harnesses](additional-harnesses.md#architecture-and-data-flow) adds
that host-injected instructions must be assessed separately. OpenCode adds
instruction files such as `AGENTS.md` to the system prompt of every agent it runs,
including the reviewers, and neither 1.18.29 nor 2.2.6 has a per-agent setting to
turn that off in the audited sources (OpenCode's `anomalyco/opencode` repository,
at the tags in Additional Resources).

The installer adds a server plugin, named `egm-guard`, to each OpenCode
bundle. For a reviewer's request it removes the instruction files before the
request reaches the model. On V2 it keeps an allowlist. On V1 it removes each
instruction block only after matching it against the file on disk. The installer
also denies reviewers direct reads of those files, and a scripted probe runs the
adapter against a real OpenCode binary and checks that planted markers stay out of
the reviewer.

The design leaves one gap open: OpenCode skips a plugin that fails to load, and the
reviewer then runs unisolated (see the first Open Question).

### Terms

*   **Goldfish reviewer**: one of eight read-only subagents (`egm-codebase-details`,
    `egm-comprehension`, `egm-design`, `egm-implementation-readiness`,
    `egm-inventive-catalyst`, `egm-structural`, `egm-style`, `egm-zoom-out`) that
    review a document without the parent conversation.
*   **`egm`**: the orchestrator, the primary agent that dispatches reviewers.
*   **Persona**: the Markdown file in `agents/` that defines one reviewer.
*   **Bundle**: the copy of EGM that the installer writes next to the generated
    `opencode.json`.
*   **Host guide**: `docs/opencode.md` (V1) or `docs/opencode_v2.md` (V2).
*   **Interface**: OpenCode's V1 or V2 configuration format. The installer's
    `--interface` option selects which one it writes.
*   **Plugin entry**: the item in the generated configuration's plugin list
    (`plugin` on V1, `plugins` on V2) that names the plugin's package.
*   **Hook**: a function that a plugin registers for OpenCode to call at a fixed
    point, such as before each model call, with the data it is about to use.
*   **System part and source**: the system prompt is a list of parts. On V2 one
    part holds the instruction sources, such as `core/instructions`,
    `core/skills`, `core/date`, and `core/environment`, each as one entry in the
    part's `metadata.experimental.instructions` list.
*   **Synthetic message**: a message OpenCode adds to a session on its own, rather
    than one the user or the model produced.
*   **Probe**: the scripted native probe,
    `tests/integration/opencode_native_probe.py`. It sends the adapter's requests to
    a local stand-in server that returns fixed replies, and records every request
    that server receives.
*   **Pinned release**: the OpenCode release that CI installs from a lockfile and
    that the installer records for an interface. CI checks that the probe passes on
    it.
*   **Guard**: the larger V2 plugin proposed on #282. This design's plugin
    implements the guard's instruction isolation and uses the same ID and options.

### Versions

| Interface | Source audited | Pinned release |
| :-------- | :------------- | :------------- |
| V1 | `v1.18.29` | 1.18.29 |
| V2 | `v2.2.6` | 2.2.6 |

The installer and the CI lockfile each hold the pin, and a unit test keeps them
equal.

## The Problem

OpenCode's host guidance reaches reviewers in both interfaces. A reviewer that sees
the project's guidance may be influenced by it, which the Goldfish model is built
to prevent.

### V1 (1.18.29)

`session/prompt.ts` builds the system prompt for every agent from
`instruction.system()`. That includes the global `AGENTS.md` (or else
`~/.claude/CLAUDE.md`); every project `AGENTS.md` from the working directory up to
the worktree root (or else every `CLAUDE.md`, or else every `CONTEXT.md`); and
files and URLs in the `instructions` setting. Each is rendered as
`Instructions from: <path>` followed by the file (`session/instruction.ts`). When
an agent reads a file, `tool/read.ts` also appends nearby instruction files to the
result in a `<system-reminder>` and lists their paths in `metadata.loaded`. The
plugin hook that can edit the system prompt, `experimental.chat.system.transform`,
receives a session ID and a model, not the agent. V1 omits the skills section of
the prompt when an agent denies `skill`, and filters the MCP guidance section by
the tools the agent denies (`session/system.ts`). Reviewers deny every tool but
`read` and `glob`, so they receive neither section, except MCP guidance from a
server that exposes no tools.

### V2 (2.2.6)

Every instruction source reaches every agent: the global and project `AGENTS.md`,
configured instruction files, and Code Mode, MCP, skill, and reference guidance,
which describe the tools and resources an agent has. They sit in one system part,
together with the date and environment
(`session/model-request.ts`). A nested `AGENTS.md`, loaded when an agent reads a
file, arrives as a synthetic message (`session/instructions.ts`). OpenCode
announces an instruction change with a system message. It also offers each agent
the `skill` tool, even when the agent's rules deny it, and refuses the call, so a
reviewer is offered a tool it cannot use. `Agent.Info`, the agent definition, has
no setting for any of this. Its fields are `id`, `name`, `model`, `request`,
`system`, `description`, `mode`, `hidden`, `color`, `steps`, and `permissions`.

### Observed

The probe puts a marker in a project `AGENTS.md` and another in a nested
`pkg/AGENTS.md`, and has an `egm-zoom-out` reviewer read a file in `pkg/`. It
runs in a clean temporary home directory against a fresh install, and the
stand-in server records every request it receives. With the plugin entry removed
from the generated configuration, both markers appear in the requests the
reviewer sends, on V1 1.18.29 and V2 2.2.6. On V2 the reviewer is also offered
`skill`. With the plugin entry in place, the same probe passes. `egm` receives the
project marker in both runs, as intended. The probe writes what it saw to
`summary.json` and `child-observations.json` in its output directory.

The only host-level switch found in the cited sources,
`OPENCODE_DISABLE_PROJECT_CONFIG=1`, applies to the whole server, so it would
also remove the orchestrator's instructions.

## Goals

*   Reviewers on V1 and V2 receive no host-injected instruction files, whether
    ambient (global or project) or nested (loaded by a read). On V2 the system
    prompt and tools are an allowlist; messages are filtered by kind, which is
    best effort (see the V2 messages Open Question).
*   `egm` keeps its instructions.
*   The plugin refuses the request in the cases it can detect. It throws, and the
    request is not sent, when it cannot tell what to remove: on V1, an instruction
    block it cannot verify against its file, or instructions arriving from a
    session it never recorded; on V2, a `context` request that no longer contains
    the agent's own prompt. The V2 `compaction` and `generate` hooks reduce the
    request but do not throw. A request the plugin never sees, because it did not
    load, is outside this guarantee.
*   The installer gives the plugin the contract proposed on #282: the plugin ID
    `egm-guard` and the options `{ primary, bundle, reviewers }`. `reviewers` maps
    each reviewer's agent ID to its persona path, and this plugin uses the IDs.
    `primary` is the orchestrator's agent ID and `bundle` is the absolute path of
    the installed bundle. This plugin does not use them, and the full guard does.
    The contract exists so that pointing the plugin entry at the guard's package
    substitutes the guard.
*   A scripted probe asserts that the markers stay out of the reviewer on each
    interface. CI runs it on the pinned release of each interface for every
    relevant change, and on the newest release of each major version weekly.
*   V2 reviewers are offered exactly `read` and `glob`, so transcripts show no denied tool
    calls.

## Non-Goals

*   Reviewer dispatch control, required-read checks, and path hardening beyond
    the read rules. These belong to the guard under design on #282, which is not
    merged.
*   Fatal behavior when the plugin does not load; see the first Open Question.
*   Isolation for agents other than the eight reviewers the installer lists. A
    renamed reviewer or a user-defined subagent is not isolated.
*   Guidance that `egm` itself relays. `egm` keeps the project's instructions and
    writes each dispatch prompt, so it can quote them to a reviewer. The skills tell
    it to pass paths and standards, not conversation, and nothing enforces that.
*   MCP, skill, and reference guidance on V1, which reviewers do not receive for
    the reasons in the Problem, except for guidance from an MCP server that exposes
    no tools. Nested instruction files and read reminders on V1 are in scope.
*   A support claim. See [Additional harnesses](additional-harnesses.md#validation-and-release-gates).
*   Changes to OpenCode. #282 lists them as a non-goal.
*   A generic adapter framework. The installer and probe each hold one table with
    a row per OpenCode interface.
*   Isolation from memory, MCP services, other plugins, or shared files, which
    need separate assessment, as the additional-harnesses design says.
*   Protection from a reviewed repository's own project configuration and
    plugins. OpenCode trusts them; an untrusted repository needs
    `OPENCODE_DISABLE_PROJECT_CONFIG=1`.
*   Bootstrap delegation and global installation, which
    [#364](https://github.com/google/elephant-goldfish-model/issues/364) proposes.

## Open Questions

*   **Fatal when missing**: Should reviewer dispatch depend on the plugin, as the
    guard on #282 does by denying dispatch until the plugin grants it? A plugin that
    does not load is the largest known failure, and it is silent. V1 has no
    equivalent mechanism yet. A model-checked canary in the reviewer's prompt is a
    weaker alternative, since it depends on the model following an instruction.
*   **V2 messages**: V2 messages are filtered by kind, not allowlisted, so a new
    injection channel that is neither a synthetic nor a text-bearing system message
    would pass. Allowlisting by provenance needs OpenCode to say which messages a
    reviewer session created. Is that available, and is it worth the risk of
    dropping a legitimate message?
*   **V1 location**: The V1 entry is placed in the V2 plugin directory provisionally. Should the V1 entry (the V1 plugin file `v1.ts`) share the V2 plugin directory,
    or live in a V1-only directory? #146 tracks V1 separately from #282.
*   **Direct reads**: Should reviewers keep their denied direct reads of `AGENTS.md`
    and, on V1, `CLAUDE.md` and `CONTEXT.md`? Keeping them is the current choice, because it closes the
    one path the plugin cannot, and a review of an instruction file can use a copy
    under another name. The cost is a refused review whose target is one of those
    files, and a symlink or another letter case bypasses the rule.
*   **V1 remote instructions**: A remote `instructions` URL makes every V1
    reviewer request fail, because the plugin cannot verify it. Should the plugin
    instead trust the configured URL list?
*   **Successor**: When the guard merges, should this plugin become its isolation
    module or be removed?
*   **Re-pinning**: What criteria move the pinned release, and who acts on a
    failed weekly run?

## Critical User Journeys (CUJs)

### CUJ 1: A V2 reviewer sees only its own context

*   **Given**: The V2 adapter is installed. The project's `AGENTS.md` and a
    nested `pkg/AGENTS.md` each hold a distinct marker.
*   **When**: `egm` dispatches `egm-zoom-out`, and the reviewer reads a file in
    `pkg/`.
*   **Then**: No request from the reviewer contains either marker. The reviewer
    keeps its persona prompt, the date and environment, the dispatched task, its
    own tool results, and the tools `read` and `glob`. `egm`'s requests still
    contain the project marker.

### CUJ 2: A V1 reviewer sees only its own context

*   **Given**: The V1 adapter is installed, with the same two markers.
*   **When**: `egm` dispatches `egm-zoom-out`, and the reviewer reads a file in
    `pkg/`.
*   **Then**: The reviewer's system prompt has no `Instructions from:` block, and
    the read result has the file's content without a `<system-reminder>`. `egm`
    keeps its instructions.

### CUJ 3: The plugin cannot verify what it would remove

*   **Given**: A V1 reviewer's system prompt names a remote instruction URL, or an
    instruction file changed between OpenCode's read of it and the plugin's later
    read.
*   **When**: OpenCode builds the reviewer's request.
*   **Then**: The plugin throws `egm-guard: cannot remove the instructions from
    <path>; refusing the request`, where `<path>` is the URL in the first case. The
    reviewer's task ends in an error and no request reaches the model. A changed
    file clears on a retry once it stops changing. A URL fails every time, until
    the user removes it from `instructions` or replaces it with a local file, which
    the plugin verifies against the disk.

### CUJ 4: A new OpenCode release changes what the plugin relies on

*   **Given**: A newer release renames `metadata.experimental.instructions`.
*   **When**: The weekly workflow probes the newest release of that major version.
*   **Then**: The run fails. The pull request workflow, which probes the pinned
    releases, is unaffected, and the pinned release does not move.

### CUJ 5: The plugin does not load

*   **Given**: The generated configuration lists the plugin, but OpenCode cannot
    load it, for example because its options were edited by hand. The plugin
    validates its options when it loads.
*   **When**: OpenCode starts and a reviewer runs.
*   **Then**: OpenCode logs `failed to load plugin` for `egm-guard`, at warning
    level on V2 and error level on V1, and the reviewer runs with OpenCode's
    default instructions. The log line is the only signal.

## Technical Plan (Architecture)

The installer writes a plugin entry into each interface's configuration and copies
`adapters/opencode/plugin/` into the bundle. The plugin acts only on requests made
by the agents named in `reviewers`.

```text
installer ──► opencode.json ──► plugin options { primary, bundle, reviewers }

V2   hooks: context, compaction, generate     (before each model call)
     request from a reviewer ──► reduce ──► model
       system:   the agent's own prompt, core/date, core/environment
       messages: the reviewer's own; not synthetic or text-bearing system messages
       tools:    read, glob

V1   hooks, in order within one step:
     1. experimental.chat.messages.transform ──► record the session's agent;
                                                 strip read reminders for reviewers
     2. experimental.chat.system.transform   ──► for reviewer sessions, remove each
                                                 "Instructions from:" block that
                                                 matches its file exactly
```

### V2 keeps an allowlist for the system prompt and tools

The `context` hook runs before each model call. Its event carries the calling
agent's ID, the session ID, the assembled system parts, the messages, and the
tools, and the plugin may edit them. The plugin reads the agent's own prompt once
per agent from the agent definition (`ctx.agent.get`) and the session's messages
from `ctx.session.context`. A system part's text is the join of its sources' texts,
so the plugin rebuilds the text from the sources it keeps and updates the part's
metadata to match; it matches no wording.

*   **System.** The plugin keeps a part whose text equals the agent's own system
    prompt, read from the agent definition, so no instruction content rides in it
    unless the persona itself contains it. From the part that holds the sources it
    keeps the `core/date` and `core/environment` sources and removes every other
    source, including kinds OpenCode adds later. It removes every other part.
*   **Transcript.** It removes the messages OpenCode injected, by kind. A synthetic
    message is identified by ID: the plugin reads the session's messages, collects
    the IDs of those typed `synthetic`, and drops each request message carrying one
    of those IDs. OpenCode gives a request message built from a synthetic message
    that message's ID (`session/runner/to-llm-message.ts`). A system message that
    carries text is dropped, because OpenCode uses
    system messages to announce instruction changes. In a reviewer session these are
    nested instruction loads, notices from plugins, and instruction announcements.
    The reviewer's own user, assistant, and tool messages stay, and the probe asserts
    that the dispatched task and the reviewer's tool results survive. Unlike the
    system prompt, messages are not an allowlist: see the second Open Question.
*   **Tools.** It removes every tool except `read` and `glob` from the list sent to
    the model, including `skill`. The installer grants reviewers exactly those two
    tools. A future reviewer that needs another tool needs a change here.
*   **Failure.** If a request from the `context` hook no longer contains the
    agent's own prompt, OpenCode builds requests in a way the plugin does not
    recognize, and the plugin throws. The `compaction` hook, which runs for
    conversation summaries, and the `generate` hook, which runs for requests that
    plugins issue, apply the same reduction without that check. The probe does not
    run either hook.

### V1 removes by verification

V1's system hook receives a session ID but not the agent, and V1 marks no
structural boundary around an instruction block. The messages hook runs first in
the same step, because `session/prompt.ts` triggers it before it calls
`instruction.system()`.

*   **Reminder strip.** The reminder is anchored as
    `\n\n<system-reminder>\nInstructions from: <first loaded path>\n` and must end
    the output. If `Instructions from: <path>` text is present but not strippable,
    the plugin refuses the request. If the format changed so that it is absent, the
    reminder stays silently, which the probe's markers detect.
*   **Messages hook.** It records the session's agent from the latest user message,
    which carries the reviewer's agent name in a delegated session; the probe checks
    this. For a reviewer session it strips the `<system-reminder>` that `read`
    appended, for each read result whose `metadata.loaded` lists instruction paths.
    Sessions are keyed by ID, so reviewers dispatched in parallel do not share state,
    and the record is never removed.
*   **System hook.** For a reviewer session it takes the first line that starts
    `Instructions from: <path>` and re-reads that path from disk, only if it is
    absolute. It removes the block only if the text from that line equals
    `Instructions from: <path>\n<file>` and is followed by a line break or the end
    of the text. It then looks for the next header in what remains, and repeats. A
    header line inside a verified file is part of that file's block and is removed
    with it. A relative path, a URL, a missing file, or any difference in the text
    throws. The plugin only compares the file; it never sends it. OpenCode renders a
    file without a leading byte order mark, so the plugin drops one first.
    A manual observation on 1.18.29, not retained as a script: CRLF line endings, non-ASCII text, invalid UTF-8, a 320 KB file, no
    final newline, extra blank lines, tabs, and a symlink all matched.
*   **Unrecorded sessions.** V1 calls the system hook for every request its
    session code makes, such as title and summary requests. Only the main loop, the
    code that runs the agent's turns, passes instructions to it, and that loop always
    runs the messages hook first. The plugin treats instructions arriving from a
    session it never recorded as an error for any agent, since it would mean OpenCode
    changed the order.

### Read rules

Reviewers also deny direct reads of the instruction files by exact name, at the
root and in any directory: `AGENTS.md`, and on V1 `CLAUDE.md` and `CONTEXT.md`,
each also in lowercase. Other names stay readable. Removing the plugin entry leaves these denials in place. This is defense in depth, not a
boundary: it does not cover other letter cases, symlinks, or files named in the
`instructions` setting. `egm` has no such rule.

### One table per interface

`install.py` and the probe each hold a table keyed by interface (`v1`, `v2`), in
code. The installer's rows hold the pinned release, the host guide, and the
configuration builder. `--interface` selects a row.

### The probe

It installs the adapter, runs `opencode run`, delegates once to a reviewer, and has
the reviewer read a file beside the nested `AGENTS.md` and then `.env`. The planted
markers are one in the project `AGENTS.md` and one in the nested file, plus a
parent-only marker placed in the prompt that `egm` receives, to check that
dispatch does not pass the parent conversation. It asserts that none of them
reaches the reviewer except where intended, that `.env` is denied, and that the
reviewer keeps its persona prompt and environment, so an allowlist that strips too
much fails. It does not plant a global `AGENTS.md`, a `CLAUDE.md` or `CONTEXT.md`,
a file named in `instructions`, or MCP or skill guidance; unit tests cover those
paths in the plugin's logic, not on a host.

### CI

Two GitHub Actions workflows run the probe. `opencode-native.yml` probes each
interface's pinned release from a lockfile, on pull requests and pushes.
`opencode-latest.yml` probes the newest release of each major version weekly and on
demand, and never on pull requests, so an upstream release cannot block a change.

### Relationship to the guard on #282

The V2 guard under design there
([spike](https://github.com/Israel-Kli/elephant-goldfish-model/tree/b6c8913080a290adacb3ef479eaf10cffc00bd47))
installs a plugin with the same ID and options and a larger scope: it denies
reviewer dispatch until it grants it for one call, checks that the reviewer read
the files the stage requires, and re-checks resolved read paths. This design's V2
plugin implements the part that keeps instructions out, and the installer writes
the same contract, so the guard can replace it by changing the plugin entry's
package. The installer writes one plugin entry, so the two cannot both load. This
design adds V1, which the guard does not cover, and the probe.

## Risks and Mitigations

Three behaviors were observed on 2026-11-10 on V1 1.18.29 and V2 2.2.6: the plugin
absent, the plugin failing to load, and a plugin hook throwing. An unretained script
that reuses the probe's install and run steps produced them. No script or log is
retained, and no test automates them.

| Risk | Effect | Mitigation |
| :--- | :----- | :--------- |
| The plugin fails to load | Both interfaces log `failed to load plugin` and run the reviewer unisolated (observed) | Mitigated in part: a test passes the installer's options to the plugin's parser, and the log line is visible. Deferred: fatal-when-missing (Open Question) |
| A plugin hook throws | The request is not sent, and the task ends in an error (observed) | Deferred: automate the check (Future Improvements) |
| OpenCode renames `metadata.experimental.instructions` (V2) | The part that holds the sources becomes unlabeled and is removed, with the date and environment. The reviewer loses its environment and receives nothing back | The probe asserts the environment survives; the weekly run reports it |
| OpenCode stops giving request messages the ID of the session message they came from (V2) | Nested instructions pass through | The probe's nested marker fails; the weekly run reports it |
| OpenCode adds a new injected message kind (V2) | It passes through, since messages are filtered by kind | Open Question: V2 messages |
| OpenCode changes the `Instructions from:` rendering or `metadata.loaded` (V1) | Blocks and reminders are not found and stay, silently | The probe's markers fail; the weekly run reports it |
| The installer's `--host` is now `--interface` with no alias, and the V2 pin moves from 2.2.5 to 2.2.6 | Scripts and instructions that pass `--host` fail | Accepted: the adapters are experimental and the guides change in the same PR |
| A V1 prompt contains a line starting `Instructions from: ` | The plugin cannot match it to a file and refuses every request for that agent | A unit test checks that no generated agent prompt has such a line |
| OpenCode changes the hook order (V1) | Every request that carries instructions is refused, including `egm`'s, so the whole session stops | The probe fails; the weekly run reports it. Accepted: it fails closed |
| `compaction` or `generate` requests change shape (V2) | The unit tests cover their reduction, but no host run does | Deferred: extend the probe (Future Improvements) |
| A V1 instruction file changes between OpenCode's read and the plugin's | The request is refused and one reviewer run fails | Accepted: a retry succeeds once the file stops changing |
| A V1 project configures a remote `instructions` URL | Every reviewer request fails | CUJ 3; Open Question |
| `egm` quotes the project's guidance in a dispatch prompt | The reviewer sees it | Not mitigated; a Non-Goal |
| Another plugin edits the request after this one, or a reviewer is not in `reviewers` | Its additions reach the reviewer, or the reviewer is not isolated | Not mitigated; Non-Goals |
| A reviewer reads an instruction file through a symlink or another letter case | The read succeeds | Accepted: the read rules are defense in depth only |
| The guard's ID or options change before it merges | The plugin entry no longer matches it, and the entry fails to load | Deferred: the installer and plugin must follow the guard's final contract |
| The V1 session record grows | One string per session until the server restarts | Accepted: V1 has no session-end hook |
| A failed weekly run goes unseen | The pinned release stays, and nobody learns that the newest release breaks | Open Question: re-pinning and ownership |

## Alternatives Considered

### Alternative A: Configuration only

*   **Pros**: No plugin; nothing for OpenCode to break.
*   **Cons**: No per-agent setting exists on either interface. Read rules block
    direct reads but not injected content. `OPENCODE_DISABLE_PROJECT_CONFIG=1`
    also removes the orchestrator's instructions.
*   **Reason for Rejection**: It cannot isolate reviewers without also changing
    the orchestrator.

### Alternative B: Disable project config and give `egm` its instructions explicitly

*   **Pros**: Reviewers get no project instructions, and no request needs editing.
*   **Cons**: The global `AGENTS.md` is expected to still reach reviewers; the flag
    is documented as a project-configuration switch and this was not tested. `egm` loses the
    project's instructions unless the installer copies them into its prompt, which
    goes stale, or something loads them for it at run time. The flag also disables
    the rest of project configuration.
*   **Reason for Rejection**: It leaves the global instructions in place and
    replaces the removal problem with a staleness problem.

### Alternative C: Tell reviewers to ignore `AGENTS.md`

*   **Pros**: Needs no code.
*   **Cons**: A reviewer that does not follow the instruction still sees the file,
    and the additional-harnesses design says an instruction to avoid something does
    not establish enforced isolation.
*   **Reason for Rejection**: It is not enforcement.

### Alternative D: Run reviewers in a clean directory

*   **Pros**: A directory without an `AGENTS.md` has none to inject.
*   **Cons**: The global `AGENTS.md` still applies, and reviewers must read the
    project's files, which needs external-directory permissions on V2.
*   **Reason for Rejection**: It solves part of the problem and widens reviewers'
    filesystem access.

### Alternative E: A denylist on V2

*   **Pros**: Smaller change: remove only the `core/instructions` source and match
    nested instructions by their text.
*   **Cons**: Every other source still reaches reviewers, new sources would too,
    and matching text depends on OpenCode's wording. An
    [earlier version of this plugin](https://github.com/kime-ai/elephant-goldfish-model/blob/e8dd3bc/adapters/opencode/goldfish_isolation/isolate.ts)
    did this.
*   **Reason for Rejection**: On V2 an allowlist for the system prompt fails closed,
    and message removal by kind needs no text matching. V1 has no structural marker,
    so V1 does match text, and verifies each match against its file.

### Alternative F: A separate OpenCode process per reviewer

*   **Pros**: A process started with `OPENCODE_DISABLE_PROJECT_CONFIG=1` carries no
    project instructions, and nothing needs editing in the request.
*   **Cons**: Reviewers are native subagents of the orchestrator's session. A
    separate process would need EGM to build its own transport and result
    collection, which the additional-harnesses design lists as a non-goal. The
    global `AGENTS.md` still applies.
*   **Reason for Rejection**: It replaces native delegation with a framework.

### Alternative G: Wait for the guard on #282

*   **Pros**: One plugin, and no duplicated V2 work.
*   **Cons**: The design is unmerged and covers V2 only. V1 has no plan for
    instruction isolation, and no probe checks either.
*   **Reason for Rejection**: Not adopted alone. This design proceeds in parallel
    with a contract the guard can adopt, so the V2 plugin is replaceable.

## Non-Functional Requirements

*   **Security**: The plugin refuses the request in the cases listed under Goals. A plugin that is not loaded refuses nothing. Log lines name the agent and a count, never file content.
*   **Cost**: Not measured. On V2 each model call reads the reviewer session's
    history, which grows with the session; reviewer sessions are short. On V1 the
    plugin reads one file per instruction block.
*   **Rollout and rollback**: Remove the plugin entry from the generated
    `opencode.json` to restore OpenCode's defaults. V1 and V2 installs are
    separate, and V1 output outside the plugin entry and the read rules is
    unchanged.
*   **Dependence on experimental OpenCode behavior**: Both plugins rely on experimental OpenCode behavior. Risks and
    Mitigations lists each dependency and what detects a change.

### Additional Resources

*   [Additional harnesses](additional-harnesses.md) and the
    [OpenCode V1 tracking issue #146](https://github.com/google/elephant-goldfish-model/issues/146)
*   [Add verified OpenCode V2 support #282](https://github.com/google/elephant-goldfish-model/issues/282),
    including the
    [guard plugin spike](https://github.com/Israel-Kli/elephant-goldfish-model/tree/b6c8913080a290adacb3ef479eaf10cffc00bd47)
    that proposes the plugin ID and options used here
*   [OpenCode V2 adapter notes #364](https://github.com/google/elephant-goldfish-model/issues/364)
*   OpenCode source: `packages/opencode/src/session/instruction.ts`,
    `session/prompt.ts`, `session/system.ts`, and `tool/read.ts` at tag
    `v1.18.29`; `packages/core/src/session/model-request.ts` and
    `session/instructions.ts` at tag `v2.2.6`

### Future Improvements

*   **A native switch**: A per-agent setting in OpenCode to skip instruction files
    could replace both plugins. None was requested upstream when this was written:
    a search of the `anomalyco/opencode` issue tracker on 2026-11-10 for
    "AGENTS.md subagent" and "instructions per agent disable" found no matching
    request. Filing one is a first step.
*   **A failure-mode probe**: Automate the observations in Risks and Mitigations. It
    would catch OpenCode starting to swallow hook errors, which would turn a
    fail-closed request into a silent leak, and OpenCode making a missing plugin
    fatal, which would make the first Open Question obsolete.
*   **A wider probe**: Plant a global `AGENTS.md`, a `CLAUDE.md` and `CONTEXT.md`,
    and a file named in `instructions`, and exercise the `compaction` and `generate`
    hooks.
*   **Live evidence**: Run brainstorm, draft, and review on a clean profile with a
    fixed model and real approval pauses, as #146 and #282 require.

--------------------------------------------------------------------------------

## Detailed Implementation Plan

### Target Files to Create/Modify

#### 1. `adapters/opencode/install.py` (Modify)

*   **Type / Scope**: Python installer.
*   **Proposed Changes**: Select the configuration interface with
    `--interface {v1,v2}` through one `Interface` record per interface (the pinned
    release, as `probed`; the host guide; the configuration builder; extra trees).
    Copy `adapters/opencode/plugin/` into both bundles. Pass the plugin
    `{ primary, bundle, reviewers }` options. Add the instruction-file read denials
    to reviewers.

#### 2. `adapters/opencode/plugin/index.ts`, `isolate.ts`, `options.ts` (Create)

*   **Type / Scope**: V2 server plugin. `isolate.ts` holds the reduction and the
    reviewer guard with its lookups injected; `index.ts` wires them to the host
    through `Plugin.define`; `options.ts` validates `reviewers`.
*   **Proposed Changes**: As in the Technical Plan. Plugin ID `egm-guard`.

#### 3. `adapters/opencode/plugin/v1.ts`, `isolate_v1.ts` (Create)

*   **Type / Scope**: V1 plugin entry and its host-independent logic.
*   **Proposed Changes**: The `isolation()` factory with the two hook handlers, the
    absolute-path file reader, and the entry that wires them.

#### 4. `tests/integration/opencode_native_probe.py` (Modify)

*   **Type / Scope**: Scripted native probe.
*   **Proposed Changes**: One `Interface` record per OpenCode interface (flags,
    delegation call, reviewer calls, expected tools, denials, mock provider
    configuration, where the delegation event records its sessions). Shared
    checks. `--interface` selects a row.

#### 5. Tests (Create/Modify)

*   **Type / Scope**: `tests/unit/goldfish_isolation.test.ts` (V2) and
    `goldfish_isolation_v1.test.ts` (V1), run under Bun by
    `test_goldfish_isolation.py`; `test_opencode_adapter.py`;
    `test_opencode_native_probe.py`; `test_ci_workflow.py`.
*   **Proposed Changes**: Behavior tests for each property above, including
    malformed metadata, unknown sources, a missing own prompt, relative paths, a
    byte order mark, and an unverifiable block. A test passes the installer's
    options to the plugin's parser. A test keeps the installer's pinned releases
    equal to the lockfile.

#### 6. `.github/workflows/opencode-native.yml` (Modify), `opencode-latest.yml` (Create), `tests.yml` (Modify)

*   **Type / Scope**: GitHub Actions.
*   **Proposed Changes**: The pinned probe for both interfaces; the weekly latest
    probe; Bun in the unit job. `tests/integration/opencode-ci/package.json` and its
    lockfile pin the Linux packages.

#### 7. `docs/opencode.md`, `docs/opencode_v2.md` (Modify)

*   **Type / Scope**: Host guides.
*   **Proposed Changes**: "Instruction isolation" and "Host versions" sections;
    the V2 guide's "Native probe". The guides rename `--host` to `--interface` (no
    alias) and move the V2 release from 2.2.5 to 2.2.6. A relevant change is one that
    matches the workflows' path filters.

### Verification Plan

*   **Unit Tests**: `pytest tests/unit`. The Bun tests need Bun, which CI
    installs.
*   **Static Analysis & Linting**: `tsc --strict` against `@opencode-ai/plugin`
    1.18.29 and `@opencode/plugin` 2.2.6; `actionlint` on the workflows.
*   **E2E/Integration**: `python tests/integration/opencode_native_probe.py
    --interface v1|v2 --source . --opencode <binary> --output <new directory>` on
    each pinned release. The probe fails with the plugin entry removed: on V1 with
    "Project instructions reached child", and on V2 on the reviewer's toolset.
*   **Not covered**: The sources and hooks listed under The probe, live model
    behavior, full brainstorm, draft, and review workflows, and approval pauses.
    Support stays unverified until those pass.

--------------------------------------------------------------------------------

*Drafted with EGM*
