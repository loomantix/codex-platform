---
name: ship-staging
description: Merge an approved GitHub pull request into a staging base branch, mark linked issues as on-staging, fast-forward the local staging reference checkout, and post a short Google Chat notification. Use when the user asks to ship, merge, or deploy a staging-targeted PR through the staging branch, especially with "ship-staging".
---

# Ship Staging

Merge one ready PR into `staging`, mark its linked issues as shipped to
staging, refresh the local staging reference checkout, and notify the configured
development Google Chat space. This skill is intentionally narrow: it ships
staging-base PRs only.

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

   If the merge fails, do not post to chat and do not label issues.

8. Capture the merge commit:

   ```bash
   MERGE_SHA=$(gh pr view <pr> --json mergeCommit --jq '.mergeCommit.oid')
   ```

9. Mark linked open issues as on-staging. A closing keyword on a staging PR does
   not close the issue until the work later reaches the default branch, so open
   fixed issues need an explicit "done, awaiting promotion" label in the
   meantime. Prefer GitHub's parsed closing references; fall back to explicit
   `Closes #N`, `Fixes #N`, or `Resolves #N` text in the PR title/body.

   ```bash
   LINKED=$(gh pr view <pr> --json closingIssuesReferences \
     --jq '.closingIssuesReferences[].number' 2>/dev/null)
   if [[ -z "$LINKED" ]]; then
     LINKED=$(gh pr view <pr> --json title,body \
       --jq '[.title, .body] | join("\n")' \
       | grep -ioE '(close[sd]?|fix(e[sd])?|resolve[sd]?)[: ]+#[0-9]+' \
       | grep -oE '[0-9]+' | sort -u)
   fi

   ISSUES_MARKED=()
   for n in $LINKED; do
     state=$(gh issue view "$n" --json state --jq '.state' 2>/dev/null) || {
       echo "warning: could not read issue #$n; leaving labels unchanged" >&2
       continue
     }
     [[ "$state" == "OPEN" ]] || continue

     mapfile -t issue_labels < <(
       gh issue view "$n" --json labels --jq '.labels[].name' 2>/dev/null
     )
     edit_args=(--add-label "status: on-staging")
     if printf '%s\n' "${issue_labels[@]}" | grep -Fxq "dev: agent"; then
       edit_args+=(--remove-label "dev: agent")
     fi

     if gh issue edit "$n" "${edit_args[@]}"; then
       ISSUES_MARKED+=("#$n")
       echo "  marked #$n status: on-staging"
     else
       echo "warning: could not mark issue #$n status: on-staging" >&2
     fi
   done
   ```

   Keep this phase best-effort: labeling failures must not block the chat post
   because the PR has already merged. Do not close the issues. Do not add
   unrelated workflow labels. `status: on-staging` is the only label this skill
   adds. Remove only the agent-loop admission label `dev: agent` when it is
   present.

10. Fast-forward the local staging reference checkout. This keeps new worktrees
    and later staging/promotion diffs from starting from a stale local branch.
    The checkout can be overridden with `SHIP_STAGING_MAIN_CHECKOUT`; otherwise
    default to `$HOME/<repo-name>`, derived from the current repository's
    `origin` URL.

    ```bash
    current_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
    origin_url=$(git -C "$current_root" remote get-url origin 2>/dev/null || true)
    repo_name=$(basename "$origin_url")
    repo_name="${repo_name%.git}"
    MAIN_CHECKOUT="${SHIP_STAGING_MAIN_CHECKOUT:-}"
    if [[ -z "$MAIN_CHECKOUT" && -n "$repo_name" && "$repo_name" != "." ]]; then
      MAIN_CHECKOUT="$HOME/$repo_name"
    fi
    if [[ -z "$MAIN_CHECKOUT" ]]; then
      MAIN_CHECKOUT="$current_root"
    fi

    if ! git -C "$MAIN_CHECKOUT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      echo "  (skip ff: $MAIN_CHECKOUT is not a git checkout)"
    elif [[ "$(git -C "$MAIN_CHECKOUT" rev-parse --abbrev-ref HEAD)" != "staging" ]]; then
      echo "  (skip ff: $MAIN_CHECKOUT is not on staging)"
    elif [[ -n "$(git -C "$MAIN_CHECKOUT" status --porcelain)" ]]; then
      echo "  (skip ff: $MAIN_CHECKOUT has uncommitted changes)"
    else
      git -C "$MAIN_CHECKOUT" fetch origin staging --quiet
      if git -C "$MAIN_CHECKOUT" merge --ff-only origin/staging --quiet 2>/dev/null; then
        echo "  fast-forwarded $MAIN_CHECKOUT to origin/staging"
      else
        echo "  (skip ff: $MAIN_CHECKOUT could not fast-forward)"
      fi
    fi
    ```

    Fast-forward only. Never use merge commits, rebase, checkout overwrite, or
    `reset --hard` for this cleanup. Keep it best-effort like issue labeling:
    report the result, but do not block the chat post.

11. Post to Google Chat:

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

12. On successful chat post, remove the temp payload file and report:

    ```text
    Shipped PR #<number> - <title>
    Merge commit: <short-sha>
    Issues marked status: on-staging: <#N, #M | none>
    Staging checkout: <fast-forwarded | skipped with reason>
    Chat notification: posted (message id <msg-id>)
    PR: <url>
    ```

## Summary Guidance

Write for teammates skimming a dev channel. Prefer concrete user or operational
impact over implementation detail. Mention migrations, flags, follow-up issue
numbers, or manual validation only when relevant. Keep the PR link as the source
of traceability instead of listing commits.
