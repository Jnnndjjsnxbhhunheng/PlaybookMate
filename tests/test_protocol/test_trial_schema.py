"""Tests for the trials.jsonl schema and TrialLog."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from praxis.protocol.trial_schema import (
    FeedbackSource,
    PolicyDiff,
    ResourceUsage,
    ScoreSnapshot,
    TrialLog,
    TrialOutcome,
    TrialRecord,
)


def make_record(trial_idx: int = 0, outcome: TrialOutcome = TrialOutcome.IMPROVED) -> TrialRecord:
    return TrialRecord(
        hs_id="test_hs",
        run_id="test_hs/1234_5678",
        trial_idx=trial_idx,
        trigger=FeedbackSource.MANUAL,
        outcome=outcome,
        score=ScoreSnapshot(primary=0.85, previous_best=0.80),
        resources=ResourceUsage(wall_seconds=42.0, llm_input_tokens=1000, llm_output_tokens=500),
    )


def test_round_trip_jsonl() -> None:
    r = make_record()
    line = r.to_jsonl_line()
    parsed = json.loads(line)
    assert parsed["hs_id"] == "test_hs"
    assert parsed["score"]["primary"] == 0.85
    assert parsed["outcome"] == "improved"


def test_score_delta() -> None:
    r = make_record()
    assert abs(r.score.delta - 0.05) < 1e-9


def test_note_truncation() -> None:
    data = make_record().model_dump()
    data["agent_note"] = "x" * 600
    r2 = TrialRecord.model_validate(data)
    assert len(r2.agent_note) == 500


def test_trial_log_append_and_read() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log = TrialLog(str(Path(tmp) / "trials.jsonl"))
        assert log.read_all() == []
        assert log.best_score() is None

        log.append(make_record(0, TrialOutcome.IMPROVED))
        log.append(make_record(1, TrialOutcome.NEUTRAL))
        log.append(make_record(2, TrialOutcome.IMPROVED))

        records = log.read_all()
        assert len(records) == 3
        assert log.best_score() == 0.85
        assert log.next_trial_idx() == 3
