// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

/** Reads the configured agent names; throws so a misconfigured install never runs unisolated. */
export const parseAgents = (options: Record<string, unknown> | undefined): ReadonlySet<string> => {
  const agents = options?.agents
  if (!Array.isArray(agents) || agents.length === 0 || !agents.every((id) => typeof id === "string" && id)) {
    throw new Error("egm-goldfish-isolation: options.agents must be a non-empty array of agent names")
  }
  return new Set(agents)
}
