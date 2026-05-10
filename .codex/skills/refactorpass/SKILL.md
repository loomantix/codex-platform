---
name: refactorpass
description: Pre-push cleanup pass for Codex. Use when the user asks for refactoring, cleanup, simplification, or the platform review chain before pushing source-code changes. Skips docs/config-only changesets, applies a single scoped simplification pass, and commits the result when appropriate.
---

# Refactor Pass

Run one focused cleanup pass on the current branch before review.

## Process

1. Verify the branch is not `main`, `master`, or `staging`.
2. Determine the diff scope against `@{u}` when available, otherwise against the default branch.
3. Skip if the changeset is docs/config-only. Treat source files such as `.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.rs`, `.go`, `.java`, `.cpp`, `.c`, `.h`, `.cs`, `.rb`, `.swift`, `.kt`, `.sh`, and `.bash` as review-worthy.
4. Read the changed source files and simplify only fresh code touched by the diff.
5. Keep scope tight: remove duplication, collapse awkward control flow, delete dead code, improve names when the diff makes intent clearer.
6. Do not introduce feature behavior, broad rewrites, or unrelated style churn.
7. Run the smallest relevant formatter/test command if the repo documents one.
8. If changes were made, commit them as `refactor: codex cleanup pass - <summary>`.

## Output

Report whether changes were made, the commit SHA if created, and the recommended next step: `grill` before push, then `reviewit <pr-number>` after the PR opens.
