---
name: reviewit
description: Post-push AI review orchestrator for pull requests. Use when the user asks Codex to run AI review on a PR, address Gemini or Copilot findings, dedupe reviewer comments, push fixes, reply in PR threads, or complete the platform review chain. Accepts a PR number, optional deep mode, and optional --resume.
---

# Reviewit

Run the post-push review cycle for an open PR.

## Modes

- **Lean**: default. Fire Gemini Flash and request Copilot review. Cap at 2 iterations.
- **Deep**: if the argument includes `deep`. Also run a local Codex review pass and cap at 4 iterations.
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
4. If `--resume` is present:
   - Load `.codex/reviewit-state/<pr>.json` if present.
   - If no state file exists, reconstruct enough state from `gh pr view`, PR reviews, PR review comments, issue comments, and workflow runs. Use the current PR head SHA as `headSha`.
   - If the current PR head SHA differs from the saved `headSha`, ask whether to start a new iteration. Do not silently process stale reviewer output.
   - Do not trigger Gemini or request Copilot again unless the saved reviewer request clearly failed or the user explicitly asks to rerun.
   - Continue at the polling/dedupe/fix/reply step.
5. For each iteration:
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
   - In deep mode, also run a local Codex review of the PR diff and include those findings in dedupe.
   - Poll PR comments, PR review comments, and PR reviews for a short active budget by default (60-90 seconds). Use `--wait` only when the user explicitly wants Codex to stay blocked.
   - If Gemini or Copilot has not posted after the short budget, stop cleanly and report:
     - PR number
     - `headSha`
     - reviewers fired
     - reviewer status
     - state file path
     - exact resume command, for example `reviewit <pr> deep --resume`
   - On resume, poll only reviewer output for the saved `headSha` and comments newer than `startedAt`.
   - Deduplicate findings by file, line, and root cause.
   - Fix actionable findings, defer valid out-of-scope items to issues, dismiss false positives with rationale.
   - Commit and push fixes.
   - Reply to every inline AI comment after pushing, including the fix commit SHA or rationale.
   - Append handled comment ids to the state file so repeated resumes do not duplicate replies.
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

## Output

Summarize mode, iterations, reviewers fired, reviewer status, findings fixed/deferred/dismissed, commits pushed, replies posted, state file path if still waiting, resume command if applicable, and any remaining risks.
