#!/usr/bin/env bash
# Deterministic, per-issue agent loop with local reviews before publication.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

MAX_ITERATIONS=10
ISSUE_ALLOWLIST=""
RESUME_IN_PROGRESS=false
DRY_RUN=false
LEGACY_ITERATIONS_SEEN=false

usage() {
    cat <<'EOF'
Usage: agent-loop.sh [iterations] [options]

Options:
  --iterations N       Process at most N issues (default: 10).
  --issues N,N,...     Restrict selection to this explicit issue allowlist.
  --resume             Permit allowlisted issues already assigned only to @me
                       (no effect on the ready queue, which is unassigned-only).
  --dry-run            Show selection, gates, paths, hooks, and publication only.
  -h, --help           Show this help.

The legacy numeric first argument remains supported. Collection branches are no
longer supported: every issue receives its own branch, worktree, and pull request.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --iterations)
            [ "$#" -ge 2 ] || { echo "--iterations requires a value" >&2; exit 2; }
            MAX_ITERATIONS="$2"
            shift 2
            ;;
        --issues)
            [ "$#" -ge 2 ] || { echo "--issues requires a comma-separated value" >&2; exit 2; }
            ISSUE_ALLOWLIST="$2"
            shift 2
            ;;
        --resume)
            RESUME_IN_PROGRESS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        [0-9]*)
            if [ "$LEGACY_ITERATIONS_SEEN" = true ]; then
                echo "unexpected positional argument: $1" >&2
                exit 2
            fi
            MAX_ITERATIONS="$1"
            LEGACY_ITERATIONS_SEEN=true
            shift
            ;;
        *)
            echo "unexpected argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! [[ "$MAX_ITERATIONS" =~ ^[1-9][0-9]*$ ]]; then
    echo "iterations must be a positive integer: $MAX_ITERATIONS" >&2
    exit 2
fi
if [ -n "$ISSUE_ALLOWLIST" ] && ! [[ "$ISSUE_ALLOWLIST" =~ ^[1-9][0-9]*(,[1-9][0-9]*)*$ ]]; then
    echo "--issues must be a comma-separated list of positive issue numbers" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -n "${AGENT_LOOP_PROJECT_DIR:-}" ]; then
    PROJECT_DIR="$AGENT_LOOP_PROJECT_DIR"
else
    PROJECT_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "$PROJECT_DIR" ]; then
    echo "Could not find a Git repository from $SCRIPT_DIR" >&2
    exit 1
fi

CONFIG_FILE="$PROJECT_DIR/.codex/skills/agent-loop/agent-loop.config"
PROMPT_FILE="$PROJECT_DIR/.codex/skills/agent-loop/prompt.txt"
INSTRUCTIONS_FILE="$PROJECT_DIR/agent-loop-instructions.md"
ISSUES_READY="$PROJECT_DIR/.codex/skills/issues/scripts/ready.py"

BASE_BRANCH=""
SETUP_HOOK=""
VALIDATION_HOOK=""
CLAUDE_REVIEW_HOOK=""
CODEX_REVIEW_HOOK=""
WORKER_HOOK=""
WORKER_MODEL=""
WORKER_FALLBACK_MODEL=""
WORKER_RETRIES=1
WORKER_TIMEOUT_SECONDS=3600
HOOK_TIMEOUT_SECONDS=3600
RETRY_ON_TIMEOUT=true
RETRY_DELAY_SECONDS=15
DEPENDENCY_GATE=ready
BRANCH_PREFIX=agent-loop
WORKTREE_ROOT="${TMPDIR:-/tmp}/agent-loop-worktrees"
LOG_ROOT="${TMPDIR:-/tmp}/agent-loop-logs"
LOG_MAX_KB=1024
OUTPUT_MAX_LINES=40

