---
name: to-spec
description: "Turn the current conversation or a slice of PLAN.md into a spec for Fabro or GitHub Issues: no interview, just synthesis of what has already been decided."
disable-model-invocation: true
---

This skill takes the current conversation context and `PLAN.md` / `CLAUDE.md` and produces a self-contained vertical-slice spec (saved to `specs/<slug>.md` or `.fabro/plans/<slug>.md` and optionally published to GitHub Issues with `ready-for-agent`).

## Process

1. Read `PLAN.md` and `CLAUDE.md` to ensure all privacy rules (`~/invoice-private/` never read, `python3 scripts/leak_scan.py` required) and `needs-user` (`NU-*`) boundaries are respected.
2. Sketch out the highest-level test seam (`pytest` against redacted/synthetic fixtures; skip cleanly if private fixtures are absent).
3. Write the spec with sections: `Problem Statement`, `Solution`, `User Stories`, `Implementation Decisions`, `Testing & Privacy Gate Decisions` (`python3 scripts/leak_scan.py` + `pytest -q` + `ubs -q .`), and `Out of Scope`.
