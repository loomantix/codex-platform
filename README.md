# codex-platform

Reusable Codex skills, workflow prompts, and a sync engine for propagating agent tooling into consumer repos. Apache 2.0 + DCO.

> **Status:** private v0.1 bootstrap. This repo is intentionally private while the Codex surface is hardened, but it is licensed Apache 2.0 so it can be opened later without a license migration.

## What's in here

### Codex skills (`.codex/skills/`)

Operational skills you can install globally or sync into any repo:

| Skill                  | What it does                                                                                                                  |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `refactorpass`         | Pre-push cleanup pass for local source changes; skips docs/config-only changesets.                                            |
| `grill`                | Pre-push adversarial review. Lean default uses high-signal review roles; deep mode broadens the checklist.                    |
| `deepgrill`            | Orchestrates the deep pre-push review chain.                                                                                  |
| `reviewit <pr>`        | Post-push AI review orchestrator for Gemini Flash + Copilot, with deduping, fixes, replies, and iteration caps.              |
| `copilot-review <pr>`  | Address GitHub Copilot review comments systematically.                                                                        |
| `feature-dev`          | Guided feature development: discovery, architecture, implementation, validation.                                              |
| `issues`               | Thin workflow over `gh issue` with a dependency-aware ready queue. Parses `Blocked by #N` / `Depends on #N` from issue bodies. |
| `agent-loop`           | Experimental Codex relay over the issue ready queue using `codex exec`.                                                       |
| `task-packet`          | Execute a markdown Task Packet end-to-end.                                                                                    |
| `phone-install`        | Build a release APK from the consumer repo and install it on a tethered Android device over wireless ADB.                    |

### Codex references (`.codex/references/`)

Longer role prompts live as references instead of always-loaded instructions:

- `roles/code-explorer.md`
- `roles/code-architect.md`
- `roles/code-reviewer.md`

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
