"""
Lifecycle FSM for a single Heuristic System.

States:
    IDLE        → no active run
    EXPLORING   → agent is generating and testing policy changes
    SIMPLIFYING → mandatory code-golf pass after N improvements
    REGRESSING  → running full regression suite before promotion
    PROMOTING   → writing policy + updating README, tagging git
    BLOCKED     → promotion requirements not met; human review needed

Transitions are driven by TrialRecord outcomes written to trials.jsonl.
The FSM itself is stateless — it derives current state from the log every
time it's called, so crashes are safe and logs are the source of truth.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from .trial_schema import TrialLog, TrialOutcome
from .workspace import WorkspaceManager


class Phase(StrEnum):
    IDLE = "idle"
    EXPLORING = "exploring"
    SIMPLIFYING = "simplifying"
    REGRESSING = "regressing"
    PROMOTING = "promoting"
    BLOCKED = "blocked"


class LifecycleFSM:
    def __init__(self, hs_id: str, workspace: WorkspaceManager | None = None) -> None:
        self.hs_id = hs_id
        self._ws = workspace or WorkspaceManager()
        self._config = self._ws.load_config(hs_id)
        self._log = TrialLog(str(self._ws.runs_root / hs_id / "trials.jsonl"))

    def current_phase(self) -> Phase:
        records = self._log.read_all()
        if not records:
            return Phase.IDLE

        # count improvements since last simplification
        improvements_since_simplify = 0
        simplifications = 0
        for r in records:
            if r.outcome == TrialOutcome.IMPROVED:
                improvements_since_simplify += 1
            elif r.outcome == TrialOutcome.SIMPLIFIED:
                simplifications += 1
                improvements_since_simplify = 0

        # if last trial entered regress/promote phase, derive from that
        last = records[-1]
        if last.phase == "regress":
            if last.regression_fail_count > 0:
                return Phase.BLOCKED
            return Phase.PROMOTING
        if last.phase == "simplify":
            return Phase.SIMPLIFYING

        # check stagnation → trigger simplify
        if self._is_stagnating(records):
            return Phase.SIMPLIFYING

        # check improvement count → trigger simplify
        trigger = self._config.simplify_after_n_improvements
        if improvements_since_simplify >= trigger:
            return Phase.SIMPLIFYING

        return Phase.EXPLORING

    def _is_stagnating(self, records: list) -> bool:
        window = self._config.stagnation_window
        threshold = self._config.stagnation_threshold
        if len(records) < window:
            return False
        recent = records[-window:]
        scores = [r.score.primary for r in recent]
        return (max(scores) - min(scores)) < threshold

    def next_phase_instruction(self) -> str:
        """Return a short directive string the prompt template can embed."""
        phase = self.current_phase()
        match phase:
            case Phase.IDLE:
                return "Bootstrap the initial policy from scratch using available tools."
            case Phase.EXPLORING:
                best = self._log.best_score()
                return (
                    f"Continue exploring improvements. Current best: {best}. "
                    f"Stagnation window: {self._config.stagnation_window} trials, "
                    f"threshold: {self._config.stagnation_threshold}."
                )
            case Phase.SIMPLIFYING:
                return (
                    "ENTER SIMPLIFICATION PHASE. Score must not drop. "
                    "Reduce policy.py line count and cyclomatic complexity. "
                    "Remove dead branches, inline constants, merge conditions. "
                    "Record outcome as 'simplified'."
                )
            case Phase.REGRESSING:
                return (
                    "Run full regression suite in regression_set/. "
                    "All cases must pass before promotion is allowed."
                )
            case Phase.PROMOTING:
                return (
                    "All regressions pass. Update README.md changelog. "
                    "Tag the commit with the current score. "
                    "Signal promotion complete."
                )
            case Phase.BLOCKED:
                return (
                    "BLOCKED: regression failures detected. "
                    "Fix failing cases before promotion. "
                    "Do not skip or delete regression cases."
                )
        return ""

    def summary(self) -> dict:
        records = self._log.read_all()
        resources = self._log.cumulative_resources()
        return {
            "hs_id": self.hs_id,
            "phase": self.current_phase(),
            "total_trials": len(records),
            "best_score": self._log.best_score(),
            "cumulative_tokens": (
                resources.cumulative_llm_input_tokens
                + resources.cumulative_llm_output_tokens
            ),
            "cumulative_wall_seconds": resources.cumulative_wall_seconds,
        }
