// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

import { Plugin } from "@opencode/plugin"
import { isolate, parseAgents, type Message, type Request } from "./isolate.ts"

// OpenCode V2 adds AGENTS.md to every agent's context, including subagents.
// For the agents named in `options.agents`, remove ambient AGENTS.md from the
// instructions system part and drop nested AGENTS.md loads and mid-session
// instruction updates from the transcript. Only the outgoing request changes.
export default Plugin.define({
  id: "egm-goldfish-isolation",
  async setup(ctx) {
    const agents = parseAgents(ctx.options)
    const hook = <M extends Message>(request: Request<M>) => {
      const removed = isolate(agents, request)
      if (removed > 0) console.error(`[egm-goldfish-isolation] ${request.agent}: removed ${removed} AGENTS.md block(s)`)
    }
    await ctx.session.hook("context", hook)
    await ctx.session.hook("compaction", hook)
  },
})
