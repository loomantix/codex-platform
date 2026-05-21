# Review Workflow

This file is synced from `codex-platform` into consumer repos. Consumer-specific edits will be overwritten on the next sync.

## Lean Path

Use this for most source-code PRs:

1. Make the local change.
2. Run the `refactorpass` skill if source files changed. It must execute the cleanup matrix: simplicity/DRY, correctness-preserving cleanup, and convention/API alignment. Use independent subagents when the active runtime permits them; otherwise run three separate local passes and disclose that downgrade.
3. Run the `grill` skill before pushing. Lean `grill` must execute the two-lane review: code reviewer plus silent failure hunter. Use independent subagents when the active runtime permits them; otherwise run two separate local passes and disclose that downgrade.
4. Push and open the PR.
5. Run `reviewit <pr-number>` to trigger Gemini Flash + Copilot, fix Gemini findings first, then fold in Copilot findings when they finish, push, and reply.

## Deep Path

Use this for high-risk or complex changes:

1. Run `deepgrill` before pushing. This must execute `refactorpass` plus `grill deep`'s six review lanes: code reviewer, silent failure hunter, type/API design analyzer, comment/docs analyzer, PR test analyzer, and security reviewer. Use independent subagents when the active runtime permits them; otherwise run six separate local passes and disclose that downgrade.
2. Push and open the PR.
3. Run `reviewit <pr-number> deep`. Deep mode fires the same two bot reviewers as lean (Gemini Flash + Copilot) but with a 4-iteration cap, an early-exit when an iteration produces no `fix` resolutions (defer/dismiss-only doesn't justify another round), and a final `deepgrill` invocation after the loop exits so fresh subagents review the PR's current state in a separate session. The old in-loop `codex review` is gone — running it inside the polling loop routinely dropped the orchestrator out early.

Choose deep when the change touches auth, crypto, secret handling, schema/data shape, GitHub Actions, sync tooling, `.codex/skills/**`, or a large refactor.

## Skip Path

For docs/config-only changes, skip expensive review automation unless the user explicitly wants it. Source-code changes include common implementation extensions such as `.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.rs`, `.go`, `.java`, `.cpp`, `.c`, `.h`, `.cs`, `.rb`, `.swift`, `.kt`, `.sh`, and `.bash`.

## Review Principles

- Keep Gemini and Copilot manual-only; `reviewit` is the orchestrator. It should not block every iteration on Copilot before acting on Gemini Flash: fire both, fix Gemini findings first, then poll and handle Copilot before starting the next iteration.
- In deep mode, fresh-agent local review (`deepgrill`) runs **once at the end** of the bot loop, not during it. Inline local review inside the polling loop is what historically broke `reviewit` deep — keep the loop bot-only.
- Reply to every actionable AI review comment after fixes are pushed.
- Do not treat generated AI comments as automatically correct; verify each finding against the code.
- Fix every valid finding in the PR, including nits. Dismiss invalid findings or suggestions that would make the code worse. Defer only valid but extremely large follow-up refactors, roughly 300+ lines or cross-cutting rewrites, and track each deferral in a GitHub issue.
- Stop at the iteration cap and hand back a clear summary if findings keep recurring.
