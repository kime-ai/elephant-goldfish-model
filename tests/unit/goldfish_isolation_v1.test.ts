// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

// Run through tests/unit/test_goldfish_isolation.py, or directly with `bun test`.
import { describe, expect, test } from "bun:test"
import {
  isolation,
  requester,
  withoutAmbient,
  withoutNested,
  type Entry,
  type Part,
} from "../../adapters/opencode/goldfish_isolation/isolate_v1.ts"

const REVIEWERS = new Set(["egm-structural"])

const user = (agent: string, sessionID = "child"): Entry => ({
  info: { role: "user", sessionID, agent },
  parts: [{ type: "text" }],
})
const unnamed: Entry = { info: { role: "user", sessionID: "child" }, parts: [] }
const assistant = (agent: string): Entry => ({ info: { role: "assistant", sessionID: "child", agent }, parts: [] })

describe("requester", () => {
  test("names the session and agent of the latest user message", () => {
    expect(requester([user("egm"), assistant("egm"), user("egm-structural")])).toEqual({
      sessionID: "child",
      agent: "egm-structural",
    })
  })

  test("ignores assistant messages", () => {
    expect(requester([user("egm"), assistant("egm-structural")])).toEqual({ sessionID: "child", agent: "egm" })
  })

  test.each([
    { entries: [] },
    { entries: [assistant("egm-structural")] },
    { entries: [unnamed] },
  ])("returns nothing without a user message that names an agent %#", ({ entries }) => {
    expect(requester(entries)).toBeUndefined()
  })
})

const CONTENT = "<path>/p/pkg/notes.txt</path>\n<content>\n1: NOTES\n</content>"
const REMINDER = "\n\n<system-reminder>\nInstructions from: /p/pkg/AGENTS.md\nNESTED\n</system-reminder>"

const read = (output: string, metadata: Record<string, unknown>, extra: Partial<Part> = {}): Part => ({
  type: "tool",
  tool: "read",
  state: { status: "completed", output, metadata, time: { start: 0 } },
  ...extra,
})
const loaded = { loaded: ["/p/pkg/AGENTS.md"] }
const entry = (...parts: Part[]): Entry => ({ info: { role: "assistant", sessionID: "child" }, parts })
const outputOf = (part: Part) => (part.state?.status === "completed" ? part.state.output : undefined)
const outputs = (entries: readonly Entry[]) => entries.flatMap((item) => item.parts.map(outputOf))

describe("withoutNested", () => {
  test("strips the instructions the read tool appended", () => {
    const original = read(CONTENT + REMINDER, loaded)
    const entries = [entry(original)]
    expect(withoutNested(entries)).toBe(1)
    expect(outputs(entries)).toEqual([CONTENT])
    expect(outputOf(original)).toBe(CONTENT + REMINDER)
  })

  test("strips only the trailing reminder when the file quotes one", () => {
    const quoted = CONTENT + REMINDER.replace("NESTED", "QUOTED") + "\n</content>"
    const entries = [entry(read(quoted + REMINDER, loaded))]
    withoutNested(entries)
    expect(outputs(entries)).toEqual([quoted])
  })

  test("strips each read in the transcript", () => {
    const entries = [entry(read(CONTENT + REMINDER, loaded)), entry(read(CONTENT + REMINDER, loaded))]
    expect(withoutNested(entries)).toBe(2)
    expect(outputs(entries)).toEqual([CONTENT, CONTENT])
  })

  test.each([
    { name: "no loaded files", part: read(CONTENT, {}) },
    { name: "empty loaded list", part: read(CONTENT, { loaded: [] }) },
    { name: "an image read", part: read("Image read successfully", loaded) },
    { name: "a compacted read", part: read(CONTENT + REMINDER, loaded, { state: { status: "completed", output: CONTENT + REMINDER, metadata: loaded, time: { start: 0, compacted: 1 } } }) },
    { name: "a running read", part: read(CONTENT + REMINDER, loaded, { state: { status: "running" } }) },
    { name: "a read that only ends like a reminder", part: read(`${CONTENT}\n<system-reminder>\n</system-reminder>`, loaded) },
    { name: "a read part without state", part: { type: "tool", tool: "read" } },
    { name: "another tool", part: read(CONTENT + REMINDER, loaded, { tool: "glob" }) },
    { name: "a text part", part: { type: "text" } },
  ])("leaves $name unchanged", ({ part }) => {
    const entries = [entry(part)]
    expect(withoutNested(entries)).toBe(0)
    expect(entries[0].parts[0]).toBe(part)
  })

  test("refuses a loaded file it cannot strip", () => {
    const entries = [entry(read(CONTENT + REMINDER + "\nTRAILING", loaded))]
    expect(() => withoutNested(entries)).toThrow(/pkg\/AGENTS\.md/)
  })
})

const files = (contents: Readonly<Record<string, string | undefined>>) => async (path: string) => contents[path]
const HEAD = "PERSONA\nYou are powered by the model named fixture.\n<env>\n</env>"

