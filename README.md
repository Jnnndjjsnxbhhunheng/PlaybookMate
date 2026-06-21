# Praxis

**Heuristic System OS** — maintain business strategy like code, and accumulate cross-domain knowledge across all heuristic systems.

## Core idea

Praxis extends Jiayi Guo's heuristic learning protocol from RL environments to real business systems. Three design decisions define it:

1. **Claude Code / Codex as execution kernel** — no custom agent runtime; Praxis is the OS layer around it.
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
`trials.jsonl`, doing the simplification phase, looping until a stop rule fires.

`praxis new-hs` writes an **`AGENTS.md`** (auto-read by Codex) and a
**`CLAUDE.md`** (auto-read by Claude Code) into the workspace. You then launch
the agent in that directory and get out of the way.

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

# 3. inspect what the agent produced, then promote
praxis status
praxis promote --hs customer_triage --env staging
```

`praxis run` refreshes AGENTS.md/CLAUDE.md with the latest Knowledge Layer hints,
then calls `os.execvp` — replacing itself with the agent process. Praxis exits;
the agent owns the terminal from that point on.

## Web UI — viewer + collaboration surface

```bash
praxis web   # opens http://localhost:8000
```

The web UI is **not** a driver. It is a shared workspace for two roles:

| Role | What they do |
|------|-------------|
| **Product Manager** | Creates HS via form, attaches requirement doc, submits feedback |
| **Algorithm Eng** | Adds regression cases, reads trial history, approves/rejects promotions |

The "终端" tab shows the exact command to run locally (`cd runs/X && codex`).
There is no "launch agent" button — the agent must be started interactively in a
local terminal so you can watch and intervene.

Every UI action maps to a CLI equivalent shown in the command bar at the top of
each HS detail page. The frontend and the CLI share the same `runs/` directory
as their only data store.

## Roles

```
PM  ──→  requirement.md / feedback_inbox/   (form submits)
Algo ──→  regression_set/                   (form submits)
         praxis run → cd runs/X && codex    (local terminal)
         approve / reject in web UI
```

## Directory layout

```
praxis/
├── kernel/              # Layer 2: MCP servers exposing business tools
│   ├── mcp_kpi/
│   ├── mcp_ab_platform/
│   ├── mcp_ticket/
│   └── mcp_release/
├── protocol/            # Layer 3: workspace, lifecycle, agent brief
│   ├── workspace.py
│   ├── trial_schema.py
│   ├── lifecycle.py
│   ├── agent_brief.py   # renders AGENTS.md / CLAUDE.md
│   └── prompt_templates/
├── knowledge/           # Layer 4: cross-HS learning
│   ├── pattern_miner.py
│   ├── meta_prompt.py
│   └── ontology/
├── web/                 # FastAPI backend + Tailwind frontend
│   ├── api.py
│   ├── templates/
│   └── static/
├── runs/                # runtime data (gitignored except schema)
└── cli/
    └── main.py
```

## File contract

Every HS workspace under `runs/{hs_id}/` must maintain:

| File | Purpose |
|------|---------|
| `AGENTS.md` / `CLAUDE.md` | self-drive brief (auto-written by Praxis, auto-read by agent) |
| `policy.py` or `rules.yaml` | current best policy |
| `trials.jsonl` | append-only trial log (see `protocol/trial_schema.py`) |
| `summary.csv` | per-trial KPI columns for quick plotting |
| `regression_set/` | golden cases that must not regress |
| `feedback_inbox/` | incoming business feedback (client complaints, KPI anomalies) |
| `requirement.md` | PM's requirement document |
| `README.md` | auto-maintained changelog by lifecycle FSM |

## The brief structure (AGENTS.md / CLAUDE.md)

Every agent brief follows Jiayi's four-part structure plus a knowledge section:

1. **Hard constraints** — resource budget, never delete regression cases, append-only logs
2. **Stop rules** — when to stop exploring and enter simplification phase
3. **Loop steps** — read state → hypothesis → edit policy.py → evaluate → log → repeat
4. **Output file contract** — exact filenames and formats the agent must produce
5. **MCP tools** — business tools available (KPI, A/B, tickets, releases)
6. **Knowledge hints** — patterns mined from previous HS runs via `praxis refresh`

Replacing the "environment" section (EnvPool → business MCP tools) is the only
customization needed per domain.

## CLI reference

```
praxis new-hs     --name X --domain Y   Create workspace, write AGENTS.md + CLAUDE.md
praxis run        --hs X                Refresh brief, hand terminal to codex/claude
praxis run        --hs X --print-brief  Print AGENTS.md + launch command, don't launch
praxis status     [--hs X]              Show phase / trials / best score
praxis promote    --hs X [--env Y]      Validate and promote best policy
praxis refresh                          Re-mine all HS logs, update Knowledge Layer
praxis web        [--port N]            Start web UI
praxis mcp-config                       Print MCP server config for Claude Code
```
