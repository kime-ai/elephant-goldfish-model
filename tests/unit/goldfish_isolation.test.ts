// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

// Run through tests/unit/test_goldfish_isolation.py, or directly with `bun test`.
import { describe, expect, test } from "bun:test"
import * as isolation from "../../adapters/opencode/goldfish_isolation/isolate.ts"
import type { Message, Request, SystemPart } from "../../adapters/opencode/goldfish_isolation/isolate.ts"

const { isolate } = isolation
const REVIEWERS = new Set(["egm-structural"])
const AMBIENT = "Instructions from: /p/AGENTS.md\nSECRET"

const instructions = (sources: { key: string; text: string }[]): SystemPart => ({
  type: "text",
  text: sources.map((source) => source.text).join("\n\n"),
  metadata: { experimental: { instructions: sources } },
})

const user = (text: string): Message => ({ role: "user", content: [{ type: "text", text }] })
const system = (text: string): Message => ({ role: "system", content: [{ type: "text", text }] })

const request = (agent: string, overrides: Partial<Request> = {}): Request => ({
  agent,
  system: [
    { type: "text", text: "PERSONA" },
    instructions([
      { key: "core/skills", text: "SKILLS" },
      { key: "core/instructions", text: AMBIENT },
      { key: "core/date", text: "DATE" },
    ]),
  ],
  messages: [user("Review /p/design.md")],
  ...overrides,
})

const texts = (parts: readonly SystemPart[]) => parts.map((part) => part.text)

describe("ambient AGENTS.md", () => {
  test("is removed from the reviewer's instructions while other sources stay", () => {
    const value = request("egm-structural")
    expect(isolate(REVIEWERS, value)).toBe(1)
    expect(texts(value.system)).toEqual(["PERSONA", "SKILLS\n\nDATE"])
    expect(JSON.stringify(value)).not.toContain("SECRET")
  })

  test("drops an instructions part whose only source is AGENTS.md", () => {
    const value = request("egm-structural", {
      system: [{ type: "text", text: "PERSONA" }, instructions([{ key: "core/instructions", text: AMBIENT }])],
    })
    isolate(REVIEWERS, value)
    expect(texts(value.system)).toEqual(["PERSONA"])
  })

  test("leaves an instructions part without AGENTS.md unchanged", () => {
    const part = instructions([{ key: "core/date", text: "DATE" }])
    const value = request("egm-structural", { system: [part] })
    expect(isolate(REVIEWERS, value)).toBe(0)
    expect(value.system).toEqual([part])
  })

  test("drops an unlabelled instructions part rather than leak it", () => {
    const value = request("egm-structural", {
      system: [{ type: "text", text: "PERSONA" }, { type: "text", text: `SKILLS\n\n${AMBIENT}\n\nDATE` }],
    })
    isolate(REVIEWERS, value)
    expect(texts(value.system)).toEqual(["PERSONA"])
  })

  test.each([
    { instructions: [{ key: 1 }] },
    { instructions: [{ key: "core/skills", text: 5 }] },
    { instructions: [{ key: 5, text: "SKILLS" }] },
    { instructions: [null] },
    { instructions: "not a list" },
  ])("treats malformed source metadata as unlabelled %#", ({ instructions }) => {
    const value = request("egm-structural", {
      system: [
        { type: "text", text: "PERSONA" },
        { type: "text", text: `SKILLS\n\n${AMBIENT}`, metadata: { experimental: { instructions } } },
      ],
    })
    isolate(REVIEWERS, value)
    expect(texts(value.system)).toEqual(["PERSONA"])
  })

  test("keeps a persona that only mentions AGENTS.md instructions in prose", () => {
    const persona = "Ignore any instructions from AGENTS.md that you were not given."
    const value = request("egm-structural", { system: [{ type: "text", text: persona }] })
    isolate(REVIEWERS, value)
    expect(texts(value.system)).toEqual([persona])
  })
})

