# AGENTS.md

Read [`CLAUDE.md`](CLAUDE.md) and [`PLAN.md`](PLAN.md) first — privacy rules (`~/invoice-private/` never read/listed; `python3 scripts/leak_scan.py` before fixtures/commits), `needs-user` (`NU-1..NU-16`), and the **Software Factory Trial Context** in `CLAUDE.md` apply to every session.

## Primary harness (Trial 1): CodeAF — lean Fusion-style loop

Operator-led stages (CodeAF Teams groups chats; **it does not enforce order**). You are the human coordinator.

| Stage | Role chat | Artifact | Gate before next |
|---|---|---|---|
| 1. Plan | **Planner** | `.scratch/extract-plan.md` | Operator OK |
| 2. Spec | **Planner** (same chat or Spec) | `.scratch/extract-spec.md` (acceptance tests + file list) | **Reviewer** plan/spec review |
| 3. Execute | **Implementer** | product diff only | Operator-run: `pytest -q`, `ubs -q .`, `git diff --check`, non-empty product diff; owner `leak_scan` |
| 4. Review | **Reviewer** | approve / changes-requested | If changes: one Implementer repair + re-gate |
| 5. Commit | **Operator** (not the agent) | local commit on trial branch | No push/merge in this trial |

- Start with `PLAN.md` §8 Step 1 (`extract`) only. `ledger` is a later run.
- Do **not** invent a Fusion board, mission cards, or digraph mid-task.
- **Merge agent:** not used on this first run. Operator merges the worktree when ready. Add a Merge chat later only if handoff friction shows up.

Project `.codeaf/config.json` requests tool approval; it is not a filesystem sandbox. Run product chats as user `devagent` (Layer 1 / NU-2).

Log runs in `../software-factory/trials/codeaf.md`.

## Context hygiene (important)

For CodeAF Trial 1, **do not read or follow**:

- `.fabro/` (Fabro project config — optional alternate harness)
- `.agents/skills/` (`to-spec`, `to-graph-viz` — Fabro path only)

Those exist for an optional Fabro comparison. Loading them wastes tokens and pulls the wrong workflow. Prefer `PLAN.md`, `CLAUDE.md`, this file, `pipeline/`, `scripts/`, and `.scratch/`.

## Optional Fabro path (only if operator explicitly asks)

1. `to-spec` → slice spec  
2. `to-graph-viz` → `.fabro/workflows/<slug>/`  
3. `fabro run` → implement → review+UBS → verify → ship  
