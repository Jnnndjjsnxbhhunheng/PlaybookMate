"""
Orchestrator — spawns and monitors Claude Code instances per HS run.

Design: each run gets its own isolated run_dir; the orchestrator passes a
rendered prompt file and waits for the trial contract files to appear.
Multiple HS can run in parallel because they write to different directories.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from ..knowledge.meta_prompt import MetaPrompt
from .lifecycle import LifecycleFSM
from .trial_schema import TrialLog, TrialRecord
from .workspace import WorkspaceManager

# Claude Code binary — override via PRAXIS_CC_BIN env var
import os
CC_BIN = os.environ.get("PRAXIS_CC_BIN", "claude")


class RunResult:
    def __init__(self, run_dir: Path, trial: TrialRecord | None, error: str = "") -> None:
        self.run_dir = run_dir
        self.trial = trial
        self.error = error

    @property
    def success(self) -> bool:
        return self.trial is not None and not self.error


class Orchestrator:
    def __init__(
        self,
        workspace: WorkspaceManager | None = None,
        meta_prompt: MetaPrompt | None = None,
        on_trial_complete: Callable[[TrialRecord], None] | None = None,
    ) -> None:
        self._ws = workspace or WorkspaceManager()
        self._mp = meta_prompt or MetaPrompt()
        self._on_trial = on_trial_complete

    def run_hs(self, hs_id: str, *, dry_run: bool = False) -> RunResult:
        """
        Execute one trial cycle for an HS:
          1. Render prompt (including Knowledge Layer hints)
          2. Spawn Claude Code in an isolated run_dir
          3. Wait for trials.jsonl entry to appear
          4. Append to canonical HS log with updated cumulative counters
        """
        config = self._ws.load_config(hs_id)
        fsm = LifecycleFSM(hs_id, self._ws)
        hs_dir = self._ws.runs_root / hs_id
        run_dir = self._ws.new_run_dir(hs_id)

        # copy current policy into run_dir so agent has a starting point
        policy_src = hs_dir / "policy.py"
        if policy_src.exists():
            shutil.copy(policy_src, run_dir / "policy.py")

        # copy regression set
        reg_src = hs_dir / "regression_set"
        if reg_src.exists():
            shutil.copytree(reg_src, run_dir / "regression_set", dirs_exist_ok=True)

        # render prompt
        hints = self._mp.get_hints(config.domain, config.tags)
        phase_instruction = fsm.next_phase_instruction()
        prompt = self._render_prompt(
            hs_id=hs_id,
            config=config,
            run_dir=run_dir,
            phase_instruction=phase_instruction,
            hints=hints,
            best_score=fsm._log.best_score(),
            trial_idx=fsm._log.next_trial_idx(),
        )

        prompt_file = run_dir / "PROMPT.md"
        prompt_file.write_text(prompt, encoding="utf-8")

        if dry_run:
            return RunResult(run_dir=run_dir, trial=None, error="dry_run")

        # spawn Claude Code
        exit_code, stderr = self._spawn_claude_code(run_dir, config.budget_wall_seconds)

        # read the trial output the agent must have written
        trial_out = run_dir / "trial_output.json"
        if not trial_out.exists():
            return RunResult(
                run_dir=run_dir,
                trial=None,
                error=f"agent did not produce trial_output.json (exit={exit_code})\n{stderr}",
            )

        trial_data = json.loads(trial_out.read_text(encoding="utf-8"))
        # inject identity fields the agent does not set
        trial_data["hs_id"] = hs_id
        trial_data["run_id"] = run_dir.name
        trial_data["trial_idx"] = fsm._log.next_trial_idx()
        trial_data["injected_hints"] = hints

        record = TrialRecord.model_validate(trial_data)

        # update cumulative counters
        prev = fsm._log.cumulative_resources()
        r = record.resources
        r.cumulative_wall_seconds = prev.cumulative_wall_seconds + r.wall_seconds
        r.cumulative_llm_input_tokens = prev.cumulative_llm_input_tokens + r.llm_input_tokens
        r.cumulative_llm_output_tokens = (
            prev.cumulative_llm_output_tokens + r.llm_output_tokens
        )
        r.cumulative_tool_calls = prev.cumulative_tool_calls + r.tool_calls

        # append to canonical log
        TrialLog(str(hs_dir / "trials.jsonl")).append(record)

        # if improved, promote policy back to hs_dir
        from .trial_schema import TrialOutcome
        if record.outcome in (TrialOutcome.IMPROVED, TrialOutcome.SIMPLIFIED):
            new_policy = run_dir / "policy.py"
            if new_policy.exists():
                shutil.copy(new_policy, policy_src)
                self._append_readme_changelog(hs_dir, record)

        if self._on_trial:
            self._on_trial(record)

        return RunResult(run_dir=run_dir, trial=record)

    async def run_many(self, hs_ids: list[str], *, max_parallel: int = 4) -> list[RunResult]:
        """Run multiple HS concurrently, respecting max_parallel."""
        sem = asyncio.Semaphore(max_parallel)

        async def _run(hs_id: str) -> RunResult:
            async with sem:
                return await asyncio.to_thread(self.run_hs, hs_id)

        return list(await asyncio.gather(*[_run(h) for h in hs_ids]))

    def _spawn_claude_code(self, run_dir: Path, budget_seconds: int) -> tuple[int, str]:
        """Run Claude Code with the rendered prompt as stdin."""
        prompt_file = run_dir / "PROMPT.md"
        try:
            result = subprocess.run(
                [CC_BIN, "--print", str(prompt_file)],
                cwd=str(run_dir),
                capture_output=True,
                text=True,
                timeout=budget_seconds + 60,  # add buffer for startup
            )
            return result.returncode, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "timeout"
        except FileNotFoundError:
            return -1, f"Claude Code binary not found: {CC_BIN}"

    def _render_prompt(
        self,
        *,
        hs_id: str,
        config,
        run_dir: Path,
        phase_instruction: str,
        hints: list[str],
        best_score: float | None,
        trial_idx: int,
    ) -> str:
        hints_block = (
            "\n".join(f"- {h}" for h in hints) if hints else "(none yet)"
        )
        best_str = str(best_score) if best_score is not None else "N/A (first trial)"
        return f"""# Praxis Trial — {hs_id} — Trial #{trial_idx}

