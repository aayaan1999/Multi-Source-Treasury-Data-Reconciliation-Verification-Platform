---
name: git-commit-push
description: Commit staged/unstaged changes and push them to the GitHub remote for this repo. Use when the user asks to "commit and push", "push this to github", "save my changes to github", or similar — for this repo (origin https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform), current branch main.
---

# Git commit and push

Commit the current changes and push them to GitHub.

## Steps

1. Run in parallel: `git status`, `git diff` (staged + unstaged), `git log --oneline -5`, and `git branch --show-current`.
2. Review the diff. Never stage files that look like secrets/credentials (`.env`, `*credentials*`, key files) — warn the user instead of committing them.
3. Stage relevant files by explicit name (avoid `git add -A`/`git add .` unless the user confirms everything untracked should go in).
4. Write a concise commit message (1-2 sentences, focused on *why*) following the style of recent commits (`git log`). Use a heredoc for the message.
5. Commit, then push to the current branch's remote (`git push`, or `git push -u origin <branch>` if it has no upstream yet).
6. Run `git status` after to confirm a clean tree and successful push.

## Notes

- This repo's remote is `origin` → `https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform`, default branch `main`.
- Only commit when the user has asked for it in this turn — do not commit proactively as a side effect of other work.
- Never force-push, never skip hooks (`--no-verify`), never amend an existing commit unless the user explicitly asks.
- If `git push` fails because the remote has new commits, run `git pull --rebase` (or ask the user how they want to resolve) rather than force-pushing.
- End commit messages with the attribution line already configured for this session (see system reminder), if present.
