"""
trials.jsonl schema — the single file contract that all HS workspaces share.

Every trial appended to trials.jsonl must conform to TrialRecord.
The schema is intentionally strict: the lifecycle FSM and Knowledge Layer
both depend on field presence to work correctly.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class TrialOutcome(StrEnum):
    IMPROVED = "improved"       # new best; policy promoted to candidate
    REGRESSED = "regressed"     # broke a regression case
    NEUTRAL = "neutral"         # change within noise band; no promotion
    FAILED = "failed"           # agent error, timeout, or contract violation
    SIMPLIFIED = "simplified"   # simplification pass; same score, fewer lines


class FeedbackSource(StrEnum):
    REGRESSION = "regression"   # automated regression suite
    AB_TEST = "ab_test"         # A/B experiment result
    KPI_ALERT = "kpi_alert"     # KPI monitoring anomaly
    TICKET = "ticket"           # human-escalated ticket
    MANUAL = "manual"           # manual eval / annotation


class ResourceUsage(BaseModel):
    wall_seconds: float
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    tool_calls: int = 0
    # cumulative totals since HS creation (auto-filled by Trial Recorder)
    cumulative_wall_seconds: float = 0.0
    cumulative_llm_input_tokens: int = 0
    cumulative_llm_output_tokens: int = 0
    cumulative_tool_calls: int = 0


class ScoreSnapshot(BaseModel):
    """Primary metric plus any secondary metrics for this trial."""
    primary: float
    secondary: dict[str, float] = Field(default_factory=dict)
    # previous best at time of trial (for delta computation)
    previous_best: float | None = None

    @property
    def delta(self) -> float | None:
        if self.previous_best is None:
            return None
        return self.primary - self.previous_best


class PolicyDiff(BaseModel):
    """Minimal record of what the agent changed in this trial."""
    lines_before: int
    lines_after: int
    hunks: int          # number of diff hunks; proxy for edit complexity
    # optional: a one-sentence agent self-description of the change
    description: str = ""


class TrialRecord(BaseModel):
    """One row in trials.jsonl."""

    # identity
    hs_id: str
    run_id: str                         # "{hs_id}/{ts}_{pid}"
    trial_idx: int                      # monotonically increasing within hs_id
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # what triggered this trial
    trigger: FeedbackSource
    trigger_ref: str = ""               # e.g. ticket ID, alert ID, regression case name

    # what the agent did
    policy_diff: PolicyDiff | None = None
    phase: str = "explore"              # "explore" | "simplify" | "regress"

    # results
    outcome: TrialOutcome
    score: ScoreSnapshot
    regression_pass_count: int = 0
    regression_fail_count: int = 0
    regression_total: int = 0

    # resource accounting (never optional — agent must always report)
    resources: ResourceUsage

    # free-form agent notes (limited to 500 chars to prevent bloat)
    agent_note: str = ""

    # Knowledge Layer: hints injected into the prompt for this trial
    injected_hints: list[str] = Field(default_factory=list)

    @field_validator("agent_note", mode="before")
    @classmethod
    def _note_length(cls, v: str) -> str:
        if isinstance(v, str) and len(v) > 500:
            return v[:497] + "..."
        return v

    def to_jsonl_line(self) -> str:
        import json
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False)


class TrialLog:
    """Append-only writer/reader for a single HS's trials.jsonl."""

    def __init__(self, path: str) -> None:
        self._path = path

    def append(self, record: TrialRecord) -> None:
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(record.to_jsonl_line() + "\n")

    def read_all(self) -> list[TrialRecord]:
        import json
        records: list[TrialRecord] = []
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(TrialRecord.model_validate(json.loads(line)))
        except FileNotFoundError:
            pass
        return records

    def best_score(self) -> float | None:
        scores = [
            r.score.primary
            for r in self.read_all()
            if r.outcome in (TrialOutcome.IMPROVED, TrialOutcome.SIMPLIFIED)
        ]
        return max(scores) if scores else None

    def cumulative_resources(self) -> ResourceUsage:
        records = self.read_all()
        if not records:
            return ResourceUsage(wall_seconds=0)
        last = records[-1].resources
        return ResourceUsage(
            wall_seconds=last.cumulative_wall_seconds,
            llm_input_tokens=last.cumulative_llm_input_tokens,
            llm_output_tokens=last.cumulative_llm_output_tokens,
            tool_calls=last.cumulative_tool_calls,
            cumulative_wall_seconds=last.cumulative_wall_seconds,
            cumulative_llm_input_tokens=last.cumulative_llm_input_tokens,
            cumulative_llm_output_tokens=last.cumulative_llm_output_tokens,
            cumulative_tool_calls=last.cumulative_tool_calls,
        )

    def next_trial_idx(self) -> int:
        records = self.read_all()
        return records[-1].trial_idx + 1 if records else 0
