---
name: context-loader
description: Assembles the context for a lane before code work starts — lane file, per-repo MEMORY.md, preferences, the repo's own CLAUDE.md, ticket text — and returns a compact brief. Use at the start of a coding session or when switching lanes.
tools: Read, Glob, Grep, Bash
model: sonnet
---
Given a lane id (or infer it from the cwd under lanes/<id>/), read in this order, all under the workspace's .repolane/:
1. registry/lanes/<id>.md
2. knowledge/preferences.md
3. For each repo in the lane: memory/<repo>/MEMORY.md, then only the memory files whose
   index line is relevant to the Goal; the repo's CLAUDE.md and .claude/rules/* in the worktree.
4. knowledge/domains/<name>.md if the lane file names one.
Do not read anything under .repolane/repos/ or other lanes. Do not read .env files.
Return a brief of at most 25 lines: goal, current state (from Resume note + git log -5 per worktree), the rules
that constrain this work, open questions. No file dumps.
