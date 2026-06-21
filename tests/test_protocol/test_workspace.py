"""Tests for WorkspaceManager."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from praxis.protocol.workspace import HSConfig, WorkspaceManager


def test_create_and_load() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wm = WorkspaceManager(runs_root=Path(tmp))
        config = HSConfig(hs_id="my_hs", domain="ticket_routing", description="test")
        path = wm.create(config)

        assert (path / "hs_config.yaml").exists()
        assert (path / "trials.jsonl").exists()
        assert (path / "regression_set").is_dir()
        assert (path / "feedback_inbox").is_dir()
        assert (path / "README.md").exists()
        assert (path / "policy.py").exists()

        loaded = wm.load_config("my_hs")
        assert loaded.hs_id == "my_hs"
        assert loaded.domain == "ticket_routing"


def test_create_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wm = WorkspaceManager(runs_root=Path(tmp))
        config = HSConfig(hs_id="hs2", domain="test")
        wm.create(config)
        wm.create(config)  # should not raise
        assert wm.list_hs() == ["hs2"]


def test_validate_for_promotion_missing_regression() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wm = WorkspaceManager(runs_root=Path(tmp))
        config = HSConfig(hs_id="hs3", domain="test")
        wm.create(config)
        # regression_set exists but is empty
        missing = wm.validate_for_promotion("hs3")
        assert any("regression_set" in m for m in missing)
