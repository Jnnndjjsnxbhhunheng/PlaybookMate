"""
Praxis CLI — entry point for all developer interactions.

Commands:
    praxis new-hs     Create a new heuristic system workspace
    praxis run        Execute one trial cycle for an HS
    praxis run-all    Run all registered HS (parallel)
    praxis status     Show lifecycle summary for one or all HS
    praxis promote    Validate and promote best policy to staging
    praxis refresh    Re-mine all logs and refresh Knowledge Layer
    praxis mcp-config Print MCP server config block for Claude Code
    praxis web        Start the web UI (product + algo dashboard)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..knowledge.meta_prompt import MetaPrompt
from ..protocol.lifecycle import LifecycleFSM
from ..protocol.orchestrator import Orchestrator
from ..protocol.workspace import HSConfig, WorkspaceManager

console = Console()
ws = WorkspaceManager()


@click.group()
def cli() -> None:
    """Praxis — Heuristic System OS."""


@cli.command("new-hs")
@click.option("--name", required=True, help="Unique HS identifier (snake_case)")
@click.option("--domain", required=True, help="Domain template to use (e.g. ticket_routing)")
@click.option("--description", default="", help="Short description of what this HS optimises")
@click.option("--metric", default="score", help="Primary metric name")
@click.option("--budget-seconds", default=3600, help="Per-run wall time budget")
@click.option("--budget-tokens", default=500_000, help="Per-run LLM token budget")
def new_hs(
    name: str,
    domain: str,
    description: str,
    metric: str,
    budget_seconds: int,
    budget_tokens: int,
) -> None:
    """Create a new heuristic system workspace."""
    config = HSConfig(
        hs_id=name,
        domain=domain,
        description=description,
        primary_metric=metric,
        budget_wall_seconds=budget_seconds,
        budget_llm_tokens=budget_tokens,
    )
    path = ws.create(config)
    console.print(f"[green]✓[/green] Created HS workspace: [bold]{path}[/bold]")
    console.print(f"  Next step: [cyan]praxis run --hs {name}[/cyan]")


@cli.command("run")
@click.option("--hs", required=True, help="HS ID to run")
@click.option("--dry-run", is_flag=True, help="Render prompt and exit without spawning agent")
def run(hs: str, dry_run: bool) -> None:
    """Execute one trial cycle for an HS."""
    orch = Orchestrator()
    console.print(f"Starting trial for [bold]{hs}[/bold]...")
    result = orch.run_hs(hs, dry_run=dry_run)

    if dry_run:
        prompt_file = result.run_dir / "PROMPT.md"
        console.print(f"[yellow]dry-run[/yellow] Prompt written to: {prompt_file}")
        console.print(prompt_file.read_text(encoding="utf-8"))
        return

    if not result.success:
        console.print(f"[red]✗[/red] Trial failed: {result.error}")
        sys.exit(1)

    t = result.trial
    assert t is not None
    delta = t.score.delta
    delta_str = f" (Δ{delta:+.4f})" if delta is not None else ""
    console.print(
        f"[green]✓[/green] Trial #{t.trial_idx} — "
        f"outcome=[bold]{t.outcome}[/bold] "
        f"score={t.score.primary:.4f}{delta_str}"
    )


@cli.command("run-all")
@click.option("--parallel", default=4, help="Max parallel agents")
def run_all(parallel: int) -> None:
    """Run all registered HS concurrently."""
    hs_list = ws.list_hs()
    if not hs_list:
        console.print("[yellow]No HS workspaces found.[/yellow]")
        return
    console.print(f"Running {len(hs_list)} HS with max_parallel={parallel}...")
    orch = Orchestrator()
    results = asyncio.run(orch.run_many(hs_list, max_parallel=parallel))
    for r in results:
        if r.success and r.trial:
            console.print(f"  [green]✓[/green] {r.trial.hs_id} — {r.trial.outcome}")
        else:
            console.print(f"  [red]✗[/red] {r.run_dir.parent.name} — {r.error}")


@cli.command("status")
@click.option("--hs", default=None, help="Specific HS ID (omit for all)")
def status(hs: str | None) -> None:
    """Show lifecycle summary."""
    hs_list = [hs] if hs else ws.list_hs()
    if not hs_list:
        console.print("[yellow]No HS workspaces found.[/yellow]")
        return

    table = Table(title="Praxis HS Status")
    table.add_column("HS ID", style="cyan")
    table.add_column("Phase", style="bold")
    table.add_column("Trials", justify="right")
    table.add_column("Best Score", justify="right")
    table.add_column("Total Tokens", justify="right")

    for h in hs_list:
        try:
            fsm = LifecycleFSM(h)
            s = fsm.summary()
            table.add_row(
                h,
                s["phase"],
                str(s["total_trials"]),
                f"{s['best_score']:.4f}" if s["best_score"] is not None else "—",
                f"{s['cumulative_tokens']:,}",
            )
        except FileNotFoundError:
            table.add_row(h, "ERROR", "—", "—", "—")

    console.print(table)


@cli.command("promote")
@click.option("--hs", required=True, help="HS ID to promote")
@click.option("--env", default="staging", help="Target environment")
def promote(hs: str, env: str) -> None:
    """Validate and promote best policy to target environment."""
    missing = ws.validate_for_promotion(hs)
    if missing:
        console.print(f"[red]✗ Cannot promote — missing:[/red]")
        for m in missing:
            console.print(f"  - {m}")
        sys.exit(1)

    fsm = LifecycleFSM(hs)
    s = fsm.summary()
    console.print(
        f"[green]✓[/green] Promotion checks passed for [bold]{hs}[/bold].\n"
        f"  Phase: {s['phase']}  Best score: {s['best_score']}\n"
        f"  Target: [bold]{env}[/bold]\n\n"
        "  Next step: use the [cyan]mcp_release deploy[/cyan] tool or run:\n"
        f"  [cyan]praxis mcp-config[/cyan] → configure in Claude Code → "
        f"call release_deploy(hs_id={hs!r}, env={env!r}, traffic_pct=5)"
    )


@cli.command("refresh")
def refresh() -> None:
    """Re-mine all HS trial logs and refresh the Knowledge Layer."""
    mp = MetaPrompt()
    mp.refresh()
    console.print("[green]✓[/green] Knowledge Layer refreshed.")


@cli.command("web")
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", default=8000, help="Bind port")
@click.option("--reload", is_flag=True, help="Auto-reload on file changes (dev mode)")
def web(host: str, port: int, reload: bool) -> None:
    """Start the Praxis web UI."""
    from ..web.server import serve
    console.print(f"Starting Praxis web UI at [cyan]http://{host}:{port}[/cyan]")
    console.print("  [dim]Product: open in browser, switch to 🗂 Product role[/dim]")
    console.print("  [dim]Algo:    switch to ⚙ Algorithm role for review controls[/dim]")
    serve(host=host, port=port, reload=reload)


@cli.command("mcp-config")
def mcp_config() -> None:
    """Print the MCP server config block to add to Claude Code's settings."""
    config = {
        "mcpServers": {
            "praxis-ticket": {
                "command": "python",
                "args": ["-m", "praxis.kernel.mcp_ticket.server"],
            },
            "praxis-kpi": {
                "command": "python",
                "args": ["-m", "praxis.kernel.mcp_kpi.server"],
            },
            "praxis-ab": {
                "command": "python",
                "args": ["-m", "praxis.kernel.mcp_ab_platform.server"],
            },
            "praxis-release": {
                "command": "python",
                "args": ["-m", "praxis.kernel.mcp_release.server"],
            },
        }
    }
    console.print("Add to ~/.claude/claude_desktop_config.json (or your project .mcp.json):\n")
    console.print(json.dumps(config, indent=2))


if __name__ == "__main__":
    cli()
