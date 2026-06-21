"""
MetaPrompt — decides which Knowledge Layer hints to inject into a new trial.

Selection logic:
  1. Load success and anti patterns from ontology/
  2. Filter by domain match (exact) or tag overlap
  3. Rank by avg_score_delta descending
  4. Return top-N as plain strings the Orchestrator embeds in the prompt

The selection strategy itself is a candidate for self-hosting: a future
iteration can treat "which hints to inject" as its own HS, letting Praxis
optimise its own meta-prompt strategy.
"""

from __future__ import annotations

from pathlib import Path

from .pattern_miner import PatternMiner

ONTOLOGY_DIR = Path(__file__).parent / "ontology"
MAX_HINTS = 8
MAX_ANTI_HINTS = 4


class MetaPrompt:
    def __init__(
        self,
        ontology_dir: Path = ONTOLOGY_DIR,
        runs_root: Path | None = None,
    ) -> None:
        self._miner = PatternMiner(
            runs_root=runs_root or Path(__file__).parent.parent.parent / "runs",
            ontology_dir=ontology_dir,
        )

    def get_hints(self, domain: str, tags: list[str] | None = None) -> list[str]:
        """Return hint strings for injection into the trial prompt."""
        result = self._miner.load()
        tags = tags or []

        success_hints = [
            f"[WORKS] {p.description} "
            f"(seen {p.occurrences}x, avg Δ={p.avg_score_delta:+.4f})"
            for p in result.success_patterns
            if p.domain == domain or any(t in tags for t in p.hs_ids)
        ][:MAX_HINTS]

        anti_hints = [
            f"[AVOID] {p.description} "
            f"(failed {p.occurrences}x across {len(p.hs_ids)} HS)"
            for p in result.anti_patterns
            if p.domain == domain or any(t in tags for t in p.hs_ids)
        ][:MAX_ANTI_HINTS]

        return success_hints + anti_hints

    def refresh(self) -> None:
        """Re-mine all HS logs and rebuild ontology files."""
        self._miner.mine_all()
