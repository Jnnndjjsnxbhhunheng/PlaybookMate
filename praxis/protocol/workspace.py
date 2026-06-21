"""
Workspace Manager — creates and validates the per-HS directory contract.

Each HS lives under runs/{hs_id}/ with a fixed layout. Run-level isolation
uses runs/{hs_id}/{timestamp}_{pid}/ so parallel agents never collide.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

RUNS_ROOT = Path(__file__).parent.parent.parent / "runs"

# Files that MUST exist before a run can be promoted
REQUIRED_FOR_PROMOTION = [
    "policy.py",
    "trials.jsonl",
    "regression_set",
    "README.md",
]


@dataclass
class HSConfig:
    hs_id: str
    domain: str               # e.g. "ticket_routing", "marketing_rules"
    description: str = ""
    primary_metric: str = "score"
    higher_is_better: bool = True
    # resource budget per run (agent is told to stop when hit)
    budget_wall_seconds: int = 3600
    budget_llm_tokens: int = 500_000
    # stop exploring when score improvement < this for N consecutive trials
    stagnation_threshold: float = 0.001
    stagnation_window: int = 5
    # simplification trigger: enter simplify phase after this many improvements
    simplify_after_n_improvements: int = 3
    # tags for Knowledge Layer routing
    tags: list[str] = field(default_factory=list)


class WorkspaceManager:
    def __init__(self, runs_root: Path = RUNS_ROOT) -> None:
        self.runs_root = runs_root

    def create(self, config: HSConfig) -> Path:
        """Initialise a new HS workspace. Idempotent."""
        ws = self.runs_root / config.hs_id
        ws.mkdir(parents=True, exist_ok=True)

        config_path = ws / "hs_config.yaml"
        if not config_path.exists():
            config_path.write_text(
                yaml.dump(
                    {
                        "hs_id": config.hs_id,
                        "domain": config.domain,
                        "description": config.description,
                        "primary_metric": config.primary_metric,
                        "higher_is_better": config.higher_is_better,
                        "budget_wall_seconds": config.budget_wall_seconds,
                        "budget_llm_tokens": config.budget_llm_tokens,
                        "stagnation_threshold": config.stagnation_threshold,
                        "stagnation_window": config.stagnation_window,
                        "simplify_after_n_improvements": config.simplify_after_n_improvements,
                        "tags": config.tags,
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

        # skeleton files
        for name in ("trials.jsonl", "summary.csv"):
            (ws / name).touch(exist_ok=True)

        for dirname in ("regression_set", "feedback_inbox"):
            (ws / dirname).mkdir(exist_ok=True)

        # seed README
        readme = ws / "README.md"
        if not readme.exists():
            readme.write_text(
                f"# HS: {config.hs_id}\n\n"
                f"Domain: `{config.domain}`\n\n"
                f"{config.description}\n\n"
                "## Changelog\n\n"
                f"- {datetime.utcnow().date()} — workspace created\n",
                encoding="utf-8",
            )

        # seed empty policy
        policy = ws / "policy.py"
        if not policy.exists():
            policy.write_text(
                '"""Initial policy — agent will populate this on first run."""\n\n\n'
                "def evaluate(case: dict) -> dict:\n"
                "    raise NotImplementedError\n",
                encoding="utf-8",
            )

        # write the self-driven agent brief (AGENTS.md for Codex, CLAUDE.md for Claude Code)
        self.write_agent_brief(config)

        return ws

    def write_agent_brief(self, config: HSConfig) -> None:
        """(Re)generate AGENTS.md + CLAUDE.md, injecting current knowledge-layer hints."""
        from ..protocol.agent_brief import write_briefs
        ws = self.runs_root / config.hs_id
        hints: list[str] = []
        try:
            from ..knowledge.meta_prompt import MetaPrompt
            hints = MetaPrompt(runs_root=self.runs_root).get_hints(config.domain, config.tags)
        except Exception:
            pass
        write_briefs(ws, config, hints)

    def load_config(self, hs_id: str) -> HSConfig:
        path = self.runs_root / hs_id / "hs_config.yaml"
        if not path.exists():
            raise FileNotFoundError(f"HS '{hs_id}' not found at {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return HSConfig(**data)

    def new_run_dir(self, hs_id: str) -> Path:
        """Create an isolated run directory and return its path."""
        ts = int(time.time())
        pid = os.getpid()
        run_dir = self.runs_root / hs_id / f"{ts}_{pid}"
        run_dir.mkdir(parents=True)
        return run_dir

    def validate_for_promotion(self, hs_id: str) -> list[str]:
        """Return list of missing items that block promotion. Empty = OK."""
        ws = self.runs_root / hs_id
        missing = []
        for name in REQUIRED_FOR_PROMOTION:
            target = ws / name
            if not target.exists():
                missing.append(name)
            elif name == "regression_set" and not any(target.iterdir()):
                missing.append("regression_set (empty — must have at least one case)")
        return missing

    def list_hs(self) -> list[str]:
        if not self.runs_root.exists():
            return []
        return [
            d.name
            for d in sorted(self.runs_root.iterdir())
            if d.is_dir() and (d / "hs_config.yaml").exists()
        ]
