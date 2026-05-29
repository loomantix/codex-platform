---
name: deepgrill
description: High-fidelity pre-push Codex review chain. Use for complex or high-risk changes such as auth, crypto, secrets, data migrations, GitHub Actions, sync tooling, .codex/skills, large refactors, or when the user asks for a deep review.
---

# Deep Grill

## Context Window Check

Run this check before anything else. `deepgrill` is the most cache-hungry skill in the chain — it runs `refactorpass` (cleanup matrix) and then `grill deep` (six independent review lanes). When subagents/delegation are available, the six lanes run in parallel, each inheriting cache state from this session; when subagents are not available the lanes run as six serial local passes against the same context. Either way, if the current Codex session has already been heavily used for feature implementation, the lanes start with sharply reduced working windows and the whole chain runs slower and more expensively.

Assess honestly:

- Has this session been writing/editing the feature about to be reviewed? Long conversation, many file edits, dense planning?
- Is the conversation about to brush against compaction territory?

If either is yes, stop and tell the user:

> Your context is heavy from the implementation work. Start a new Codex session and run `deepgrill` there. `deepgrill` spawns up to six review lanes and is the chain that benefits most from cache headroom. A fresh session makes the chain materially cheaper.

Do not proceed in the current session unless the user explicitly overrides.

## Chain

Run the full high-fidelity pre-push chain:

1. Execute the `refactorpass` workflow.
2. Execute the `grill` workflow in deep mode, including all six independent review lanes from the `grill` skill: code reviewer, silent failure hunter, type/API design analyzer, comment/docs analyzer, PR test analyzer, and security reviewer.
3. Stop before pushing unless the user explicitly asked you to push.

Deep grill is not a single generalized review. If the active Codex runtime permits subagents/delegation, use independent reviewers for the six lanes. If subagents are unavailable or not permitted, run six separate local passes and disclose the downgrade in the final output.

Invoking `deepgrill` is an explicit request to use independent subagents for the
six deep review lanes whenever the active runtime exposes subagent/delegation
tools. Do not require the user to separately say "use subagents" before spawning
those lane reviewers.

Every deep lane must use an adversarial stance: assume the diff contains
defects, search for the highest-impact failure modes first, and require code,
tests, or documented constraints to disprove each risk. Do not report guesses;
report only evidence-backed, actionable findings.

## Deep Triggers

Use this path when the change touches:

- `.codex/skills/**`, `scripts/sync*`, or `.github/workflows/**`
- authentication, authorization, crypto, secret handling, or sensitive data
- database schema, data shape, migrations, or serialization contracts
- more than roughly 20 files or 500 net lines
- an area with recurring incidents

## Handoff

When complete, tell the user:

```text
Deep pre-push review complete.
Review depth: <deep with independent subagents | deep local six-pass fallback>
Next:
  git push
  gh pr create --title "..." --body "..."
  reviewit <pr-number> deep

Run `reviewit <pr-number> deep` in a FRESH Codex session.
The current session has absorbed refactorpass output, six deep-grill review
lanes, and any fix commits — cache pressure is high. `reviewit deep` runs
up to four review iterations and a final deepgrill against the PR; each
step needs cache headroom. A fresh session for `reviewit deep` makes the
full chain materially cheaper.
```
