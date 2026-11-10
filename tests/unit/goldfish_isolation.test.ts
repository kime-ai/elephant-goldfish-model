// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

// Run through tests/unit/test_goldfish_isolation.py, or directly with `bun test`.
import { describe, expect, test } from "bun:test"
import { guard, isolate } from "../../adapters/opencode/plugin/isolate.ts"
import type { Context, Message, Request, SystemPart } from "../../adapters/opencode/plugin/isolate.ts"
import { parseReviewers } from "../../adapters/opencode/plugin/options.ts"

const PERSONA = "PERSONA: read /b/agents/style.md"
const SECRET = "Instructions from: /p/AGENTS.md\nSECRET"

const instructions = (sources: { key: string; text: string }[]): SystemPart => ({
  type: "text",
  text: sources.map((source) => source.text).join("\n\n"),
  metadata: { experimental: { instructions: sources } },
})

const user = (text: string): Message => ({ id: "msg-user", role: "user", content: [{ type: "text", text }] })
const synthetic = (id: string, text: string): Message => ({ id, role: "user", content: [{ type: "text", text }] })
const system = (text: string): Message => ({ role: "system", content: [{ type: "text", text }] })

const TOOLS = { read: {}, glob: {}, grep: {}, skill: {}, shell: {}, edit: {}, execute: {}, subagent: {} }

const request = (overrides: Partial<Request> = {}): Request => ({
  agent: "egm-style",
  system: [
    { type: "text", text: PERSONA },
    instructions([
      { key: "core/mcp", text: "MCP GUIDANCE" },
      { key: "core/skills", text: "SKILLS" },
      { key: "core/instructions", text: SECRET },
      { key: "core/date", text: "DATE" },
      { key: "core/environment", text: "ENV" },
      { key: "core/entries", text: "ENTRIES" },
    ]),
  ],
  messages: [user("Review /p/design.md")],
  tools: { ...TOOLS },
  ...overrides,
})

const CONTEXT: Context = { own: PERSONA, synthetic: new Set() }
const texts = (parts: readonly SystemPart[]) => parts.map((part) => part.text)

describe("system prompt", () => {
  test("keeps only the date and environment from the instruction sources", () => {
    const value = request()
    expect(isolate(value, CONTEXT, true)).toBe(4)
    expect(texts(value.system)).toEqual([PERSONA, "DATE\n\nENV"])
    expect(JSON.stringify(value)).not.toMatch(/SECRET|MCP GUIDANCE|SKILLS|ENTRIES/)
  })

  test("keeps the part's metadata in step with its text", () => {
    const value = request()
    isolate(value, CONTEXT, true)
    const kept = value.system[1].metadata?.experimental as { instructions: { key: string }[] }
    expect(kept.instructions.map((source) => source.key)).toEqual(["core/date", "core/environment"])
  })

  test("drops an instructions part that has no date or environment", () => {
    const value = request({ system: [{ type: "text", text: PERSONA }, instructions([{ key: "core/instructions", text: SECRET }])] })
    expect(isolate(value, CONTEXT, true)).toBe(1)
    expect(texts(value.system)).toEqual([PERSONA])
  })

  test("drops sources it does not know, so new kinds of instructions cannot leak", () => {
    const value = request({ system: [{ type: "text", text: PERSONA }, instructions([{ key: "acme/policy", text: "POLICY" }, { key: "core/date", text: "DATE" }])] })
    isolate(value, CONTEXT, true)
    expect(texts(value.system)).toEqual([PERSONA, "DATE"])
  })

  test("drops a part that is neither the agent's own prompt nor a labelled source", () => {
    const value = request({ system: [{ type: "text", text: PERSONA }, { type: "text", text: "Some other plugin's note." }] })
    expect(isolate(value, CONTEXT, true)).toBe(1)
    expect(texts(value.system)).toEqual([PERSONA])
  })

  test.each([
    { instructions: [{ key: 1 }] },
    { instructions: [{ key: "core/date", text: 5 }] },
    { instructions: [null] },
    { instructions: "not a list" },
  ])("treats malformed source metadata as an unlabelled part %#", ({ instructions }) => {
    const value = request({ system: [{ type: "text", text: PERSONA }, { type: "text", text: `DATE\n${SECRET}`, metadata: { experimental: { instructions } } }] })
    isolate(value, CONTEXT, true)
    expect(texts(value.system)).toEqual([PERSONA])
  })

  test("does not mistake an experimental field without sources for a labelled part", () => {
    const value = request({ system: [{ type: "text", text: PERSONA }, { type: "text", text: SECRET, metadata: { experimental: "x" } }] })
    isolate(value, CONTEXT, true)
    expect(texts(value.system)).toEqual([PERSONA])
  })
})

