---
name: agent-loop
description: Autonomous Codex relay loop on top of the issues skill. Use when the user wants Codex to claim ready GitHub issues, spawn non-interactive Codex exec sessions, push results to a collection branch, and open a summary PR.
---

# /agent-loop

Run an autonomous Codex relay over the issue ready queue. Each iteration claims an issue, spawns a fresh `codex exec` session in an isolated worktree, lets it work, then pushes the result to a shared collection branch. After the loop, opens an `agent-loop: <branch>` PR with the closed-issues + commit-log summary.

## Usage

```bash
.codex/skills/agent-loop/scripts/agent-loop.sh [iterations] [collection-branch] [--resume]
```

Defaults: 10 iterations, auto-generated collection branch (`agent-loop-<timestamp>-<rand>`), ready-queue-only.

| Args                      | Behavior                                                        |
| ------------------------- | --------------------------------------------------------------- |
| `5`                       | 5 iterations, auto-generated branch, ready-only                 |
| `5 wasm-plugins`          | 5 iterations, named collection branch                           |
| `5 wasm-plugins --resume` | also pick up issues already assigned to `@me` (orphan-recovery) |
| `--help`                  | print the script header                                         |

## Prerequisites (per-repo, one-time)

1. **`agent-loop-instructions.md` at the repo root** — repo-specific agent instructions (codebase conventions, build commands, test invocation, deployment quirks). The Codex prompt that points Codex here is **consumer-owned** in `.codex/skills/agent-loop/prompt.txt`, bootstrapped from `prompt.txt.template` on first sync (`create_if_missing: true`). The default content — `Read @agent-loop-instructions.md and follow the instructions. Your assigned issue is #{ISSUE_ID}. Run 'gh issue view {ISSUE_ID}' to see the full description, then complete it.` — is the value the script falls back to when `prompt.txt` is absent, empty, or unreadable. Edit `prompt.txt` to customize what Codex is told before reading your instructions file. If `agent-loop-instructions.md` itself is missing, the script exits before claiming work.

   The instructions, prompt, and `.codex/skills/agent-loop/agent-loop.config` are bootstrapped via `create_if_missing: true` from templates in `.codex/skills/agent-loop/`. After first creation, customize them for your repo; subsequent syncs leave them alone. Set `base_branch` in the config when the integration branch differs from the GitHub default branch.

2. **`dev: agent` label + a triaged backlog** in the consumer's GitHub repo. The script picks **only** issues carrying `dev: agent` — without the label, an issue is invisible to the loop. This is a positive filter, not an exclusion: the operator must walk the backlog once and tag the agent-shaped subset, which keeps the loop from wandering into design / cross-repo / device-gated work. Create the label once per repo, then triage:

   ```bash
   gh label create "dev: agent" --description "Suitable for autonomous AI agent completion" --color 8B5CF6
   ```

   Use the `backlog-refinement` skill to assess and prepare this queue. Its consumer-owned `RUBRIC.md` is the source of truth for readiness, make-ready transformations, and bail categories; do not bulk-tag issues from a looser checklist.

3. **`gh`, `jq`, `xxd`, `python3`, `codex`** on `PATH`. The script hard-fails if any are missing.
4. **`/issues` skill synced** — the script invokes `.codex/skills/issues/scripts/ready.py --json` to enumerate the queue. Without it the script exits at startup.

## Existing consumer migration

The instructions, prompt, and config are consumer-owned `create_if_missing`
targets, so syncing does not update copies that already exist. Before using
backlog RCA in an existing consumer, manually merge the **Continuous improvement
— classify every bail** and **Operator note — align the base branch** sections
from the current instruction template, add the bail reminder from the current
prompt template, and set `base_branch` in `agent-loop.config` when the integration
branch differs from the repository default.

## Behavior per iteration

1. Sync the worktree with `origin/<collection-branch>` — fetches and fast-forwards. If the remote was force-pushed, cherry-picks the local commits onto the new tip (with a pre-reset SHA snapshot so a failed cherry-pick restores the original chain rather than leaving partial replay). Genuine merge conflicts fail loud; the eventual push surfaces persistent ones via the `PUSH_FAILURES` counter.
2. Pick a work item: with `--resume`, prefer any open `dev: agent` issue already assigned to `@me`; otherwise the first dependency-free row from `ready.py --agent --json`. The `dev: agent` label is required on both paths — an empty queue means the backlog hasn't been triaged yet, not that there's no work to do.
3. Claim by adding `@me` as assignee. Re-fetch immediately afterward — if there are >1 assignees, a parallel worker raced; release and try the next row.
4. Spawn `codex exec --dangerously-bypass-approvals-and-sandbox --json -C <worktree> "$PROMPT"` and stream the JSON events through `jq` for display. The Codex PID is tracked so `Ctrl-C` interrupts the loop cleanly. **Prompt source:** the prompt is read from the consumer-owned `.codex/skills/agent-loop/prompt.txt` (bootstrapped from the upstream `prompt.txt.template` on first sync via `create_if_missing: true`); the script falls back to a baked-in literal when that file is absent, empty, or unreadable. The prompt must include `{ISSUE_ID}` so the wrapper can substitute the claimed issue number before spawning Codex.
5. Snapshot newly-closed issues since the loop started (used for the final PR body) and push to the collection branch via `push_to_collection` — retry-and-merge with up to 3 attempts.

## After the loop

If any commits accumulated on `origin/<collection-branch>` past `origin/<base-branch>`, opens an `agent-loop: <collection-branch>` PR (or attaches to an existing one) with:

- summary line: `<N> iteration(s), <M> commit(s)`
- `### Closed Issues` — newly-closed issues since loop start
- `### Commit Log` — `git log --oneline <base>..<collection>`

Then removes the worktree.

## Worktree isolation

Each invocation creates `/tmp/agent-loop-<branch>-<pid>` so multiple runs don't collide. The `Ctrl-C` trap attempts a final push of any committed work and then removes the worktree — but if that final push fails (auth, branch protection, force-push race), the worktree is **preserved** at `/tmp/agent-loop-...` so a human can recover the local commits. The post-loop path also preserves the worktree on push failure, before skipping PR creation.

## Base branch

Resolved in this order: `AGENT_LOOP_BASE_BRANCH`, `base_branch` in the consumer-owned `.codex/skills/agent-loop/agent-loop.config`, then the GitHub default branch from `origin/HEAD` (falling back to `main`). The collection branch and summary PR both use this base. Configure it explicitly for promotion-flow repositories whose integration branch differs from the default branch.

## Source of truth

This skill lives upstream at `.codex/skills/agent-loop/`. SKILL.md and `scripts/agent-loop.sh` are synced to consumer repos via the sync mechanism. Edits in a consumer will be overwritten on next sync — make changes upstream.