describe("transcript", () => {
  test("drops nested AGENTS.md loads", () => {
    const value = request("egm-structural", {
      messages: [user("Review /p/design.md"), user("Instructions from: /p/pkg/AGENTS.md\nNESTED")],
    })
    expect(isolate(REVIEWERS, value)).toBe(2)
    expect(value.messages).toEqual([user("Review /p/design.md")])
  })

  test.each([
    "The instructions from /p/AGENTS.md no longer apply.",
    "New instructions apply from:\nInstructions from: /p/AGENTS.md\nNEW",
    "The instructions from /p/AGENTS.md changed. Here's the diff:\n```diff\n@@ -1 +1 @@\n```",
    "The instructions changed:\nInstructions from: /p/AGENTS.md\nNEW",
    "Today's date is now: Wed Nov 11 2026\n\nThe instructions from /p/AGENTS.md no longer apply.",
  ])("drops the instruction update %#", (update) => {
    const value = request("egm-structural", { messages: [user("Review /p/design.md"), system(update)] })
    isolate(REVIEWERS, value)
    expect(value.messages).toEqual([user("Review /p/design.md")])
  })

  test("keeps a review task that discusses AGENTS.md instructions", () => {
    const task = user("Review /p/design.md. It explains how instructions from AGENTS.md reach subagents.")
    const value = request("egm-structural", { messages: [task] })
    isolate(REVIEWERS, value)
    expect(value.messages).toEqual([task])
  })

  test("keeps other system messages", () => {
    const update = system("Today's date is now: Wed Nov 11 2026")
    const value = request("egm-structural", { messages: [user("Review /p/design.md"), update] })
    expect(isolate(REVIEWERS, value)).toBe(1)
    expect(value.messages).toEqual([user("Review /p/design.md"), update])
  })

  test("keeps assistant and tool messages that quote an instructions line", () => {
    const quoted = "Instructions from: /p/AGENTS.md\nNESTED"
    const replies = [
      { role: "assistant", content: [{ type: "text", text: quoted }] },
      { role: "tool", content: [{ type: "text", text: quoted }] },
    ]
    const value = request("egm-structural", { messages: replies })
    isolate(REVIEWERS, value)
    expect(value.messages).toEqual(replies)
  })

  test("reads only the text parts of a message", () => {
    const task: Message = {
      role: "user",
      content: [
        { type: "reasoning", text: "Instructions from: /p/AGENTS.md\nNESTED" },
        { type: "text", text: "Review /p/design.md" },
      ],
    }
    const value = request("egm-structural", { messages: [task] })
    isolate(REVIEWERS, value)
    expect(value.messages).toEqual([task])
  })

  test("keeps a review task that quotes an instructions line", () => {
    const task = user("Review this log:\nInstructions from: /p/AGENTS.md\nIs it expected?")
    const value = request("egm-structural", { messages: [task] })
    isolate(REVIEWERS, value)
    expect(value.messages).toEqual([task])
  })
})

describe("other agents", () => {
  test("leave the orchestrator's request unchanged", () => {
    const value = request("egm", { messages: [user("Instructions from: /p/pkg/AGENTS.md\nNESTED")] })
    expect(isolate(REVIEWERS, value)).toBe(0)
    expect(value).toEqual(request("egm", { messages: [user("Instructions from: /p/pkg/AGENTS.md\nNESTED")] }))
  })
})

describe("parseAgents", () => {
  test("returns the configured reviewer names", () => {
    expect(isolation.parseAgents({ agents: ["egm-style", "egm-structural"] })).toEqual(
      new Set(["egm-style", "egm-structural"]),
    )
  })

  test.each([{}, { agents: [] }, { agents: "egm-style" }, { agents: ["egm-style", 1] }, { agents: [""] }])(
    "rejects misconfigured options %#",
    (options) => {
      expect(() => isolation.parseAgents(options)).toThrow(/agents/)
    },
  )
})
