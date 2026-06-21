"""
Agent brief generator — the prompt-first core of Praxis.

This writes the AGENTS.md (read automatically by Codex CLI) and CLAUDE.md
(read automatically by Claude Code) into a heuristic-system workspace.

Unlike a per-trial prompt, this brief instructs the agent to drive the
ENTIRE heuristic-learning loop by itself: write the policy, run trials,
append the log, do the simplification phase, and keep looping until the
stop rule fires. Praxis does not call the agent in a loop — the agent IS
the loop, exactly like Jiayi Guo's Codex runs.

Usage flow:
    praxis new-hs --name X ...      # writes AGENTS.md + CLAUDE.md here
    cd runs/X && codex              # agent reads AGENTS.md, self-drives
    # or
    cd runs/X && claude            # agent reads CLAUDE.md, self-drives
"""

from __future__ import annotations

from .workspace import HSConfig


def render_brief(config: HSConfig, hints: list[str] | None = None) -> str:
    """Render the full self-driven agent brief for a workspace."""
    hints = hints or []
    hints_block = "\n".join(f"- {h}" for h in hints) if hints else "_(none yet — this is an early HS)_"
    direction = "higher is better" if config.higher_is_better else "lower is better"

    return f"""# Heuristic System: `{config.hs_id}`

You are an autonomous engineer improving a business policy. **You drive the
entire loop yourself.** No external orchestrator will call you repeatedly —
you run trial after trial in this single session until a stop rule fires.

Domain: `{config.domain}`
Goal: optimise `{config.primary_metric}` ({direction}).

> {config.description}

---

## How you operate (the loop)

Repeat until a **Stop Rule** fires:

1. **Read state.** Look at `policy.py` (current best policy), `trials.jsonl`
   (full history), and `regression_set/` (cases that must keep passing).
2. **Form a hypothesis.** Decide one concrete change to `policy.py` that
   should improve `{config.primary_metric}`.
3. **Apply & evaluate.** Edit `policy.py`. Run it against `regression_set/`
   and any evaluation data available through your tools.
4. **Record the trial.** Append exactly one line to `trials.jsonl` (schema
   below). Update `summary.csv`. Keep cumulative resource counters accurate —
   never reset or omit them.
5. **Simplification phase (mandatory).** Every time you reach a new best
   score, OR after {config.simplify_after_n_improvements} consecutive
   improvements, STOP exploring and do a simplification pass: reduce
   `policy.py` line count and complexity **without dropping the score**.
   Record this trial with `"phase": "simplify"` and `"outcome": "simplified"`.
6. **Loop.** Go back to step 1.

You manage exploration order yourself (sequential or parallel hypotheses).

---

## 1 · Hard Constraints — NEVER VIOLATE

- **Budget.** Stop when wall time exceeds **{config.budget_wall_seconds}s** OR
  cumulative LLM tokens exceed **{config.budget_llm_tokens:,}**. All
  exploration, evaluation, and debugging counts toward the budget.
- **Backward compatibility.** Never delete or weaken cases in
  `regression_set/`. You may only add new ones.
- **No silent failure.** If a tool or evaluation fails, record the trial with
  `"outcome": "failed"` and explain in `agent_note`. Do not skip the log.
- **Append-only log.** `trials.jsonl` is append-only. Never rewrite history.

## 2 · Stop Rules — stop the whole session when ANY is true

- Wall-time budget hit ({config.budget_wall_seconds}s).
- Token budget hit ({config.budget_llm_tokens:,}).
- `{config.primary_metric}` has not improved by more than
  {config.stagnation_threshold} across the last {config.stagnation_window}
  trials (genuine plateau, not a single bad trial).

When you stop: finalise `policy.py` (simplified), update `README.md` with the
final score, total trials, total resources, and a short failure analysis.

## 3 · Output File Contract — you write all of these

| File | What you maintain |
|------|-------------------|
| `policy.py` | current best policy (a `def evaluate(case: dict) -> dict`) |
| `trials.jsonl` | append one line per trial — schema below |
| `summary.csv` | one row per trial: trial_idx, outcome, score, cum_tokens |
| `README.md` | final score, KNOWN_BEST if any, total steps, repro notes, failure analysis |

Each `trials.jsonl` line is exactly this JSON object:

```json
{{
  "trial_idx": 0,
  "trigger": "manual",
  "phase": "explore",
  "outcome": "improved",
  "score": {{"primary": 0.0, "secondary": {{}}, "previous_best": null}},
  "regression_pass_count": 0,
  "regression_fail_count": 0,
  "regression_total": 0,
  "resources": {{
    "wall_seconds": 0.0,
    "llm_input_tokens": 0,
    "llm_output_tokens": 0,
    "tool_calls": 0,
    "cumulative_wall_seconds": 0.0,
    "cumulative_llm_input_tokens": 0,
    "cumulative_llm_output_tokens": 0,
    "cumulative_tool_calls": 0
  }},
  "policy_diff": {{"lines_before": 0, "lines_after": 0, "hunks": 0, "description": "one sentence"}},
  "agent_note": "max 500 chars"
}}
```

- `trigger` ∈ explore-driven: use `manual`; or `regression` / `ab_test` /
  `kpi_alert` / `ticket` if you are acting on a `feedback_inbox/` item.
- `outcome` ∈ `improved` | `regressed` | `neutral` | `failed` | `simplified`.
- `cumulative_*` = previous line's cumulative + this trial's usage.

## 4 · Business tools (MCP)

If the following tools are configured, use them for real evaluation instead of
guessing. They are how this HS connects to the live business:

- ticket: `ticket_search`, `ticket_get`, `ticket_regression_cases`
- kpi: `kpi_get`, `kpi_compare`
- ab: `ab_create`, `ab_status`
- release: `release_deploy`, `release_status`, `release_rollback`

Run `praxis mcp-config` to see how these are registered. If none are
configured, evaluate against `regression_set/` only and say so in `agent_note`.

## 5 · Feedback inbox

Check `feedback_inbox/*.json` at the start. Each file is a product/algo
request or a complaint. Turn relevant ones into new trials and, if they
encode a must-hold behaviour, into new `regression_set/` cases.

## 6 · Knowledge from previous heuristic systems

Patterns mined across other HS in the `{config.domain}` domain. Treat
`[WORKS]` as priors to try first and `[AVOID]` as known dead ends:

{hints_block}

---

Begin now. Read the state, then start trial #{{next_idx}} and keep going until
a stop rule fires.
"""


def write_briefs(workspace_dir, config: HSConfig, hints: list[str] | None = None) -> None:
    """Write AGENTS.md (Codex) and CLAUDE.md (Claude Code) into the workspace."""
    from pathlib import Path

    ws = Path(workspace_dir)
    brief = render_brief(config, hints)
    # AGENTS.md is auto-read by Codex CLI; CLAUDE.md by Claude Code.
    (ws / "AGENTS.md").write_text(brief, encoding="utf-8")
    (ws / "CLAUDE.md").write_text(brief, encoding="utf-8")