assign_config() {
    local key="$1" value="$2"
    case "$key" in
        base_branch) BASE_BRANCH="$value" ;;
        setup_hook) SETUP_HOOK="$value" ;;
        validation_hook) VALIDATION_HOOK="$value" ;;
        claude_review_hook) CLAUDE_REVIEW_HOOK="$value" ;;
        codex_review_hook) CODEX_REVIEW_HOOK="$value" ;;
        worker_hook) WORKER_HOOK="$value" ;;
        worker_model) WORKER_MODEL="$value" ;;
        worker_fallback_model) WORKER_FALLBACK_MODEL="$value" ;;
        worker_retries) WORKER_RETRIES="$value" ;;
        worker_timeout_seconds) WORKER_TIMEOUT_SECONDS="$value" ;;
        hook_timeout_seconds) HOOK_TIMEOUT_SECONDS="$value" ;;
        retry_on_timeout) RETRY_ON_TIMEOUT="$value" ;;
        retry_delay_seconds) RETRY_DELAY_SECONDS="$value" ;;
        dependency_gate) DEPENDENCY_GATE="$value" ;;
        branch_prefix) BRANCH_PREFIX="$value" ;;
        worktree_root) WORKTREE_ROOT="$value" ;;
        log_root) LOG_ROOT="$value" ;;
        log_max_kb) LOG_MAX_KB="$value" ;;
        output_max_lines) OUTPUT_MAX_LINES="$value" ;;
        *) echo "unknown agent-loop config key: $key" >&2; exit 1 ;;
    esac
}