describe("the agent's own prompt", () => {
  test.each([{ own: undefined }, { own: "A DIFFERENT PROMPT" }])("fails closed when it is not found %#", ({ own }) => {
    expect(() => isolate(request(), { own, synthetic: new Set() }, true)).toThrow(
      /^egm-guard: egm-style system prompt not found; refusing the request$/,
    )
  })

  test("is not required when compacting or generating", () => {
    const value = request()
    expect(() => isolate(value, { own: undefined, synthetic: new Set() }, false)).not.toThrow()
    expect(texts(value.system)).toEqual(["DATE\n\nENV"])
  })
})

describe("transcript", () => {
  test("drops the synthetic messages that carry nested instructions and notices", () => {
    const value = request({ messages: [user("Review /p/design.md"), synthetic("syn-1", "Instructions from: /p/pkg/AGENTS.md\nNESTED"), synthetic("syn-2", "Deployment completed")] })
    expect(isolate(value, { own: PERSONA, synthetic: new Set(["syn-1", "syn-2"]) }, true)).toBe(6)
    expect(value.messages).toEqual([user("Review /p/design.md")])
  })

  test("keeps a user message that merely looks like an instruction", () => {
    const task = user("Review this log:\nInstructions from: /p/AGENTS.md\nIs it expected?")
    const value = request({ messages: [task] })
    isolate(value, CONTEXT, true)
    expect(value.messages).toEqual([task])
  })

  test("drops system messages, which announce instruction changes", () => {
    const value = request({ messages: [user("Review /p/design.md"), system("The instructions from /p/AGENTS.md changed. Here's the diff:"), system("Today's date is now: Wed Nov 11 2026")] })
    expect(isolate(value, CONTEXT, true)).toBe(6)
    expect(value.messages).toEqual([user("Review /p/design.md")])
  })

  test("keeps a system message that carries no text, such as a reasoning-effort marker", () => {
    const effort: Message = { role: "system", content: [{ type: "effort" }] }
    const value = request({ messages: [user("Review"), effort] })
    isolate(value, CONTEXT, true)
    expect(value.messages).toEqual([user("Review"), effort])
  })

  test("keeps the reviewer's own assistant and tool messages", () => {
    const own: Message[] = [
      { id: "a-1", role: "assistant", content: [{ type: "text", text: "Instructions from: /p/AGENTS.md\nQUOTED" }] },
      { id: "t-1", role: "tool", content: [{ type: "text", text: "result" }] },
    ]
    const value = request({ messages: [user("Review"), ...own] })
    isolate(value, CONTEXT, true)
    expect(value.messages).toEqual([user("Review"), ...own])
  })

  test("keeps a message without an ID, since it cannot be a recorded synthetic message", () => {
    const anonymous: Message = { role: "user", content: [{ type: "text", text: "Hello" }] }
    const value = request({ messages: [anonymous] })
    isolate(value, { own: PERSONA, synthetic: new Set(["undefined"]) }, true)
    expect(value.messages).toEqual([anonymous])
  })
})

