"""
Pattern Miner — cross-HS analysis of trials.jsonl files.

Extracts two kinds of patterns:
  - SuccessPattern: policy change types that reliably produce IMPROVED outcomes
  - AntiPattern: change types that repeatedly produce REGRESSED or FAILED outcomes

These patterns are stored in knowledge/ontology/ as YAML and injected into
future prompts via MetaPrompt.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

import yaml

from ..protocol.trial_schema import TrialLog, TrialOutcome


class Pattern(NamedTuple):
    domain: str
    description: str           # extracted from policy_diff.description
    occurrences: int
    avg_score_delta: float
    hs_ids: list[str]          # which HSes contributed this pattern


class MinerResult(NamedTuple):
    success_patterns: list[Pattern]
    anti_patterns: list[Pattern]


class PatternMiner:
    """
    Runs after each promotion cycle to refresh the knowledge base.

    The current implementation uses lightweight text clustering on
    policy_diff.description fields. A production upgrade would use
    embedding similarity — but description-level matching is enough
    to bootstrap and avoids an external embedding dependency.
    """

    def __init__(self, runs_root: Path, ontology_dir: Path) -> None:
        self._runs_root = runs_root
        self._ontology_dir = ontology_dir
        self._ontology_dir.mkdir(parents=True, exist_ok=True)

    def mine_all(self) -> MinerResult:
        """Scan all HS workspaces and update ontology files."""
        success: dict[str, dict] = defaultdict(
            lambda: {"occurrences": 0, "total_delta": 0.0, "hs_ids": set(), "domain": ""}
        )
        anti: dict[str, dict] = defaultdict(
            lambda: {"occurrences": 0, "total_delta": 0.0, "hs_ids": set(), "domain": ""}
        )

        for hs_dir in sorted(self._runs_root.iterdir()):
            if not (hs_dir / "hs_config.yaml").exists():
                continue
            config_data = yaml.safe_load((hs_dir / "hs_config.yaml").read_text())
            domain = config_data.get("domain", "unknown")
            hs_id = hs_dir.name

            log = TrialLog(str(hs_dir / "trials.jsonl"))
            for record in log.read_all():
                if not record.policy_diff or not record.policy_diff.description:
                    continue
                key = self._normalize(record.policy_diff.description)
                delta = record.score.delta or 0.0

                if record.outcome == TrialOutcome.IMPROVED:
                    success[key]["occurrences"] += 1
                    success[key]["total_delta"] += delta
                    success[key]["hs_ids"].add(hs_id)
                    success[key]["domain"] = domain
                elif record.outcome in (TrialOutcome.REGRESSED, TrialOutcome.FAILED):
                    anti[key]["occurrences"] += 1
                    anti[key]["total_delta"] += delta
                    anti[key]["hs_ids"].add(hs_id)
                    anti[key]["domain"] = domain

        success_patterns = self._to_patterns(success, min_occurrences=2)
        anti_patterns = self._to_patterns(anti, min_occurrences=2)

        self._persist(success_patterns, "success_patterns.yaml")
        self._persist(anti_patterns, "anti_patterns.yaml")

        return MinerResult(success_patterns=success_patterns, anti_patterns=anti_patterns)

    def load(self) -> MinerResult:
        return MinerResult(
            success_patterns=self._load_file("success_patterns.yaml"),
            anti_patterns=self._load_file("anti_patterns.yaml"),
        )

    @staticmethod
    def _normalize(desc: str) -> str:
        """Coarse normalisation: lowercase, strip trailing punctuation."""
        return desc.lower().strip().rstrip(".")

    @staticmethod
    def _to_patterns(bucket: dict, min_occurrences: int) -> list[Pattern]:
        patterns = []
        for desc, data in bucket.items():
            if data["occurrences"] < min_occurrences:
                continue
            patterns.append(
                Pattern(
                    domain=data["domain"],
                    description=desc,
                    occurrences=data["occurrences"],
                    avg_score_delta=(
                        data["total_delta"] / data["occurrences"]
                        if data["occurrences"] > 0
                        else 0.0
                    ),
                    hs_ids=sorted(data["hs_ids"]),
                )
            )
        return sorted(patterns, key=lambda p: p.avg_score_delta, reverse=True)

    def _persist(self, patterns: list[Pattern], filename: str) -> None:
        data = [
            {
                "domain": p.domain,
                "description": p.description,
                "occurrences": p.occurrences,
                "avg_score_delta": round(p.avg_score_delta, 5),
                "hs_ids": p.hs_ids,
            }
            for p in patterns
        ]
        (self._ontology_dir / filename).write_text(
            yaml.dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _load_file(self, filename: str) -> list[Pattern]:
        path = self._ontology_dir / filename
        if not path.exists():
            return []
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        return [
            Pattern(
                domain=r["domain"],
                description=r["description"],
                occurrences=r["occurrences"],
                avg_score_delta=r["avg_score_delta"],
                hs_ids=r["hs_ids"],
            )
            for r in raw
        ]
