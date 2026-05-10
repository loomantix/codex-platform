# Review Workflow

This file is synced from `codex-platform` into consumer repos. Consumer-specific edits will be overwritten on the next sync.

## Lean Path

Use this for most source-code PRs:

1. Make the local change.
2. Run the `refactorpass` skill if source files changed.
3. Run the `grill` skill before pushing.
4. Push and open the PR.
5. Run `reviewit <pr-number>` to trigger Gemini Flash + Copilot, dedupe findings, apply fixes, push, and reply.

## Deep Path

Use this for high-risk or complex changes:

1. Run `deepgrill` before pushing.
2. Push and open the PR.
3. Run `reviewit <pr-number> deep`.

Choose deep when the change touches auth, crypto, secret handling, schema/data shape, GitHub Actions, sync tooling, `.codex/skills/**`, or a large refactor.

## Skip Path

For docs/config-only changes, skip expensive review automation unless the user explicitly wants it. Source-code changes include common implementation extensions such as `.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.rs`, `.go`, `.java`, `.cpp`, `.c`, `.h`, `.cs`, `.rb`, `.swift`, `.kt`, `.sh`, and `.bash`.

## Review Principles

- Keep Gemini and Copilot manual-only; `reviewit` is the orchestrator.
- Reply to every actionable AI review comment after fixes are pushed.
- Do not treat generated AI comments as automatically correct; verify each finding against the code.
- Stop at the iteration cap and hand back a clear summary if findings keep recurring.