describe("tools", () => {
  test("leaves reviewers only read and glob", () => {
    const value = request()
    isolate(value, CONTEXT, true)
    expect(Object.keys(value.tools).sort()).toEqual(["glob", "read"])
  })

  test("does not count removed tools as removed instructions", () => {
    const value = request({ system: [{ type: "text", text: PERSONA }] })
    expect(isolate(value, CONTEXT, true)).toBe(0)
  })
})

describe("guard", () => {
  const setup = () => {
    const calls: string[] = []
    const lines: string[] = []
    const handle = guard(new Set(["egm-style"]), {
      ownSystem: async (agent) => {
        calls.push(`own:${agent}`)
        return PERSONA
      },
      syntheticIds: async (sessionID) => {
        calls.push(`history:${sessionID}`)
        return new Set(["syn-1"])
      },
      log: (line) => lines.push(line),
    })
    return { calls, lines, handle }
  }

  test("isolates a reviewer's request and logs what it removed", async () => {
    const { handle, lines } = setup()
    const value = { ...request({ messages: [user("Review"), synthetic("syn-1", "NESTED")] }), sessionID: "child" }
    await handle(value, true)
    expect(texts(value.system)).toEqual([PERSONA, "DATE\n\nENV"])
    expect(value.messages).toEqual([user("Review")])
    expect(Object.keys(value.tools).sort()).toEqual(["glob", "read"])
    expect(lines).toEqual(["[egm-guard] egm-style: removed 5 injected item(s)"])
  })

  test("leaves every other agent's request alone and asks for nothing", async () => {
    const { handle, calls, lines } = setup()
    const value = { ...request({ agent: "egm" }), sessionID: "parent" }
    await handle(value, true)
    expect(value).toEqual({ ...request({ agent: "egm" }), sessionID: "parent" })
    expect(calls).toEqual([])
    expect(lines).toEqual([])
  })

  test("logs a single removal", async () => {
    const { handle, lines } = setup()
    const value = { ...request({ system: [{ type: "text", text: PERSONA }, { type: "text", text: "Another plugin's note." }] }), sessionID: "child" }
    await handle(value, true)
    expect(lines).toEqual(["[egm-guard] egm-style: removed 1 injected item(s)"])
  })

  test("logs nothing when a reviewer's request had nothing to remove", async () => {
    const { handle, lines } = setup()
    const value = { ...request({ system: [{ type: "text", text: PERSONA }] }), sessionID: "child" }
    await handle(value, true)
    expect(lines).toEqual([])
  })

  test("refuses a reviewer's request when its own prompt is missing", async () => {
    const { handle } = setup()
    const value = { ...request({ system: [instructions([{ key: "core/date", text: "DATE" }])] }), sessionID: "child" }
    await expect(handle(value, true)).rejects.toThrow(/system prompt not found/)
  })
})

describe("parseReviewers", () => {
  const personas = { "egm-style": "/b/agents/style.md", "egm-structural": "/b/agents/structural.md" }

  test("returns the reviewer agent IDs from the installer's options", () => {
    const options = { primary: "egm", bundle: "/b", reviewers: personas }
    expect(parseReviewers(options)).toEqual(new Set(["egm-style", "egm-structural"]))
  })

  test("accepts a single reviewer", () => {
    expect(parseReviewers({ reviewers: { "egm-style": "/b/agents/style.md" } })).toEqual(new Set(["egm-style"]))
  })

  test.each([
    undefined,
    {},
    { reviewers: {} },
    { reviewers: ["egm-style"] },
    { reviewers: "egm-style" },
    { reviewers: { "egm-style": 1 } },
    { reviewers: { "egm-style": "" } },
    { reviewers: { "": "/b/agents/style.md" } },
    { agents: ["egm-style"] },
  ])("rejects misconfigured options %#", (options) => {
    expect(() => parseReviewers(options)).toThrow(/^egm-guard: options\.reviewers/)
  })
})
