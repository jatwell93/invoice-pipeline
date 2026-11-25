# AGENTS.md

Read [`CLAUDE.md`](CLAUDE.md) and [`PLAN.md`](PLAN.md) first — all privacy rules (`~/invoice-private/` never read/listed; `python3 scripts/leak_scan.py` required before any fixture or commit), `needs-user` (`NU-1..NU-16`) boundaries, and the **Software Factory Trial Context (Dual-Mode Protocol)** in `CLAUDE.md` apply to every agent session.

## Primary harness (Trial 1): CodeAF

Use the [CodeAF team runbook](../software-factory/trials/codeaf.md#trial-1-setup-invoice-pipeline-factory) after the pay-check-app warm-up. The project `.codeaf/config.json` requests approval for tool calls; it does not isolate the filesystem. Complete the privacy preflight before starting a chat for product work. Start with `extract`; run `ledger` separately after `extract` is proven.

Log runs in `../software-factory/trials/codeaf.md` and the bake-off scorecard.

## Optional Fabro path (`to-spec` → `to-graph-viz` → `fabro run`)

Skills remain under `.agents/skills/` if you need a digraph run instead of CodeAF:

1. **`to-spec`** — turns a build step from `PLAN.md` §8 into a slice spec.
2. **`to-graph-viz`** — compiles `.fabro/plans/<slug>.md` and `.fabro/workflows/<slug>/`.
3. **`fabro run`** — implement → review+UBS → verify (`leak_scan.py` + pytest + `ubs -q .` + non-empty diff) → ship.

Prefer CodeAF for Trial 1; use Fabro only for comparison or if CodeAF is blocked.
