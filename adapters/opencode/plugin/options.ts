// Copyright 2026 Google LLC.
// SPDX-License-Identifier: Apache-2.0

/**
 * Reads the reviewer agent IDs from the installer's options: `reviewers` maps each ID to its
 * persona path. Throws, so a misconfigured install never runs unisolated.
 */
export const parseReviewers = (options: Record<string, unknown> | undefined): ReadonlySet<string> => {
  const reviewers = options?.reviewers
  const valid =
    typeof reviewers === "object" &&
    reviewers !== null &&
    !Array.isArray(reviewers) &&
    Object.keys(reviewers).length > 0 &&
    Object.entries(reviewers).every(([id, persona]) => id !== "" && typeof persona === "string" && persona !== "")
  if (!valid) throw new Error("egm-guard: options.reviewers must map reviewer agent IDs to persona paths")
  return new Set(Object.keys(reviewers))
}
