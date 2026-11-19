---
name: to-graph-viz
description: Turn a spec, plan, or the current conversation into a Fabro workflow — a digraph (.fabro) plus prompts and gate scripts under .fabro/workflows/<slug>/ — then validate it and hand back the `fabro run` command. Use after to-spec (or on any approved spec/plan) where you would otherwise ticket the work out; Fabro executes the graph with an implement → review+UBS → verify/fixup → ship pipeline.
disable-model-invocation: true
---

# To Graph Viz

Break a spec into a **Fabro workflow**: a Graphviz digraph that Fabro executes end-to-end — agent implementation, an independent review stage, a static **UBS** (ultimate-bug-scanner) check as a hard gate, a bounded fixup loop, and an optional ship step that branches, pushes, and opens a draft PR.

## Process

1. Read `PLAN.md` and `CLAUDE.md` (especially the non-negotiable privacy rules and `python3 scripts/leak_scan.py` gate).
2. Write `.fabro/plans/<slug>.md` (~100–200 lines) with the slice's problem statement, decisions, explicit constraints (`~/invoice-private/` off-limits, Decimal/cents only, no float), and acceptance criteria.
3. Emit `.fabro/workflows/<slug>/` (`workflow.fabro`, `workflow.toml`, `prompts/{implement,review,fixup}.md`, `verify.sh`, and `ship.sh` if git remote is configured).
4. Pin `shape=parallelogram` on every `script=` node and `goal_gate=true` on `verify`.
5. In `verify.sh`, always assert:
   - `git status --porcelain | grep .` (non-empty diff)
   - `python3 scripts/leak_scan.py` (privacy leak scan)
   - `pytest -q`
   - `ubs -q .`
6. Validate with `fabro validate .fabro/workflows/<slug>/workflow.fabro` and `bash -n` on scripts, then hand back:
   ```bash
   fabro run .fabro/workflows/<slug>/workflow.toml --goal-file .fabro/plans/<slug>.md -d
   ```
