"""
Praxis CLI — entry point for all developer interactions.

The agent (Codex / Claude Code) drives the whole loop itself by reading the
AGENTS.md / CLAUDE.md that `new-hs` writes into each workspace. Praxis does
not call the agent repeatedly — it hands the terminal over and gets out of
the way, then reads back the files the agent produced.

Commands:
    praxis new-hs     Create a workspace (writes AGENTS.md + CLAUDE.md)
    praxis run        Hand the terminal to codex/claude in a workspace
    praxis status     Show lifecycle summary for one or all HS
    praxis promote    Validate and promote best policy to staging
    praxis refresh    Re-mine all logs and refresh Knowledge Layer
    praxis mcp-config Print MCP server config block for Claude Code
    praxis web        Start the web UI (product + algo dashboard)
"""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console
from rich.table import Table

from ..knowledge.meta_prompt import MetaPrompt
from ..protocol.lifecycle import LifecycleFSM
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
    console.print("  Wrote [bold]AGENTS.md[/bold] (Codex) + [bold]CLAUDE.md[/bold] (Claude Code).")
    console.print("  Launch the agent — it self-drives the whole loop:")
    console.print(f"    [cyan]cd {path} && codex[/cyan]   (or [cyan]claude[/cyan])")
    console.print(f"  Or via Praxis: [cyan]praxis run --hs {name}[/cyan]")


@cli.command("run")
@click.option("--hs", required=True, help="HS ID to run")
@click.option("--agent", default=None, help="Agent to launch: codex | claude (default: $PRAXIS_AGENT or codex)")
@click.option("--print-brief", is_flag=True, help="Just print the agent brief and the launch command; don't launch")
def run(hs: str, agent: str | None, print_brief: bool) -> None:
    """
    Hand the terminal over to Codex / Claude Code in the HS workspace.

    The agent reads AGENTS.md (Codex) or CLAUDE.md (Claude Code) and drives the
    WHOLE heuristic-learning loop itself — Praxis does not call it repeatedly.
    """
    import os

    ws_dir = ws.runs_root / hs
    if not (ws_dir / "hs_config.yaml").exists():
        console.print(f"[red]✗[/red] HS '{hs}' not found. Create it: praxis new-hs --name {hs} ...")
        sys.exit(1)

    # refresh the brief so latest knowledge-layer hints are embedded
    config = ws.load_config(hs)
    ws.write_agent_brief(config)

    agent = agent or os.environ.get("PRAXIS_AGENT", "codex")
    cmd = ["claude"] if agent == "claude" else ["codex"]

    brief_path = ws_dir / "AGENTS.md"
    if print_brief:
        console.print(f"[bold]Brief:[/bold] {brief_path}\n")
        console.print(brief_path.read_text(encoding="utf-8"))
        console.print(f"\n[bold]Launch with:[/bold] [cyan]cd {ws_dir} && {' '.join(cmd)}[/cyan]")
        return

    console.print(f"Handing terminal to [bold]{agent}[/bold] in [cyan]{ws_dir}[/cyan]")
    console.print(f"  [dim]The agent self-drives the loop. Ctrl-C to detach.[/dim]\n")

    # true handoff: replace this process with the agent, cwd = workspace
    try:
        os.chdir(ws_dir)
        os.execvp(cmd[0], cmd)
    except FileNotFoundError:
        console.print(
            f"[red]✗[/red] '{cmd[0]}' not found on PATH.\n"
            f"  Install {agent}, or run manually:\n"
            f"  [cyan]cd {ws_dir} && {' '.join(cmd)}[/cyan]"
        )
        sys.exit(127)



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
