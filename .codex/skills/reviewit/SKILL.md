---
name: reviewit
description: Post-push AI review orchestrator for pull requests. Use when the user asks Codex to run AI review on a PR, address Gemini or Copilot findings, dedupe reviewer comments, push fixes, reply in PR threads, or complete the platform review chain. Accepts a PR number, optional deep mode, and optional --resume.
---

# Reviewit

Run the post-push review cycle for an open PR.

## Modes

- **Lean**: default. Fire Gemini Flash and request Copilot review, but use staggered handling: fix Gemini first, then fold in Copilot when it finishes. Cap at 2 iterations.
- **Deep**: if the argument includes `deep`. Also run the local Codex deep-review path, fix local/Gemini findings first, then fold in Copilot when it finishes. Cap at 4 iterations.
- **Resume**: if the argument includes `--resume`, do not fire reviewers again. Load or reconstruct the review state for the current PR head, poll existing reviewer output, then fix/reply.

## State

Persist reviewer state locally so the long Copilot wait does not block an active Codex turn:

```text
.codex/reviewit-state/<pr>.json
```

Create the directory if needed. The state file is local agent bookkeeping; do not commit it. Store at least:

- `pr`: PR number
- `headSha`: PR head SHA at reviewer trigger time
- `startedAt`: UTC timestamp captured before firing reviewers
- `mode`: `lean` or `deep`
- `iteration`: current iteration number
- `geminiRunId`: workflow run id when discoverable
- `copilotRequested`: boolean
- `phase`: current reviewer phase, such as `awaiting-gemini`, `handling-fast-findings`, `awaiting-copilot`, or `complete`
- `handledCommentIds`: inline/review/issue comment ids already fixed or replied to
- `lastPollAt`: UTC timestamp of the most recent poll

If `.codex/reviewit-state/` is not gitignored, add it to a repo-appropriate ignore file before writing state.

## Process

1. Parse arguments: first token is PR number. Optional tokens:
   - `deep`
   - `--resume`
   - `--wait` to keep polling until reviewers complete or timeout
2. Verify the PR is open and the local branch matches the PR head:

   ```bash
   gh pr view <pr> --json number,title,headRefName,baseRefName,headRefOid,state,files,mergeable,id
   ```

3. Skip or ask before spending reviewer budget on docs/config-only PRs.
4. Use an adversarial stance for all local review in this skill: assume there are problems to find, try to disprove safety with code/tests/docs evidence, and report only actionable findings with file/line support.
5. Bias toward fixing every valid finding in this PR, including nits and cleanup items. Dismiss only invalid findings, false positives, or suggestions that would make the code worse. Defer only valid but extremely large follow-up refactors, roughly 300+ lines or cross-cutting rewrites, and create/link a GitHub issue for each deferral.
6. If `--resume` is present:
   - Load `.codex/reviewit-state/<pr>.json` if present.
   - If no state file exists, reconstruct enough state from `gh pr view`, PR reviews, PR review comments, issue comments, and workflow runs. Use the current PR head SHA as `headSha`.
   - If the current PR head SHA differs from the saved `headSha`, ask whether to start a new iteration. Do not silently process stale reviewer output.
   - Do not trigger Gemini or request Copilot again unless the saved reviewer request clearly failed or the user explicitly asks to rerun.
   - Continue at the polling/dedupe/fix/reply step.
