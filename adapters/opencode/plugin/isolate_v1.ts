// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

// OpenCode 1.x renders each instruction file as "Instructions from: <path>\n<content>". The
// system prompt joins those blocks with "\n"; the read tool appends nearby ones to its output
// as "\n\n<system-reminder>\n<blocks>\n</system-reminder>" and lists their paths in
// metadata.loaded.
const HEADER = /^Instructions from: (.+)$/m
const REMINDER_END = "\n</system-reminder>"

import { readFile } from "node:fs/promises"
import { isAbsolute } from "node:path"

// The subset of @opencode-ai/plugin's message types this module reads, so it runs without the host.
type Completed = {
  readonly status: "completed"
  readonly output: string
  readonly metadata: Record<string, unknown>
  readonly time: { readonly start: number; readonly compacted?: number }
}
export type ToolState = Completed | { readonly status: "pending" | "running" | "error" }
export type Part = { readonly type: string; readonly tool?: string; readonly state?: ToolState }
export type Entry<P extends Part = Part> = {
  readonly info: { readonly role: string; readonly sessionID: string; readonly agent?: string }
  parts: P[]
}
export type Read = (path: string) => Promise<string | undefined>

/** An instruction file's text, or undefined when the path is relative or the file is unreadable. */
export const readAbsolute: Read = async (path) =>
  isAbsolute(path) ? readFile(path, "utf8").catch(() => undefined) : undefined
export type Log = (line: string) => void

const refuse = (reason: string): never => {
  throw new Error(`egm-guard: ${reason}; refusing the request`)
}
const unverifiable = (path: string) => refuse(`cannot remove the instructions from ${path}`)

/** The session and agent of the transcript's latest user message. */
export const requester = (entries: readonly Entry[]) => {
  const latest = entries.findLast((item) => item.info.role === "user")
  if (latest?.info.agent === undefined) return undefined
  return { sessionID: latest.info.sessionID, agent: latest.info.agent }
}

const loadedPaths = (state: Completed): readonly string[] => {
  const loaded = state.metadata.loaded
  return Array.isArray(loaded) ? loaded.filter((path): path is string => typeof path === "string") : []
}

/** The read output without the reminder it appended, or undefined when nothing was appended. */
const stripReminder = (output: string, paths: readonly string[]): string | undefined => {
  const start = output.lastIndexOf(`\n\n<system-reminder>\nInstructions from: ${paths[0]}\n`)
  if (start !== -1 && output.endsWith(REMINDER_END)) return output.slice(0, start)
  // Image and PDF reads list loaded files without appending them.
  const leaked = paths.find((path) => output.includes(`Instructions from: ${path}`))
  return leaked === undefined ? undefined : unverifiable(leaked)
}

/** The state of a finished read whose output still reaches the model. */
const visibleRead = (part: Part): Completed | undefined => {
  const state = part.state
  const finished = part.type === "tool" && part.tool === "read" && state?.status === "completed"
  return finished && !state.time.compacted ? state : undefined
}

const withoutReminder = <P extends Part>(part: P): P | undefined => {
  const state = visibleRead(part)
  if (state === undefined) return
  const output = stripReminder(state.output, loadedPaths(state))
  return output === undefined ? undefined : { ...part, state: { ...state, output } }
}

/** Replaces read results that carry nested instruction files; returns how many changed. */
export const withoutNested = <P extends Part>(entries: Entry<P>[]) => {
  let removed = 0
  for (const item of entries) {
    item.parts = item.parts.map((part) => {
      const stripped = withoutReminder(part)
      if (stripped === undefined) return part
      removed++
      return stripped
    })
  }
  return removed
}

/** One system entry without its instruction blocks, each verified against the file it names. */
const withoutBlocks = async (text: string, read: Read): Promise<[string, number]> => {
  let removed = 0
  for (let match = HEADER.exec(text); match; match = HEADER.exec(text)) {
    const path = match[1]
    const content = await read(path)
    const block = `Instructions from: ${path}\n${content}`
    const end = match.index + block.length
    if (content === undefined || !text.startsWith(block, match.index) || (end < text.length && text[end] !== "\n")) {
      unverifiable(path)
    }
    // A header after the first line follows a line break; remove that too.
    const start = Math.max(match.index - 1, 0)
    text = text.slice(0, start) + text.slice(end)
    removed++
  }
  return [text, removed]
}

/** Removes instruction blocks from every system entry; throws rather than send one it cannot verify. */
export const withoutAmbient = async (system: string[], read: Read) => {
  let removed = 0
  for (const [index, text] of system.entries()) {
    const [cleaned, count] = await withoutBlocks(text, read)
    system[index] = cleaned
    removed += count
  }
  return removed
}

/** The two hook handlers, sharing each session's agent. */
export const isolation = (agents: ReadonlySet<string>, read: Read, log: Log) => {
  // One entry per session the messages hook has seen, for the life of the server process.
  const sessions = new Map<string, string>()
  return {
    messages: <P extends Part>(entries: Entry<P>[]) => {
      const sender = requester(entries)
      if (sender === undefined) return
      sessions.set(sender.sessionID, sender.agent)
      if (agents.has(sender.agent)) withoutNested(entries)
    },
    system: async (sessionID: string | undefined, system: string[]) => {
      const agent = sessionID === undefined ? undefined : sessions.get(sessionID)
      if (agent === undefined) {
        // OpenCode 1.18.29 adds instructions only after the messages hook has run for the session.
        if (system.some((text) => HEADER.test(text))) refuse("cannot tell which agent sent instructions")
        return
      }
      if (!agents.has(agent)) return
      const removed = await withoutAmbient(system, read)
      if (removed > 0) log(`[egm-guard] ${agent}: removed ${removed} instruction block(s)`)
    },
  }
}