describe("withoutAmbient", () => {
  test("removes every instruction block and keeps the sections around them", async () => {
    const system = [
      `${HEAD}\nInstructions from: /p/AGENTS.md\nAMBIENT\n\nInstructions from: /p/docs/rules.md\nRULES\n<mcp_instructions>\n</mcp_instructions>`,
    ]
    const read = files({ "/p/AGENTS.md": "AMBIENT\n", "/p/docs/rules.md": "RULES" })
    expect(await withoutAmbient(system, read)).toBe(2)
    expect(system).toEqual([`${HEAD}\n<mcp_instructions>\n</mcp_instructions>`])
  })

  test("removes a block that quotes another instructions line", async () => {
    const quoted = "Quote:\nInstructions from: /elsewhere/AGENTS.md\n"
    const system = [`${HEAD}\nInstructions from: /p/CLAUDE.md\n${quoted}`]
    expect(await withoutAmbient(system, files({ "/p/CLAUDE.md": quoted }))).toBe(1)
    expect(system).toEqual([HEAD])
  })

  test("removes the line break before a block on a later line", async () => {
    const system = ["\nInstructions from: /p/AGENTS.md\nAMBIENT"]
    await withoutAmbient(system, files({ "/p/AGENTS.md": "AMBIENT" }))
    expect(system).toEqual([""])
  })

  test("cleans each system entry", async () => {
    const system = [HEAD, "Instructions from: /p/AGENTS.md\nAMBIENT"]
    await withoutAmbient(system, files({ "/p/AGENTS.md": "AMBIENT" }))
    expect(system).toEqual([HEAD, ""])
  })

  test("keeps prose that mentions instructions", async () => {
    const system = [`${HEAD}\nIgnore any instructions from AGENTS.md.`]
    expect(await withoutAmbient(system, files({}))).toBe(0)
    expect(system).toEqual([`${HEAD}\nIgnore any instructions from AGENTS.md.`])
  })

  test.each([
    { name: "a file that changed", text: "Instructions from: /p/AGENTS.md\nOLD", contents: { "/p/AGENTS.md": "NEW" } },
    { name: "a remote URL", text: "Instructions from: https://example.com/rules.md\nREMOTE", contents: {} },
    { name: "a longer block", text: "Instructions from: /p/AGENTS.md\nAMBIENT MORE", contents: { "/p/AGENTS.md": "AMBIENT" } },
  ])("refuses $name", async ({ text, contents }) => {
    const system = [`${HEAD}\n${text}`]
    await expect(withoutAmbient(system, files(contents))).rejects.toThrow(/egm-goldfish-isolation/)
  })
})

describe("isolation", () => {
  const AGENTS = "/p/AGENTS.md"
  const prompt = `${HEAD}\nInstructions from: ${AGENTS}\nAMBIENT\n`
  const setup = () => {
    const lines: string[] = []
    const hooks = isolation(REVIEWERS, files({ [AGENTS]: "AMBIENT\n" }), (line) => lines.push(line))
    return { hooks, lines }
  }

  test("isolates a reviewer session", async () => {
    const { hooks, lines } = setup()
    const transcript = [user("egm-structural"), entry(read(CONTENT + REMINDER, loaded))]
    hooks.messages(transcript)
    const system = [prompt]
    await hooks.system("child", system)
    expect(outputs(transcript)).toEqual([undefined, CONTENT])
    expect(system).toEqual([HEAD])
    expect(lines).toEqual(["[egm-goldfish-isolation] egm-structural: removed 1 instruction block(s)"])
  })

  test("logs nothing when a reviewer request has no instructions", async () => {
    const { hooks, lines } = setup()
    hooks.messages([user("egm-structural")])
    await hooks.system("child", [HEAD])
    expect(lines).toEqual([])
  })

  test.each([{ sessionID: "unseen" }, { sessionID: undefined }])(
    "refuses instructions for a request it cannot attribute %#",
    async ({ sessionID }) => {
      const { hooks } = setup()
      hooks.messages([user("egm", "parent")])
      await expect(hooks.system(sessionID, [prompt])).rejects.toThrow(/^egm-goldfish-isolation: .*agent/)
    },
  )

  test("passes an unattributed request without instructions, such as a title", async () => {
    const { hooks } = setup()
    const system = [HEAD]
    await hooks.system("unseen", system)
    expect(system).toEqual([HEAD])
  })

  test("leaves the orchestrator's session unchanged", async () => {
    const { hooks, lines } = setup()
    const transcript = [user("egm", "parent"), entry(read(CONTENT + REMINDER, loaded))]
    hooks.messages(transcript)
    const system = [prompt]
    await hooks.system("parent", system)
    expect(outputs(transcript)).toEqual([undefined, CONTENT + REMINDER])
    expect(system).toEqual([prompt])
    expect(lines).toEqual([])
  })
})