7. For each iteration:
   - Capture current PR head SHA and timestamp before firing reviewers.
   - Write the initial state file.
   - Trigger Gemini Flash:

     ```bash
     gh workflow run "Gemini Code Review" --repo <owner>/<repo> -F pr_number=<pr> -F tier=flash
     ```

   - Record the Gemini workflow run id when discoverable:

     ```bash
     gh run list --repo <owner>/<repo> --workflow "Gemini Code Review" --limit 10 --json databaseId,status,createdAt,headBranch
     ```

   - Request Copilot via GraphQL bot reviewer:

     ```bash
     PR_NODE=$(gh pr view <pr> --json id --jq '.id')
     gh api graphql \
       -f query='mutation($prId:ID!,$botIds:[ID!]){requestReviews(input:{pullRequestId:$prId,botIds:$botIds,union:true}){pullRequest{id}}}' \
       -f prId="$PR_NODE" \
       -f botIds='BOT_kgDOCnlnWA'
     ```

   - Mark `copilotRequested: true` in the state file.
   - In deep mode, also run local Codex review of the PR diff while Gemini and Copilot are running. Include those findings in the first dedupe/fix pass. The local pass must be at least as thorough as `grill deep`: code reviewer, silent failure hunter, type/API design analyzer, comment/docs analyzer, PR test analyzer, and security reviewer. Use independent subagents when the active runtime permits them; otherwise run six separate local passes and disclose that fallback in the summary.
   - Set `phase: awaiting-gemini`. Poll PR comments, PR review comments, PR reviews, and the Gemini workflow run for Gemini output on `headSha`. Use a short active budget by default (60-90 seconds) unless `--wait` is present. Do not wait for Copilot in this phase.
   - If Gemini has not posted after the short budget and there are no local deep-review findings, stop cleanly and report:
     - PR number
     - `headSha`
     - reviewers fired
     - reviewer status
     - state file path
     - exact resume command, for example `reviewit <pr> deep --resume`
   - Set `phase: handling-fast-findings`. Deduplicate Gemini plus local deep-review findings by file, line, and root cause. Fix every valid finding, including nits. Defer only valid but extremely large follow-up refactors to GitHub issues. Dismiss invalid findings and false positives with rationale.
   - Commit and push the Gemini/local fixes before waiting on Copilot.
   - Reply to every handled Gemini/local inline AI comment after pushing, including the fix commit SHA or rationale. Append handled comment ids to the state file so repeated resumes do not duplicate replies.
   - Set `phase: awaiting-copilot`. Now poll Copilot output for the original `headSha` and comments newer than `startedAt`. Copilot is allowed to be reviewing the pre-fix head; treat its findings as delayed feedback on that iteration.
   - If Copilot has not posted yet, poll briefly by default. If `--wait` is present, keep polling until Copilot completes or times out. If Copilot is still missing after the allowed wait, stop cleanly with the same state/resume details; do not start the next iteration until the pending Copilot request is handled or explicitly abandoned.
   - Deduplicate Copilot findings against already-handled Gemini/local findings and the current working tree. If a Copilot finding was already fixed by the Gemini/local commit, reply with that commit SHA and record it handled. Fix any remaining valid Copilot findings on top of the current head, push, and reply.
   - On resume, continue from `phase`: poll only reviewer output for the saved `headSha` and comments newer than `startedAt`, then handle only unhandled comment ids.
   - Stop when no actionable findings remain or the iteration cap is reached.

## Important Details

- Pass `tier=flash` explicitly unless the user asks for Pro and accepts cost.
- Copilot may post inline comments without a review row; poll both endpoints.
- Do not count stale comments from a previous commit as completion.
- Do not retrigger Gemini or Copilot on `--resume` unless the PR head changed and the user starts a new iteration, or the original request failed.
- Prefer exiting with a resume command over waiting 5-10 minutes for Copilot during an interactive Codex turn.
- Do not reply before pushing fixes; replies should reference the real commit SHA.
- If a reviewer times out in `--wait` mode, continue with findings received and state the timeout in the summary.
- Keep `.codex/reviewit-state/*.json` out of commits.

## Local Codex Review In Deep Mode

In deep mode, run the local Codex reviewer against the PR diff:

```bash
codex review --base <base-branch> --title "<pr title>"
```

If the Codex CLI fails before review starts with a filesystem error such as
`Read-only file system` or `failed to initialize in-process app-server client`,
retry the same command with the harness/tool escalation needed to let Codex write
to its normal state directory, usually `${CODEX_HOME:-$HOME/.codex}`.

Do not work around that failure by setting `CODEX_HOME` to a fresh temp directory.
A blank temp home drops the user's existing `auth.json`, `config.toml`, and
provider state, which turns a filesystem problem into an authentication failure
such as `401 Unauthorized: Missing bearer or basic authentication`.

Bad workaround:

```bash
CODEX_HOME=/tmp/codex-home codex review --base <base-branch> --title "<pr title>"
```

Before using any non-default `CODEX_HOME`, verify that it already contains a
valid Codex auth/config setup or that the environment explicitly provisions API
credentials for that home. If one escalated retry with the authenticated Codex
home still fails, record the local Codex reviewer as unavailable in the
`reviewit` summary and continue with Gemini/Copilot instead of blocking the
whole review cycle.

The CLI reviewer does not replace the deep-review lane requirement above unless
it clearly returns equivalent lane coverage. If the CLI review is unavailable,
too shallow, or does not expose lane-level findings, perform the six local lanes
manually or with subagents when permitted and include them in dedupe.

## Output

Summarize mode, iterations, reviewers fired, reviewer status, findings fixed/deferred/dismissed, commits pushed, replies posted, state file path if still waiting, resume command if applicable, and any remaining risks.
