# Praxis

**Heuristic System OS** — maintain business strategy like code, and accumulate cross-domain knowledge across all heuristic systems.

## Core idea

Praxis extends Jiayi Guo's heuristic learning protocol from RL environments to real business systems. Three design decisions define it:

1. **Claude Code as execution kernel** — no custom agent runtime; Praxis is the OS layer around it.
2. **File contract as the API** — every heuristic system shares the same `trials.jsonl` / `regression_set/` / `feedback_inbox/` schema; swapping the model is a one-line change.
3. **Knowledge Layer as the moat** — patterns extracted across all HS runs are injected into the prompt of every new HS, so the second system is always faster than the first.

## Layers

```
┌─────────────────────────────────────────────┐
│  Layer 4 · Knowledge Layer                  │  cross-HS pattern mining, meta-prompt
├─────────────────────────────────────────────┤
│  Layer 3 · Protocol & Orchestration         │  workspace, lifecycle FSM, templates
├─────────────────────────────────────────────┤
│  Layer 2 · Tool Adapter (MCP servers)       │  KPI, A/B platform, tickets, releases
├─────────────────────────────────────────────┤
│  Layer 1 · Execution Kernel (Claude Code)   │  file edit, shell, MCP client
└─────────────────────────────────────────────┘
```

## How it runs — the agent drives, not Praxis

Praxis does **not** call the LLM in a loop. Following Jiayi Guo's model, the
agent (Codex CLI or Claude Code) reads a brief and self-drives the entire
heuristic-learning loop — writing `policy.py`, running trials, appending
`trials.jsonl`, doing the simplification phase, looping until a stop rule.

`praxis new-hs` writes an **`AGENTS.md`** (auto-read by Codex) and a
**`CLAUDE.md`** (auto-read by Claude Code) into the workspace. You then just
launch the agent in that directory and get out of the way.

```bash
pip install -e ".[dev]"

# 1. create a workspace (writes AGENTS.md + CLAUDE.md with the full loop brief)
praxis new-hs --name customer_triage --domain ticket_routing

# 2. launch the agent — it self-drives the whole loop
cd runs/customer_triage && codex          # or: claude
#   equivalently, Praxis hands the terminal over for you:
praxis run --hs customer_triage           # default agent via $PRAXIS_AGENT (codex)
praxis run --hs customer_triage --agent claude
praxis run --hs customer_triage --print-brief   # just show the brief + launch cmd

# 3. unattended batch — one headless agent per HS (Jiayi's Atari57 style)
praxis run-all --launch

# 4. inspect what the agent produced, then promote
praxis status
praxis promote --hs customer_triage --env staging
```

The web UI (`praxis web`) is a **viewer + collaboration surface**, not a
driver: PMs file requirements/feedback, algo engineers review trials and add
regression cases, and the "Agent Brief" tab shows the exact `AGENTS.md` plus
the `cd … && codex` command. Its "启动 Agent" button spawns a *headless*
background agent (`codex exec`) — still the agent driving its own loop.

## Directory layout

```
praxis/
├── kernel/              # Layer 2: MCP servers exposing business tools
│   ├── mcp_kpi/
│   ├── mcp_ab_platform/
│   ├── mcp_ticket/
│   └── mcp_release/
├── protocol/            # Layer 3: workspace, lifecycle, orchestrator
│   ├── workspace.py
│   ├── trial_schema.py
│   ├── lifecycle.py
│   ├── orchestrator.py
│   └── prompt_templates/
├── knowledge/           # Layer 4: cross-HS learning
│   ├── pattern_miner.py
│   ├── meta_prompt.py
│   └── ontology/
├── runs/                # runtime data (gitignored except schema)
└── cli/
    └── main.py
```

## File contract

Every HS workspace under `runs/{hs_id}/` must maintain:

| File | Purpose |
|------|---------|
| `policy.py` or `rules.yaml` | current best policy |
| `trials.jsonl` | append-only trial log (see `protocol/trial_schema.py`) |
| `summary.csv` | per-trial KPI columns for quick plotting |
| `regression_set/` | golden cases that must not regress |
| `feedback_inbox/` | incoming business feedback (client complaints, KPI anomalies) |
| `README.md` | auto-maintained changelog by lifecycle FSM |

## The four-part prompt structure

Every HS prompt template follows Jiayi's four-part structure:

1. **Hard constraints** — what the agent must never do (resource budget, backward compat)
2. **Stop rules** — when to stop exploring and enter simplification phase
3. **Simplification phase** — mandatory code-golf pass before promoting
4. **Output file contract** — exact filenames and formats the agent must produce

Replacing the "environment" section (EnvPool → business MCP tools) is the only customization needed per domain.
