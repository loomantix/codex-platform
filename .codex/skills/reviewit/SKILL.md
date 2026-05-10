---
name: reviewit
description: Post-push AI review orchestrator for pull requests. Use when the user asks Codex to run AI review on a PR, address Gemini or Copilot findings, dedupe reviewer comments, push fixes, reply in PR threads, or complete the platform review chain. Accepts a PR number and optional deep mode.
---

# Reviewit

Run the post-push review cycle for an open PR.

## Modes

- **Lean**: default. Fire Gemini Flash and request Copilot review. Cap at 2 iterations.
- **Deep**: if the argument includes `deep`. Also run a local Codex review pass and cap at 4 iterations.

## Process

1. Parse arguments: first token is PR number, optional second token is `deep`.
2. Verify the PR is open and the local branch matches the PR head:

   ```bash
   gh pr view <pr> --json number,title,headRefName,baseRefName,state,files,mergeable
   ```

3. Skip or ask before spending reviewer budget on docs/config-only PRs.
4. For each iteration:
   - Capture current PR head SHA and timestamp.
   - Trigger Gemini Flash:

     ```bash
     gh workflow run "Gemini Code Review" --repo <owner>/<repo> -F pr_number=<pr> -F tier=flash
     ```

   - Request Copilot via GraphQL bot reviewer:

     ```bash
     PR_NODE=$(gh pr view <pr> --json id --jq '.id')
     gh api graphql \
       -f query='mutation($prId:ID!,$botIds:[ID!]){requestReviews(input:{pullRequestId:$prId,botIds:$botIds,union:true}){pullRequest{id}}}' \
       -f prId="$PR_NODE" \
       -f botIds='BOT_kgDOCnlnWA'
     ```

   - In deep mode, also run a local Codex review of the PR diff and include those findings in dedupe.
   - Poll PR comments, PR review comments, and PR reviews until Gemini and Copilot have posted for the captured head SHA or timeout.
   - Deduplicate findings by file, line, and root cause.
   - Fix actionable findings, defer valid out-of-scope items to issues, dismiss false positives with rationale.
   - Commit and push fixes.
   - Reply to every inline AI comment after pushing, including the fix commit SHA or rationale.
   - Stop when no actionable findings remain or the iteration cap is reached.

## Important Details

- Pass `tier=flash` explicitly unless the user asks for Pro and accepts cost.
- Copilot may post inline comments without a review row; poll both endpoints.
- Do not count stale comments from a previous commit as completion.
- Do not reply before pushing fixes; replies should reference the real commit SHA.
- If a reviewer times out, continue with findings received and state the timeout in the summary.

## Output

Summarize mode, iterations, reviewers fired, findings fixed/deferred/dismissed, commits pushed, replies posted, and any remaining risks.
