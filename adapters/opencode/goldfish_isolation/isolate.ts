// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

const DISCOVERY_KEY = "core/instructions"
// OpenCode renders each instruction file as "Instructions from: <path>" and announces
// changes as "The instructions from <path> ...". Match those lines only, never prose.
const INSTRUCTION_LINE = /^(?:Instructions from: |The instructions from )[^\n]*AGENTS\.md/im
// A nested load is a user message that starts with the rendered file.
const NESTED_LOAD = /^Instructions from: [^\n]*AGENTS\.md(?:\n|$)/i

// The subset of @opencode/plugin's SessionContext this module reads, so it runs without the host.
type Rendered = { readonly key: string; readonly text: string }
export type SystemPart = { readonly type: "text"; readonly text: string; readonly metadata?: Record<string, unknown> }
export type Message = {
  readonly role: string
  readonly content: readonly { readonly type: string; readonly text?: string | null }[]
}
export type Request<M extends Message = Message> = { readonly agent: string; system: SystemPart[]; messages: M[] }

const isRendered = (value: unknown): value is Rendered =>
  typeof value === "object" &&
  value !== null &&
  typeof (value as Rendered).key === "string" &&
  typeof (value as Rendered).text === "string"

type Labelled = { readonly experimental: object; readonly instructions: readonly Rendered[] }

/** The part's instruction sources, or undefined when the part carries no valid source list. */
const labelled = (part: SystemPart): Labelled | undefined => {
  const experimental = part.metadata?.experimental
  if (typeof experimental !== "object" || experimental === null) return undefined
  const instructions = (experimental as { instructions?: unknown }).instructions
  return Array.isArray(instructions) && instructions.every(isRendered) ? { experimental, instructions } : undefined
}

const text = (content: Message["content"]) =>
  content
    .flatMap((part) => (part.type === "text" && typeof part.text === "string" ? [part.text] : []))
    .join("\n")

const withoutDiscovery = (part: SystemPart, label: Labelled): SystemPart[] => {
  const instructions = label.instructions.filter((source) => source.key !== DISCOVERY_KEY)
  if (instructions.length === 0) return []
  const experimental = { ...label.experimental, instructions }
  return [
    {
      ...part,
      text: instructions.map((source) => source.text).join("\n\n"),
      metadata: { ...part.metadata, experimental },
    },
  ]
}

const isInstructionMessage = (message: Message) =>
  message.role === "user"
    ? NESTED_LOAD.test(text(message.content))
    : message.role === "system" && INSTRUCTION_LINE.test(text(message.content))

/** Removes AGENTS.md instructions from a request made by one of `agents`; returns the count removed. */
export const isolate = <M extends Message>(agents: ReadonlySet<string>, request: Request<M>) => {
  if (!agents.has(request.agent)) return 0
  let removed = 0

  request.system = request.system.flatMap((part) => {
    const label = labelled(part)
    const leaks = label
      ? label.instructions.some((source) => source.key === DISCOVERY_KEY)
      : INSTRUCTION_LINE.test(part.text)
    if (!leaks) return [part]
    removed++
    // Without a valid source list the part cannot be split, so drop it rather than leak.
    return label ? withoutDiscovery(part, label) : []
  })

  request.messages = request.messages.filter((message) => {
    if (!isInstructionMessage(message)) return true
    removed++
    return false
  })

  return removed
}
