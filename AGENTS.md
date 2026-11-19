# AGENTS.md

Read [`CLAUDE.md`](CLAUDE.md) and [`PLAN.md`](PLAN.md) first — all privacy rules (`~/invoice-private/` never read/listed; `python3 scripts/leak_scan.py` required before any fixture or commit), `needs-user` (`NU-1..NU-15`) boundaries, and the **Software Factory Trial Context (Dual-Mode Protocol)** in `CLAUDE.md` apply to every agent session.

## Factory Pipeline (`to-spec` → `to-graph-viz` → `fabro run`)

1. **`to-spec`** (`.agents/skills/to-spec/SKILL.md`) — turns a build step from `PLAN.md` §8 into a slice spec.
2. **`to-graph-viz`** (`.agents/skills/to-graph-viz/SKILL.md`) — compiles `.fabro/plans/<slug>.md` and `.fabro/workflows/<slug>/` (`workflow.fabro`, `workflow.toml`, `verify.sh`, `ship.sh`).
3. **`fabro run`** — executes `implement → review+UBS → verify (leak_scan.py + pytest + ubs -q . + non-empty diff) → ship`.
