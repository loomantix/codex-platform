# codex-platform

Reusable Codex skills, workflow prompts, and a sync engine for propagating agent tooling into consumer repos. Apache 2.0 + DCO.

> **Status:** v0.1. The Codex surface is young, but the repository is structured for public use: Apache 2.0, DCO, public-safe docs, and review-gated sync tooling.

## What's in here

### Codex skills (`.codex/skills/`)

Operational skills you can install globally or sync into any repo:

| Skill                 | What it does                                                                                                                                                                                                                                                                     |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `refactorpass`        | Pre-push cleanup pass for local source changes; runs simplicity/DRY, correctness-preserving, and convention/API cleanup lanes.                                                                                                                                                   |
| `grill`               | Pre-push adversarial review. Lean mode runs code-reviewer + silent-failure-hunter lanes; deep mode runs the full six-lane matrix.                                                                                                                                                |
| `deepgrill`           | Orchestrates refactorpass plus `grill deep`; uses independent reviewers when the active Codex runtime permits delegation.                                                                                                                                                        |
| `reviewit <pr>`       | Post-push AI review orchestrator for Gemini Flash + Copilot. Lean default caps at 2 iterations. `deep` arg bumps the cap to 4, early-exits when an iteration produces no `fix` resolutions, and ends with a final `deepgrill` so fresh subagents look at the PR's current state. |
| `copilot-review <pr>` | Address GitHub Copilot review comments systematically.                                                                                                                                                                                                                           |
| `feature-dev`         | Guided feature development: discovery, architecture, implementation, validation.                                                                                                                                                                                                 |
| `issues`              | Thin workflow over `gh issue` with a dependency-aware ready queue. Parses `Blocked by #N` / `Depends on #N` from issue bodies.                                                                                                                                                   |
| `agent-loop`          | Experimental Codex relay over the issue ready queue using `codex exec`.                                                                                                                                                                                                          |
| `task-packet`         | Execute a markdown Task Packet end-to-end.                                                                                                                                                                                                                                       |
| `phone-install`       | Build a release APK from the consumer repo and install it on a tethered Android device over wireless ADB.                                                                                                                                                                        |

### Codex references (`.codex/references/`)

Longer role prompts live as references instead of always-loaded instructions:

- `roles/code-explorer.md`
- `roles/code-architect.md`
- `roles/code-reviewer.md`
- `roles/silent-failure-hunter.md`
- `roles/type-design-analyzer.md`
- `roles/comment-analyzer.md`
- `roles/pr-test-analyzer.md`
- `roles/security-reviewer.md`

Skills can load these when they need a specialized review, exploration, or architecture stance.

### Sync engine (`scripts/`)

The sync engine is intentionally agent-agnostic:

- `sync-engine.py` reads upstream `scripts/sync-targets.yml` plus consumer `.platform-config.yml`, applies `<<KEY>>` substitutions, writes or deletes destination files, and supports `create_if_missing`.
- `create-signed-commit.py` creates sync commits through the GitHub Contents API so GitHub can mark them verified when run with a GitHub App token.
- `.github/workflows/sync-from-upstream.yml.template` is the consumer-side workflow template.

## Install

```bash
git clone https://github.com/loomantix/codex-platform.git
cd codex-platform
./scripts/install-skills.sh           # symlink skills into ~/.codex/skills/
./scripts/install-skills.sh --dry-run # report what would happen
./scripts/install-skills.sh --force   # replace existing entries after backup
```

Updates flow through `git pull` in this checkout. Existing symlinks pick up edits automatically.

## Wire Up A Consumer Repo

1. Add `.platform-config.yml` at the consumer root with template substitutions.
2. Copy `.github/workflows/sync-from-upstream.yml.template` to `.github/workflows/sync-from-upstream.yml`.
3. Fill in `UPSTREAM_REPO`, branch, and secret names.
4. Set the GitHub App secrets on the consumer.
5. Run `gh workflow run "Sync from upstream" --repo <owner>/<consumer>`.
6. Reference `.codex/REVIEW_WORKFLOW.md` from the consumer `AGENTS.md` if you want every Codex session to follow the same review chain.

## Design Notes

This repo keeps the durable parts of the old platform model: GitHub issue queue helpers, review automation, Copilot/Gemini plumbing, and tag-gated sync PRs. The agent-facing layer is Codex-specific: `AGENTS.md`, `.codex/skills`, `codex exec`, and concise skill bodies with optional references.

## License

Apache 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
