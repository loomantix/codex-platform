---
name: ship-staging
description: Merge an approved GitHub pull request into a staging base branch and post a short Google Chat notification. Use when the user asks to ship, merge, or deploy a staging-targeted PR through the staging branch, especially with "ship-staging".
---

# Ship Staging

Merge one ready PR into `staging` and notify the configured development Google
Chat space. This skill is intentionally narrow: it ships staging-base PRs only.

## Guardrails

- Refuse when the PR base is not `staging`; production/main promotions need the
  repo's separate promotion or hotfix workflow.
- Use only `gh pr merge <pr> --merge --delete-branch`.
- Never use `--admin`, `--squash`, `--rebase`, `--auto`, or `--no-verify`.
- Stop on draft PRs, merge conflicts, blocked/dirty/unstable merge state,
  requested changes, failing CI, or required checks still running.
- Resolve the Google Chat webhook at runtime from `GCHAT_DEV_WEBHOOK_URL`, or
  from `GCHAT_DEV_WEBHOOK_FILE` when set, otherwise from
  `$HOME/.config/codex-platform/gchat-dev-webhook.txt`.
- Treat the webhook URL as a secret: never print it, commit it, or include it in
  logs, PRs, issues, or summaries.
- Do not merge if the webhook secret is unavailable; the notification is part of
  the staging ship contract.

## Process

1. Parse the PR number from the first argument. Accept optional `--yes` only
   when the user explicitly requested an automatic path.
2. Resolve the webhook secret before validating the PR:

   ```bash
   if [[ -n "$GCHAT_DEV_WEBHOOK_URL" ]]; then
     GCHAT_WEBHOOK_URL="$GCHAT_DEV_WEBHOOK_URL"
   else
     WEBHOOK_FILE="${GCHAT_DEV_WEBHOOK_FILE:-$HOME/.config/codex-platform/gchat-dev-webhook.txt}"
     if [[ ! -f "$WEBHOOK_FILE" ]]; then
       echo "Missing webhook secret: set GCHAT_DEV_WEBHOOK_URL or create $WEBHOOK_FILE" >&2
       exit 1
     fi
     GCHAT_WEBHOOK_URL=$(<"$WEBHOOK_FILE")
   fi
   ```

3. Fetch PR state:

   ```bash
   gh pr view <pr> --json number,title,state,isDraft,baseRefName,headRefName,headRefOid,mergeable,mergeStateStatus,url,body,author,reviewDecision,statusCheckRollup,labels
   ```

4. Refuse without merging when any of these are true:
   - `state != "OPEN"`
   - `isDraft == true`
   - `baseRefName != "staging"`
   - `mergeable != "MERGEABLE"`
   - `mergeStateStatus` is `BLOCKED`, `BEHIND`, `DIRTY`, or `UNSTABLE`
   - `reviewDecision == "CHANGES_REQUESTED"`
   - any status check conclusion is `FAILURE`, `CANCELLED`, `TIMED_OUT`, or
     `ACTION_REQUIRED`
   - any required status check is `PENDING`, `IN_PROGRESS`, or `QUEUED`

   `mergeStateStatus` of `CLEAN` or `HAS_HOOKS` is acceptable when checks are
   otherwise green.

5. Draft a Google Chat message. Keep it under 600 characters and at most three
   sentences after the header. Do not include PHI, secrets, internal IPs, commit
   SHAs, or reviewer/bot names.

   Template:

   ```text
   *Merged to staging:* PR #<number> - <title>

   <one-to-three sentence summary of what changed, why it matters, and caveats/follow-ups if any>

   <url>
   ```

   Save it as JSON:

   ```bash
   jq -n --arg text "$MESSAGE" '{text: $text}' > /tmp/ship-staging-<pr>-payload.json
   ```

6. Unless `--yes` was explicitly requested, show the assembled message and exact
   merge command, then ask the user to choose ship, edit summary, or cancel.
7. Merge:

   ```bash
   gh pr merge <pr> --merge --delete-branch
   ```

   If the merge fails, do not post to chat.

8. Capture the merge commit:

   ```bash
   MERGE_SHA=$(gh pr view <pr> --json mergeCommit --jq '.mergeCommit.oid')
   ```

9. Post to Google Chat:

   ```bash
   RESPONSE=$(curl -sS -w "\n%{http_code}" \
     -X POST \
     -H "Content-Type: application/json" \
     --data @/tmp/ship-staging-<pr>-payload.json \
     "$GCHAT_WEBHOOK_URL")
   HTTP_CODE=$(echo "$RESPONSE" | tail -1)
   BODY=$(echo "$RESPONSE" | sed '$d')
   MSG_ID=$(echo "$BODY" | jq -r '.name // empty')
   ```

   Success requires `HTTP_CODE == 200` and a non-empty message id shaped like
   `spaces/<space-id>/messages/<msg-id>`. If Google Chat returns `429`, wait
   30 seconds and retry once. If posting still fails, report that the PR merged
   but notification failed and leave the payload file in `/tmp` for manual
   re-posting.

10. On successful chat post, remove the temp payload file and report:

    ```text
    Shipped PR #<number> - <title>
    Merge commit: <short-sha>
    Chat notification: posted (message id <msg-id>)
    PR: <url>
    ```

## Summary Guidance

Write for teammates skimming a dev channel. Prefer concrete user or operational
impact over implementation detail. Mention migrations, flags, follow-up issue
numbers, or manual validation only when relevant. Keep the PR link as the source
of traceability instead of listing commits.
