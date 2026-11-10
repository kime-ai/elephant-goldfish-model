// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

import { Plugin } from "@opencode/plugin"
import { guard } from "./isolate.ts"
import { parseReviewers } from "./options.ts"

// OpenCode V2 adds AGENTS.md and every other instruction source to each agent's request, including
// subagents, and offers every agent the skill tool. For the reviewers in `options.reviewers`, this
// keeps only the agent's own prompt, the date and environment, the reviewer's own transcript, and
// the read and glob tools. Only the outgoing request changes.
export default Plugin.define({
  id: "egm-guard",
  async setup(ctx) {
    const reviewers = parseReviewers(ctx.options)
    const systems = new Map<string, string | undefined>()
    const handle = guard(reviewers, {
      ownSystem: async (agent) => {
        if (!systems.has(agent)) systems.set(agent, (await ctx.agent.get({ agentID: agent })).data.system)
        return systems.get(agent)
      },
      syntheticIds: async (sessionID) => {
        const history = await ctx.session.context({ sessionID })
        return new Set(history.filter((message) => message.type === "synthetic").map((message) => message.id))
      },
      log: (line) => console.error(line),
    })
    await ctx.session.hook("context", (event) => handle(event, true))
    await ctx.session.hook("compaction", (event) => handle(event, false))
    await ctx.session.hook("generate", (event) => handle(event, false))
  },
})
