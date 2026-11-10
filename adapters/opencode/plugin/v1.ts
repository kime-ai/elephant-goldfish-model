// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

import type { Plugin } from "@opencode-ai/plugin"
import { isolation, readAbsolute } from "./isolate_v1.ts"
import { parseReviewers } from "./options.ts"

// OpenCode 1.x adds AGENTS.md, CLAUDE.md, CONTEXT.md, and configured instruction files to every
// agent's system prompt, and the read tool appends nearby ones to its output. For the agents in
// `options.reviewers`, remove both from each request. The system hook does not name the agent, so
// the messages hook, which runs first in the same step, records each session's agent.
const server: Plugin = async (_input, options) => {
  const hooks = isolation(parseReviewers(options), readAbsolute, (line) => console.error(line))
  return {
    "experimental.chat.messages.transform": async (_hook, output) => hooks.messages(output.messages),
    "experimental.chat.system.transform": async (hook, output) => hooks.system(hook.sessionID, output.system),
  }
}

export default { id: "egm-guard", server }
