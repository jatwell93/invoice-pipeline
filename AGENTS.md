# AGENTS.md

Read [`CLAUDE.md`](CLAUDE.md) and [`PLAN.md`](PLAN.md) first — all privacy rules (`~/invoice-private/` never read/listed; `python3 scripts/leak_scan.py` required before any fixture or commit), `needs-user` (`NU-1..NU-16`) boundaries, and the **Software Factory Trial Context (Dual-Mode Protocol)** in `CLAUDE.md` apply to every agent session.

## Primary harness (Trial 1): CodeAF

After the pay-check-app CodeAF warm-up ([`../software-factory/tasks/codeaf-setup-and-paycheck-overtime.md`](../software-factory/tasks/codeaf-setup-and-paycheck-overtime.md)), run packaging slices with CodeAF:

```bash
export CODEAF_TELEMETRY=off
export CODEAF_MODEL_POOL=read
mkdir -p .scratch

# PlanDB worker + checker
codeaf do --dir . \
  --file specs/extract-and-ledger.md \
  --check "python3 scripts/leak_scan.py" \
  --check "pytest -q" \
  --check "ubs -q ." \
  --keep --json | tee .scratch/codeaf-extract-ledger-1.json

# Optional: /senior-dev frozen tree on a private task/<slug> branch
codeaf senior-dev --dir . \
  --file specs/extract-and-ledger.md \
  --verify-test "pytest -q" \
  --json | tee .scratch/codeaf-senior-dev-1.json
```

Log runs in `../software-factory/trials/codeaf.md` and the bake-off scorecard.

## Optional Fabro path (`to-spec` → `to-graph-viz` → `fabro run`)

Skills remain under `.agents/skills/` if you need a digraph run instead of CodeAF:

1. **`to-spec`** — turns a build step from `PLAN.md` §8 into a slice spec.
2. **`to-graph-viz`** — compiles `.fabro/plans/<slug>.md` and `.fabro/workflows/<slug>/`.
3. **`fabro run`** — implement → review+UBS → verify (`leak_scan.py` + pytest + `ubs -q .` + non-empty diff) → ship.

Prefer CodeAF for Trial 1; use Fabro only for comparison or if CodeAF is blocked.
