// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

// OpenCode 2.x puts every instruction source into each agent's request: global and project
// AGENTS.md, configured instruction files, Code Mode, MCP, skill and reference guidance, and
// plugin entries. Nested AGENTS.md files and instruction updates arrive as injected messages.
// A Goldfish reviewer keeps an allowlist of the system prompt and the transcript, so a kind
// of instruction that OpenCode adds later cannot reach it.

// The sources a reviewer keeps; the agent's own prompt and the date and environment.
const KEEP = new Set(["core/date", "core/environment"])
// The only tools a reviewer may be offered. OpenCode offers `skill` even when it is denied.
const TOOLS = new Set(["read", "glob"])

// The subset of @opencode/plugin's request types this module reads, so it runs without the host.
type Rendered = { readonly key: string; readonly text: string }
type Labelled = { readonly experimental: object; readonly instructions: readonly Rendered[] }
export type SystemPart = { readonly type: "text"; readonly text: string; readonly metadata?: Record<string, unknown> }
export type Message = {
  readonly id?: string
  readonly role: string
  readonly content: readonly { readonly type: string; readonly text?: string | null }[]
}
export type Request<M extends Message = Message> = {
  readonly agent: string
  system: SystemPart[]
  messages: M[]
  tools: Record<string, unknown>
}
export type Context = {
  // The agent's own system prompt, when OpenCode knows one.
  readonly own: string | undefined
  // IDs of the session messages that OpenCode injected, such as nested instructions.
  readonly synthetic: ReadonlySet<string>
}

const isRendered = (value: unknown): value is Rendered =>
  typeof value === "object" &&
  value !== null &&
  typeof (value as Rendered).key === "string" &&
  typeof (value as Rendered).text === "string"

/** The part's instruction sources, or undefined when the part carries no valid source list. */
const labelled = (part: SystemPart): Labelled | undefined => {
  const experimental = part.metadata?.experimental
  if (typeof experimental !== "object" || experimental === null) return undefined
  const instructions = (experimental as { instructions?: unknown }).instructions
  return Array.isArray(instructions) && instructions.every(isRendered) ? { experimental, instructions } : undefined
}

const withSources = (part: SystemPart, label: Labelled, instructions: readonly Rendered[]): SystemPart => ({
  ...part,
  text: instructions.map((source) => source.text).join("\n\n"),
  metadata: { ...part.metadata, experimental: { ...label.experimental, instructions } },
})

/** The system parts a reviewer keeps, and how many sources and parts were dropped. */
const systemParts = (parts: SystemPart[], own: string | undefined): [SystemPart[], number] => {
  let removed = 0
  const kept = parts.flatMap((part) => {
    const label = labelled(part)
    if (label === undefined) {
      if (part.text === own) return [part]
      removed++
      return []
    }
    const instructions = label.instructions.filter((source) => KEEP.has(source.key))
    removed += label.instructions.length - instructions.length
    return instructions.length > 0 ? [withSources(part, label, instructions)] : []
  })
  return [kept, removed]
}

// A system message announces an instruction change; one without text, such as a
// reasoning-effort marker, is not an instruction.
const injected = (message: Message, synthetic: ReadonlySet<string>) =>
  (message.id !== undefined && synthetic.has(message.id)) ||
  (message.role === "system" && message.content.some((part) => part.type === "text"))

/**
 * Reduces one reviewer's request to its own prompt, the date and environment, its own transcript,
 * and read and glob. Returns how many sources, parts, and messages it removed. In strict mode it
 * throws when the agent's own prompt is not in the request, since OpenCode then sends something
 * this module does not recognize.
 */
export const isolate = <M extends Message>(request: Request<M>, context: Context, strict: boolean) => {
  const [system, droppedParts] = systemParts(request.system, context.own)
  if (strict && !system.some((part) => part.text === context.own)) {
    throw new Error(`egm-guard: ${request.agent} system prompt not found; refusing the request`)
  }
  request.system = system
  const messages = request.messages.filter((message) => !injected(message, context.synthetic))
  const droppedMessages = request.messages.length - messages.length
  request.messages = messages
  for (const tool of Object.keys(request.tools)) if (!TOOLS.has(tool)) delete request.tools[tool]
  return droppedParts + droppedMessages
}

export type Deps = {
  readonly ownSystem: (agent: string) => Promise<string | undefined>
  readonly syntheticIds: (sessionID: string) => Promise<ReadonlySet<string>>
  readonly log: (line: string) => void
}

/** The hook handler: isolates each request that one of `reviewers` makes. */
export const guard = (reviewers: ReadonlySet<string>, deps: Deps) => {
  return async <M extends Message>(request: Request<M> & { readonly sessionID: string }, strict: boolean) => {
    if (!reviewers.has(request.agent)) return
    const [own, synthetic] = await Promise.all([deps.ownSystem(request.agent), deps.syntheticIds(request.sessionID)])
    const removed = isolate(request, { own, synthetic }, strict)
    if (removed > 0) deps.log(`[egm-guard] ${request.agent}: removed ${removed} injected item(s)`)
  }
}