## 1 · Hard Constraints  ← READ FIRST, NEVER VIOLATE

- **Budget**: stop if wall time exceeds {config.budget_wall_seconds}s OR total LLM tokens exceed {config.budget_llm_tokens:,}.
- **Backward compatibility**: never delete cases from `regression_set/`. Only add new ones.
- **Output contract**: you MUST write `trial_output.json` before exiting (schema below).
- **No silent failures**: if a tool call fails, record it in `agent_note` and set outcome to `failed`.
- **Metric direction**: {"higher is better" if config.higher_is_better else "lower is better"} for `{config.primary_metric}`.

## 2 · Stop Rules

Stop exploring and write `trial_output.json` when ANY of the following:
- Wall time budget hit ({config.budget_wall_seconds}s).
- Token budget hit ({config.budget_llm_tokens:,} tokens).
- Score has not improved by more than {config.stagnation_threshold} in the last {config.stagnation_window} trials.
- You have completed the current phase instruction (see §3).

## 3 · Phase Instruction

**Current phase directive:**

> {phase_instruction}

## 4 · Output File Contract

Write `trial_output.json` in the run directory `{run_dir}` with exactly this schema:

```json
{{
  "trigger": "<regression|ab_test|kpi_alert|ticket|manual>",
  "trigger_ref": "<optional reference ID>",
  "phase": "<explore|simplify|regress>",
  "outcome": "<improved|regressed|neutral|failed|simplified>",
  "score": {{
    "primary": <float>,
    "secondary": {{}},
    "previous_best": {best_score!r}
  }},
  "regression_pass_count": <int>,
  "regression_fail_count": <int>,
  "regression_total": <int>,
  "resources": {{
    "wall_seconds": <float>,
    "llm_input_tokens": <int>,
    "llm_output_tokens": <int>,
    "tool_calls": <int>
  }},
  "policy_diff": {{
    "lines_before": <int>,
    "lines_after": <int>,
    "hunks": <int>,
    "description": "<one sentence>"
  }},
  "agent_note": "<max 500 chars>"
}}
```

## 5 · Knowledge Layer Hints

Patterns extracted from previous HS runs in the `{config.domain}` domain:

{hints_block}

---

## 6 · Domain Context

HS ID: `{hs_id}`
Domain: `{config.domain}`
Description: {config.description}
Current best score: {best_str}
Run directory: `{run_dir}`
Policy file: `policy.py` (already copied to run directory)
Regression set: `regression_set/`

Begin.
"""

    @staticmethod
    def _append_readme_changelog(hs_dir: Path, record: TrialRecord) -> None:
        readme = hs_dir / "README.md"
        if not readme.exists():
            return
        line = (
            f"- {record.timestamp.date()} — trial #{record.trial_idx} "
            f"**{record.outcome}** score={record.score.primary:.4f}"
        )
        if record.policy_diff:
            line += f" ({record.policy_diff.description})"
        content = readme.read_text(encoding="utf-8")
        content += line + "\n"
        readme.write_text(content, encoding="utf-8")
