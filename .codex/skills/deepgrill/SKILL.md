---
name: deepgrill
description: High-fidelity pre-push Codex review chain. Use for complex or high-risk changes such as auth, crypto, secrets, data migrations, GitHub Actions, sync tooling, .codex/skills, large refactors, or when the user asks for a deep review.
---

# Deep Grill

Run the full high-fidelity pre-push chain:

1. Execute the `refactorpass` workflow.
2. Execute the `grill` workflow in deep mode, including all six independent review lanes from the `grill` skill: code reviewer, silent failure hunter, type/API design analyzer, comment/docs analyzer, PR test analyzer, and security reviewer.
3. Stop before pushing unless the user explicitly asked you to push.

Deep grill is not a single generalized review. If the active Codex runtime permits subagents/delegation, use independent reviewers for the six lanes. If subagents are unavailable or not permitted, run six separate local passes and disclose the downgrade in the final output.

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
```
