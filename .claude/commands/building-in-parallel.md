---
description: Set up git worktrees and separate tmux sessions for parallel feature development
argument-hint: ["feature1, feature2, feature3"]
allowed-tools: Bash, Read
---

# Building in Parallel

Sets up isolated git worktrees with one dedicated tmux session per feature, so multiple features can be developed in parallel without shared views. Each session automatically launches Claude Code and primes it with codebase understanding.

## Variables

FEATURES: "feature1, feature2, feature3"

## Instructions

You are given a comma-separated list of feature names in `$FEATURES`. For each feature, you will create a git worktree on a new branch and a dedicated tmux session named `dev-<feature>`.

**Important conventions:**
- Branch name: `feat/<feature-name>`
- Worktree path: `../hyper-strategies-<feature-name>` (sibling directory to the main repo)
- Symlink `.env` from the main repo so secrets are shared
- Create `logs/` and `output/` directories (they are gitignored and won't exist in fresh worktrees)

## Workflow

1. **Parse features**: Split `$FEATURES` by comma, trim whitespace, and normalize names (lowercase, hyphens instead of spaces).

2. **Check prerequisites**:
   - Verify `.env` exists in the main repo at `/home/jsong407/hyper-strategies/.env` using Read.
   - Run `git worktree list` to see existing worktrees. Skip any feature that already has a worktree.

3. **Create worktrees**: For each feature that doesn't already exist, run:
   ```bash
   git worktree add ../hyper-strategies-<feature> -b feat/<feature>
   ```
   If the branch already exists (e.g. from a previous run), use:
   ```bash
   git worktree add ../hyper-strategies-<feature> feat/<feature>
   ```

4. **Set up each worktree**: For each newly created worktree, run:
   ```bash
   ln -sf /home/jsong407/hyper-strategies/.env ../hyper-strategies-<feature>/.env
   mkdir -p ../hyper-strategies-<feature>/logs ../hyper-strategies-<feature>/output
   ```

5. **Create tmux sessions**: Create one dedicated tmux session per feature:
   ```bash
   tmux new-session -d -s dev-<feature> -c /home/jsong407/hyper-strategies-<feature>
   ```
   - Skip if session `dev-<feature>` already exists.
   - Each session is independent — no shared views between features.

6. **Launch Claude Code and prime each session**: For each newly created tmux session, send keystrokes to start Claude Code and run /prime with three explore agents:
   ```bash
   tmux send-keys -t dev-<feature> 'cldy' Enter
   ```
   Wait a few seconds for Claude Code to initialize, then send the prompt:
   ```bash
   sleep 5
   tmux send-keys -t dev-<feature> 'use three explore agents to explore the project base with /prime' Enter
   ```
   - This launches Claude Code via the `cldy` alias in each session.
   - The prompt instructs Claude to use three explore agents to explore the project base with `/prime`.
   - Process each session sequentially — wait for `cldy` to start before sending the prompt.

7. **Verify**: Run `git worktree list` and `tmux list-sessions` to confirm everything is set up.

## Report

Output a summary table:

| Feature | Branch | Worktree Path | tmux Session | Claude Primed | Status |
|---------|--------|---------------|--------------|---------------|--------|
| ... | feat/... | ../hyper-strategies-... | dev-... | Yes / No | Created / Skipped |

Then remind the user:
- List all sessions: `tmux list-sessions`
- Attach to a feature: `tmux attach -t dev-<feature>`
- Detach from a session: `Ctrl-b d`
- Claude Code is already running with `/prime` in each session — attach to check progress
- When done, clean up: `tmux kill-session -t dev-<feature> && git worktree remove ../hyper-strategies-<feature>`
