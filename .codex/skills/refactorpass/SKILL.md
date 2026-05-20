---
name: refactorpass
description: Pre-push cleanup pass for Codex. Use when the user asks for refactoring, cleanup, simplification, or the platform review chain before pushing source-code changes. Skips docs/config-only changesets, runs a structured cleanup matrix, and commits the result when appropriate.
---

# Refactor Pass

Run a structured, behavior-preserving cleanup pass on the current branch before review. This is not a broad refactor. The goal is to make the fresh diff simpler, easier to review, and less brittle without changing feature behavior.

## Cleanup Matrix

Refactorpass must cover three lanes:

1. **Simplicity/DRY lane** — remove fresh duplication, collapse awkward control flow, inline one-use abstractions, delete dead code, and simplify names when the diff makes intent clearer.
2. **Correctness-preserving lane** — look for cleanup that reduces bug risk without changing behavior: narrower conditions, safer defaults, clearer error paths, less state mutation, and tighter async/resource cleanup.
3. **Convention/API lane** — align fresh code with local patterns, package boundaries, exports, dependency placement, and documented repo conventions.

Run these lanes as independently as the active runtime permits:

- If subagents/delegation are available and permitted by the active Codex instructions, spawn independent cleanup reviewers for the three lanes. Tell each reviewer to inspect only the local diff, suggest behavior-preserving cleanup, and avoid broad rewrites.
- If subagents are unavailable or not permitted, perform three separate local passes using the lane prompts above. Do not present that as equivalent to independent subagents.
- If refactorpass could not use independent subagents, explicitly say so in the output under `cleanup depth`.

## Process

1. Verify the branch is not `main`, `master`, or `staging`.
2. Determine the diff scope against `@{u}` when available, otherwise against the default branch.
3. Skip if the changeset is docs/config-only. Treat source files such as `.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.rs`, `.go`, `.java`, `.cpp`, `.c`, `.h`, `.cs`, `.rb`, `.swift`, `.kt`, `.sh`, and `.bash` as review-worthy.
4. Read the changed source files and execute every lane in the Cleanup Matrix.
5. Consolidate lane suggestions, deduplicate by root cause, and apply only cleanup that is behavior-preserving and clearly improves the fresh diff.
6. Keep scope tight: touch only code changed by the current branch unless a tiny adjacent edit is required to finish the cleanup safely.
7. Do not introduce feature behavior, broad rewrites, unrelated style churn, formatting-only commits, or speculative abstraction.
8. Run the smallest relevant formatter/test command if the repo documents one.
9. If changes were made, commit them as `refactor: codex cleanup pass - <summary>`.

## Output

Report:

- cleanup depth: independent subagents, local three-pass fallback, docs/config-only skip, or no source changes
- whether changes were made
- commit SHA if created
- validation run
- recommended next step: `grill` before push, then `reviewit <pr-number>` after the PR opens