if [ -e "$CONFIG_FILE" ]; then
    if [ ! -f "$CONFIG_FILE" ] || [ ! -r "$CONFIG_FILE" ]; then
        echo "agent-loop config is not a readable regular file: $CONFIG_FILE" >&2
        exit 1
    fi
    declare -A CONFIG_KEYS=()
    while IFS= read -r raw || [ -n "$raw" ]; do
        line="${raw#"${raw%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [ -z "$line" ] && continue
        [[ "$line" == \#* ]] && continue
        if ! [[ "$line" =~ ^([a-z_]+)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
            echo "invalid agent-loop config line: $raw" >&2
            exit 1
        fi
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        value="${value%"${value##*[![:space:]]}"}"
        [ -z "${CONFIG_KEYS[$key]:-}" ] || { echo "duplicate agent-loop config key: $key" >&2; exit 1; }
        CONFIG_KEYS[$key]=1
        assign_config "$key" "$value"
    done < "$CONFIG_FILE"
fi

BASE_BRANCH="${AGENT_LOOP_BASE_BRANCH:-$BASE_BRANCH}"
if [ -z "$BASE_BRANCH" ]; then
    BASE_BRANCH="$(git -C "$PROJECT_DIR" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || true)"
fi
BASE_BRANCH="${BASE_BRANCH:-main}"

validate_ref_component() {
    local value="$1" label="$2"
    if ! git -C "$PROJECT_DIR" check-ref-format --branch "$value" >/dev/null 2>&1; then
        echo "$label is not a valid branch name: $value" >&2
        exit 1
    fi
}
validate_ref_component "$BASE_BRANCH" "base branch"
validate_ref_component "$BRANCH_PREFIX/example" "branch prefix"

for value in "$WORKER_RETRIES" "$WORKER_TIMEOUT_SECONDS" "$HOOK_TIMEOUT_SECONDS" \
             "$RETRY_DELAY_SECONDS" "$LOG_MAX_KB" "$OUTPUT_MAX_LINES"; do
    [[ "$value" =~ ^[0-9]+$ ]] || { echo "numeric agent-loop config value required: $value" >&2; exit 1; }
done
case "$RETRY_ON_TIMEOUT" in true|false) ;; *) echo "retry_on_timeout must be true or false" >&2; exit 1 ;; esac
case "$DEPENDENCY_GATE" in ready|merged-to-base) ;; *) echo "dependency_gate must be ready or merged-to-base" >&2; exit 1 ;; esac

for cmd in git gh jq python3 timeout; do
    command -v "$cmd" >/dev/null 2>&1 || { echo "required command not found: $cmd" >&2; exit 1; }
done
if [ -z "$WORKER_HOOK" ]; then
    command -v codex >/dev/null 2>&1 || {
        echo "required command not found for default worker: codex" >&2
        exit 1
    }
fi
[ -x "$ISSUES_READY" ] || { echo "issues ready.py not found or not executable: $ISSUES_READY" >&2; exit 1; }
[ -f "$INSTRUCTIONS_FILE" ] || { echo "agent-loop-instructions.md not found at repository root" >&2; exit 1; }
[ -n "$CLAUDE_REVIEW_HOOK" ] || { echo "claude_review_hook must be configured before running agent-loop" >&2; exit 1; }
[ -n "$CODEX_REVIEW_HOOK" ] || { echo "codex_review_hook must be configured before running agent-loop" >&2; exit 1; }

if [ -s "$PROMPT_FILE" ] && [ -r "$PROMPT_FILE" ]; then
    PROMPT_TEMPLATE="$(<"$PROMPT_FILE")"
else
    PROMPT_TEMPLATE="Read @agent-loop-instructions.md. Implement issue #{ISSUE_ID}, validate it, and commit locally. Do not push or open a pull request."
fi
[[ "$PROMPT_TEMPLATE" == *"{ISSUE_ID}"* ]] || { echo "prompt template must contain {ISSUE_ID}: $PROMPT_FILE" >&2; exit 1; }

cd "$PROJECT_DIR"
if [ "$DRY_RUN" = false ]; then
    git fetch origin "$BASE_BRANCH" --quiet
fi
git rev-parse --verify --quiet "refs/remotes/origin/$BASE_BRANCH" >/dev/null || {
    echo "configured base branch does not exist locally: origin/$BASE_BRANCH" >&2
    [ "$DRY_RUN" = true ] && echo "Dry-run does not fetch; fetch the base branch once and retry." >&2
    exit 1
}

# Resolve the current login once, up front. Doing it per-candidate inside an
# unchecked command substitution meant a transient gh failure silently rendered a
# resume-eligible issue "not mine" and skipped it.
CURRENT_LOGIN="$(gh api user --jq .login)" || {
    echo "could not determine current GitHub login (is gh authenticated?)" >&2
    exit 1
}
[ -n "$CURRENT_LOGIN" ] || { echo "current GitHub login resolved empty" >&2; exit 1; }

REPO_NAME="$(basename "$PROJECT_DIR")"
RUN_TAG="$(date -u +%Y%m%d-%H%M%S)-$$"
ACTIVE_WORKTREE=""
RECOVERY_EMITTED=false
PROCESSED_ISSUES=()

recovery_message() {
    local reason="$1"
    RECOVERY_EMITTED=true
    echo -e "${RED}✗${NC} $reason" >&2
    if [ -n "$ACTIVE_WORKTREE" ]; then
        echo "Worktree preserved: $ACTIVE_WORKTREE" >&2
        echo "Inspect with: git -C '$ACTIVE_WORKTREE' status --short --branch" >&2
        echo "Recover commits with: git -C '$ACTIVE_WORKTREE' log --oneline --decorate -10" >&2
        echo "Do not reset, reuse, or remove it until the work is recovered." >&2
    fi
}

on_interrupt() {
    recovery_message "Interrupted; no cleanup was attempted."
    exit 130
}

on_exit() {
    local rc=$?
    # Backstop for unguarded `set -e` aborts (e.g. a mid-pipeline git fetch/worktree
    # failure) that would otherwise exit while an issue is claimed and live work sits
    # in the worktree, with no recovery guidance. recovery_message sets the flag, so
    # the explicit `recovery_message; exit 1` sites never double-report.
    if [ "$rc" -ne 0 ] && [ "$RECOVERY_EMITTED" = false ] && [ -n "$ACTIVE_WORKTREE" ]; then
        recovery_message "agent-loop aborted (exit $rc) with issue #${SELECTED_ID:-unknown} claimed."
    fi
}
trap on_interrupt INT TERM
trap on_exit EXIT

already_processed() {
    local candidate="$1" seen
    for seen in "${PROCESSED_ISSUES[@]:-}"; do
        [ "$seen" = "$candidate" ] && return 0
    done
    return 1
}

issue_json() {
    gh issue view "$1" --json number,title,body,state,labels,assignees
}

issue_is_selectable() {
    local number="$1" json="$2"
    [ "$(jq -r '.state' <<<"$json")" = OPEN ] || return 1
    jq -e '.labels | any(.name == "dev: agent")' <<<"$json" >/dev/null || return 1
    local count mine
    count="$(jq '.assignees | length' <<<"$json")"
    mine="$(jq -r '.assignees | any(.login == "'"$CURRENT_LOGIN"'")' <<<"$json")"
    if [ "$count" -eq 0 ]; then
        return 0
    fi
    [ "$RESUME_IN_PROGRESS" = true ] && [ "$mine" = true ] && [ "$count" -eq 1 ]
}

SELECTED_ID=""
SELECTED_BODY=""
SELECTED_ASSIGNED=false

select_next_issue() {
    SELECTED_ID=""
    SELECTED_BODY=""
    SELECTED_ASSIGNED=false
    local json number
    if [ -n "$ISSUE_ALLOWLIST" ]; then
        local candidates
        IFS=',' read -r -a candidates <<< "$ISSUE_ALLOWLIST"
        for number in "${candidates[@]}"; do
            already_processed "$number" && continue
            json="$(issue_json "$number")" || return 2
            if ! issue_is_selectable "$number" "$json"; then
                echo -e "${DIM}○${NC} Allowlisted issue #$number is not open, agent-labeled, or safely assignable." >&2
                PROCESSED_ISSUES+=("$number")
                continue
            fi
            SELECTED_ID="$number"
            SELECTED_BODY="$(jq -r '.body // ""' <<<"$json")"
            [ "$(jq '.assignees | length' <<<"$json")" -gt 0 ] && SELECTED_ASSIGNED=true
            return 0
        done
        return 1
    fi

    local ready_json
    ready_json="$("$ISSUES_READY" --unassigned --agent --limit 100 --json)" || return 2
    while IFS= read -r number; do
        [ -n "$number" ] || continue
        already_processed "$number" && continue
        json="$(issue_json "$number")" || return 2
        issue_is_selectable "$number" "$json" || continue
        SELECTED_ID="$number"
        SELECTED_BODY="$(jq -r '.body // ""' <<<"$json")"
        return 0
    done < <(jq -r '.[].number' <<<"$ready_json")
    return 1
}

pr_merged_to_base() {
    local pr="$1" data state base oid
    data="$(gh pr view "$pr" --json state,baseRefName,mergeCommit --jq '[.state,.baseRefName,(.mergeCommit.oid // "")] | @tsv' 2>/dev/null)" || return 1
    IFS=$'\t' read -r state base oid <<< "$data"
    [ "$state" = MERGED ] && [ "$base" = "$BASE_BRANCH" ] && [ -n "$oid" ] || return 1
    git merge-base --is-ancestor "$oid" "origin/$BASE_BRANCH" >/dev/null 2>&1
}

issue_dependency_merged() {
    local issue="$1" rows pr
    rows="$(gh issue view "$issue" --json closedByPullRequestsReferences \
        --jq '.closedByPullRequestsReferences[]? | [.number,.state,.baseRefName,(.mergeCommit.oid // "")] | @tsv' 2>/dev/null)" || return 1
    while IFS=$'\t' read -r pr _; do
        [ -n "$pr" ] || continue
        pr_merged_to_base "$pr" && return 0
    done <<< "$rows"
    return 1
}

dependency_refs() {
    python3 -c 'import re,sys
body=sys.stdin.read()
pattern=re.compile(r"(?im)^\s*[-*]?\s*(?:blocked\s+by|depends\s+on)[:\s]+(?:(pr)\s*)?#(\d+)\b")
for kind, number in pattern.findall(body):
    print(("pr" if kind else "issue") + "\t" + number)' <<< "$1"
}

check_dependencies() {
    local body="$1" kind number found=false
    if [ "$DEPENDENCY_GATE" = ready ]; then
        echo "   Dependency gate: ready-queue semantics"
        return 0
    fi
    while IFS=$'\t' read -r kind number; do
        [ -n "$number" ] || continue
        found=true
        if { [ "$kind" = pr ] && pr_merged_to_base "$number"; } || \
           { [ "$kind" = issue ] && issue_dependency_merged "$number"; }; then
            echo "   Dependency $kind #$number: merged into origin/$BASE_BRANCH"
        else
            echo "   Dependency $kind #$number: NOT merged into origin/$BASE_BRANCH"
            return 1
        fi
    done < <(dependency_refs "$body")
    [ "$found" = true ] || echo "   Dependency gate: no declared dependencies"
}

claim_issue() {
    local number="$1" count
    if [ "$SELECTED_ASSIGNED" = true ]; then
        echo -e "${YELLOW}›${NC} Resuming issue #$number"
        return 0
    fi
    gh issue edit "$number" --add-assignee @me >/dev/null
    count="$(gh issue view "$number" --json assignees --jq '.assignees | length')"
    if ! [[ "$count" =~ ^[0-9]+$ ]] || [ "$count" -ne 1 ]; then
        gh issue edit "$number" --remove-assignee @me >/dev/null 2>&1 || true
        echo "claim race or verification failure for issue #$number" >&2
        return 1
    fi
}

worktree_has_work() {
    local start_sha="$1"
    [ -n "$(git status --porcelain)" ] || [ "$(git rev-parse HEAD)" != "$start_sha" ]
}

run_bounded_hook() {
    local phase="$1" command="$2" timeout_seconds="$3" log_file="$4"
    local max_bytes=$((LOG_MAX_KB * 1024)) status=0
    echo -e "${BLUE}▸${NC} $phase"
    # Bound the captured log to its trailing LOG_MAX_KB with `tail -c`, NOT with a
    # process-wide `ulimit -f`: that rlimit is inherited by the worker and every hook
    # and would SIGXFSZ-kill (and truncate) any repo file they legitimately write
    # (lockfiles, build artifacts, generated code). `tail` drains all input, so the
    # hook is never signalled; keeping the tail preserves the failing output and any
    # capacity/overload marker the retry logic greps for; PIPESTATUS[0] keeps the
    # hook's real exit status.
    (
        set +e
        timeout --signal=TERM --kill-after=15 "${timeout_seconds}s" bash -lc "$command" 2>&1 \
            | tail -c "$max_bytes"
        exit "${PIPESTATUS[0]}"
    ) >"$log_file" 2>&1 || status=$?
    if [ "$status" -ne 0 ]; then
        echo -e "${RED}✗${NC} $phase failed (exit $status); bounded tail follows:" >&2
        tail -n "$OUTPUT_MAX_LINES" "$log_file" >&2 || true
    else
        echo -e "${GREEN}✓${NC} $phase"
    fi
    return "$status"
}

worker_command() {
    local model="$1"
    if [ -n "$WORKER_HOOK" ]; then
        printf '%s' "$WORKER_HOOK"
        return
    fi
    local command="codex exec --dangerously-bypass-approvals-and-sandbox -C \"\$AGENT_LOOP_WORKTREE\""
    [ -n "$model" ] && command+=" -m '$model'"
    command+=" \"\$AGENT_LOOP_PROMPT\""
    printf '%s' "$command"
}

run_worker() {
    local start_sha="$1" attempt=0 model="$WORKER_MODEL" status log command retry
    while [ "$attempt" -le "$WORKER_RETRIES" ]; do
        attempt=$((attempt + 1))
        log="$AGENT_LOOP_LOG_DIR/worker-attempt-$attempt.log"
        command="$(worker_command "$model")"
        status=0
        run_bounded_hook "worker attempt $attempt" "$command" "$WORKER_TIMEOUT_SECONDS" "$log" || status=$?
        [ "$status" -eq 0 ] && return 0

        if worktree_has_work "$start_sha"; then
            recovery_message "Worker exited $status after changing or committing work."
            return "$status"
        fi

        retry=false
        if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then
            [ "$RETRY_ON_TIMEOUT" = true ] && retry=true
        elif grep -Eqi 'capacity|overloaded|rate.?limit|temporarily unavailable|resource exhausted' "$log"; then
            retry=true
            [ -n "$WORKER_FALLBACK_MODEL" ] && model="$WORKER_FALLBACK_MODEL"
        fi
        if [ "$retry" != true ] || [ "$attempt" -gt "$WORKER_RETRIES" ]; then
            recovery_message "Worker exited $status without recoverable retry conditions."
            return "$status"
        fi
        echo -e "${YELLOW}›${NC} Retrying worker after bounded capacity/timeout failure (model: ${model:-default})"
        [ "$RETRY_DELAY_SECONDS" -gt 0 ] && sleep "$RETRY_DELAY_SECONDS"
    done
}

require_clean_committed_tree() {
    local phase="$1" start_sha="$2"
    if [ -n "$(git status --porcelain)" ]; then
        recovery_message "$phase left a dirty worktree."
        return 1
    fi
    if [ "$(git rev-parse HEAD)" = "$start_sha" ]; then
        recovery_message "$phase produced no local commit."
        return 1
    fi
}

run_validation() {
    local label="$1"
    [ -z "$VALIDATION_HOOK" ] && return 0
    run_bounded_hook "$label validation" "$VALIDATION_HOOK" "$HOOK_TIMEOUT_SECONDS" \
        "$AGENT_LOOP_LOG_DIR/${label// /-}-validation.log"
}

inspect_publication_diff() {
    local file_count
    # This function is called in an `||` context, so `set -e` is disabled in its
    # body; check the gate explicitly or its non-zero exit (conflict markers left in
    # a committed file, whitespace errors) is silently ignored and publication
    # proceeds with a corrupt diff.
    if ! git diff --check "origin/$BASE_BRANCH..HEAD"; then
        echo "publication diff contains conflict markers or whitespace errors" >&2
        return 1
    fi
    file_count="$(git diff --name-only "origin/$BASE_BRANCH..HEAD" | wc -l | tr -d ' ')"
    [ "$file_count" -gt 0 ] || { echo "publication diff is empty" >&2; return 1; }
    echo "   Publication diff: $file_count file(s)"
    git diff --stat "origin/$BASE_BRANCH..HEAD" | tail -n "$OUTPUT_MAX_LINES"
}

publish_issue() {
    local number="$1" branch="$2" body_file pr_url
    git push --set-upstream origin "$branch"
    body_file="$AGENT_LOOP_LOG_DIR/pr-body.md"
    # Report only the steps that actually ran. Claude review, Codex review, and
    # fresh-base integration are unconditional; setup and validation are optional
    # hooks (run_validation no-ops when unset), so claiming them unconditionally
    # over-states verification exactly when a consumer hasn't wired them up.
    {
        echo "## Summary"
        echo
        echo "Local worker implementation passed local Claude deep review, local Codex"
        echo "review against fresh \`origin/$BASE_BRANCH\`, and fresh-base integration."
        echo
        echo "## Test plan"
        echo
        if [ -n "$SETUP_HOOK" ]; then echo "- [x] isolated dependency bootstrap"; fi
        echo "- [x] local Claude deep grill"
        echo "- [x] local Codex review against fresh \`origin/$BASE_BRANCH\`"
        echo "- [x] fresh-base integration and publication-diff inspection"
        if [ -n "$VALIDATION_HOOK" ]; then echo "- [x] configured local validation hook"; fi
        echo
        echo "Closes #$number"
    } > "$body_file"
    pr_url="$(gh pr create --base "$BASE_BRANCH" --head "$branch" \
        --title "agent-loop: resolve #$number" --body-file "$body_file")"
    echo -e "${GREEN}✓${NC} Published $pr_url"
}

echo -e "${CYAN}→${NC} agent-loop repository: $PROJECT_DIR"
echo "   Base: origin/$BASE_BRANCH"
if [ -n "$ISSUE_ALLOWLIST" ]; then
    echo "   Selection: allowlist $ISSUE_ALLOWLIST"
else
    echo "   Selection: ready queue"
fi
echo "   Dependency gate: $DEPENDENCY_GATE"
echo "   Dry run: $DRY_RUN"
echo "   Hooks:"
echo "     setup: ${SETUP_HOOK:-<none>}"
echo "     validation: ${VALIDATION_HOOK:-<none>}"
echo "     Claude review: $CLAUDE_REVIEW_HOOK"
echo "     Codex review: $CODEX_REVIEW_HOOK"

ITERATION=0
while [ "$ITERATION" -lt "$MAX_ITERATIONS" ]; do
    select_status=0
    select_next_issue || select_status=$?
    if [ "$select_status" -eq 2 ]; then
        echo "issue selection failed" >&2
        exit 1
    fi
    [ "$select_status" -eq 0 ] || break

    PROCESSED_ISSUES+=("$SELECTED_ID")
    ITERATION=$((ITERATION + 1))
    branch="$BRANCH_PREFIX/issue-$SELECTED_ID-$RUN_TAG"
    safe_repo="${REPO_NAME//[^A-Za-z0-9._-]/-}"
    ACTIVE_WORKTREE="$WORKTREE_ROOT/$safe_repo-issue-$SELECTED_ID-$RUN_TAG"
    proposed_log_dir="$LOG_ROOT/$safe_repo-issue-$SELECTED_ID-$RUN_TAG"

    echo -e "${CYAN}▶${NC} Issue #$SELECTED_ID ($ITERATION/$MAX_ITERATIONS)"
    if ! check_dependencies "$SELECTED_BODY"; then
        echo -e "${YELLOW}○${NC} Issue #$SELECTED_ID blocked by dependency gate"
        ACTIVE_WORKTREE=""
        continue
    fi
    echo "   Worktree: $ACTIVE_WORKTREE"
    echo "   Branch: $branch"
    echo "   Setup hook: ${SETUP_HOOK:-<none>}"
    echo "   Review order: Claude deep review -> Codex review"
    echo "   Publication: push $branch; PR base $BASE_BRANCH"

    if [ "$DRY_RUN" = true ]; then
        echo -e "${GREEN}✓${NC} Dry-run only: no claim, worktree, hook, push, or PR mutation"
        ACTIVE_WORKTREE=""
        continue
    fi

    claim_issue "$SELECTED_ID" || {
        echo -e "${YELLOW}○${NC} Issue #$SELECTED_ID could not be claimed; skipping"
        ACTIVE_WORKTREE=""
        continue
    }
    mkdir -p "$WORKTREE_ROOT" "$proposed_log_dir"
    AGENT_LOOP_LOG_DIR="$proposed_log_dir"
    # Never let the issue branch inherit origin/<base> as its upstream. With
    # push.default=upstream, a bare `git push` from a worker/reviewer would
    # otherwise target the integration branch and bypass local review.
    git worktree add --no-track -b "$branch" "$ACTIVE_WORKTREE" "origin/$BASE_BRANCH"
    cd "$ACTIVE_WORKTREE"

    export AGENT_LOOP_ISSUE_ID="$SELECTED_ID"
    export AGENT_LOOP_BASE_BRANCH="$BASE_BRANCH"
    export AGENT_LOOP_BRANCH="$branch"
    export AGENT_LOOP_WORKTREE="$ACTIVE_WORKTREE"
    export AGENT_LOOP_LOG_DIR
    export AGENT_LOOP_PROMPT="${PROMPT_TEMPLATE//\{ISSUE_ID\}/$SELECTED_ID}"

    start_sha="$(git rev-parse HEAD)"
    if [ -n "$SETUP_HOOK" ]; then
        run_bounded_hook "isolated dependency bootstrap" "$SETUP_HOOK" "$HOOK_TIMEOUT_SECONDS" "$AGENT_LOOP_LOG_DIR/setup.log" || {
            recovery_message "Setup hook failed."
            exit 1
        }
        [ -z "$(git status --porcelain)" ] || { recovery_message "Setup hook dirtied tracked files."; exit 1; }
    fi

    run_worker "$start_sha" || exit 1
    require_clean_committed_tree "Worker" "$start_sha" || exit 1
    run_validation "worker" || { recovery_message "Worker validation failed."; exit 1; }

    git fetch origin "$BASE_BRANCH" --quiet
    export AGENT_LOOP_REVIEW_BASE="origin/$BASE_BRANCH"
    run_bounded_hook "fresh local Claude deep grill" "$CLAUDE_REVIEW_HOOK" "$HOOK_TIMEOUT_SECONDS" "$AGENT_LOOP_LOG_DIR/claude-review.log" || {
        recovery_message "Claude review hook failed."
        exit 1
    }
    [ -z "$(git status --porcelain)" ] || { recovery_message "Claude review left uncommitted findings/fixes."; exit 1; }
    run_validation "claude-review" || { recovery_message "Validation after Claude review failed."; exit 1; }

    git fetch origin "$BASE_BRANCH" --quiet
    run_bounded_hook "local Codex review against origin/$BASE_BRANCH" "$CODEX_REVIEW_HOOK" "$HOOK_TIMEOUT_SECONDS" "$AGENT_LOOP_LOG_DIR/codex-review.log" || {
        recovery_message "Codex review hook failed."
        exit 1
    }
    [ -z "$(git status --porcelain)" ] || { recovery_message "Codex review left uncommitted findings/fixes."; exit 1; }
    run_validation "codex-review" || { recovery_message "Validation after Codex review failed."; exit 1; }

    echo -e "${BLUE}▸${NC} Fresh-base integration"
    git fetch origin "$BASE_BRANCH" --quiet
    if ! git merge --no-edit "origin/$BASE_BRANCH"; then
        git merge --abort >/dev/null 2>&1 || true
        recovery_message "Fresh-base merge conflicted; original commits were preserved."
        exit 1
    fi
    inspect_publication_diff || { recovery_message "Fresh-base publication diff inspection failed."; exit 1; }
    run_validation "fresh-base" || { recovery_message "Fresh-base validation failed."; exit 1; }
    [ -z "$(git status --porcelain)" ] || { recovery_message "Fresh-base validation dirtied the worktree."; exit 1; }

    if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
        recovery_message "Remote branch existed before wrapper publication; a worker or hook may have pushed."
        exit 1
    fi
    publish_issue "$SELECTED_ID" "$branch"

    cd "$PROJECT_DIR"
    git worktree remove "$ACTIVE_WORKTREE"
    echo -e "${GREEN}✓${NC} Issue #$SELECTED_ID complete; local branch retained at $branch"
    ACTIVE_WORKTREE=""
done

if [ "$ITERATION" -eq 0 ]; then
    echo -e "${DIM}○${NC} No selectable issues."
fi
echo -e "${GREEN}■${NC} agent-loop finished after $ITERATION issue(s)"
