"""
MCP server: ticket system adapter.

Exposes read-only ticket queries and triage annotation tools to Claude Code.
Business credentials are loaded from environment variables — never hardcoded.

Run standalone:
    python -m praxis.kernel.mcp_ticket.server

Or register in Claude Code's MCP config:
    {
      "mcpServers": {
        "ticket": {
          "command": "python",
          "args": ["-m", "praxis.kernel.mcp_ticket.server"]
        }
      }
    }
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("praxis-ticket")

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="ticket_search",
        description=(
            "Search tickets by keyword, status, or date range. "
            "Returns up to 50 results with id, subject, status, priority, created_at."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search"},
                "status": {
                    "type": "string",
                    "enum": ["open", "pending", "resolved", "closed", "all"],
                    "default": "open",
                },
                "limit": {"type": "integer", "default": 20, "maximum": 50},
            },
        },
    ),
    Tool(
        name="ticket_get",
        description="Fetch full details of a single ticket including conversation thread.",
        inputSchema={
            "type": "object",
            "required": ["ticket_id"],
            "properties": {
                "ticket_id": {"type": "string"},
            },
        },
    ),
    Tool(
        name="ticket_annotate",
        description=(
            "Attach a structured annotation to a ticket for policy evaluation. "
            "Used to record which policy rule handled this case and the outcome."
        ),
        inputSchema={
            "type": "object",
            "required": ["ticket_id", "annotation"],
            "properties": {
                "ticket_id": {"type": "string"},
                "annotation": {
                    "type": "object",
                    "properties": {
                        "policy_version": {"type": "string"},
                        "matched_rule": {"type": "string"},
                        "predicted_label": {"type": "string"},
                        "confidence": {"type": "number"},
                        "notes": {"type": "string"},
                    },
                },
            },
        },
    ),
    Tool(
        name="ticket_regression_cases",
        description=(
            "Return a list of tickets previously marked as regression test cases "
            "for a given HS ID."
        ),
        inputSchema={
            "type": "object",
            "required": ["hs_id"],
            "properties": {
                "hs_id": {"type": "string"},
            },
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


# ---------------------------------------------------------------------------
# Tool implementations (stub — replace with real API calls)
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "ticket_search":
        return [TextContent(type="text", text=json.dumps(_stub_search(arguments)))]
    if name == "ticket_get":
        return [TextContent(type="text", text=json.dumps(_stub_get(arguments)))]
    if name == "ticket_annotate":
        return [TextContent(type="text", text=json.dumps({"ok": True}))]
    if name == "ticket_regression_cases":
        return [TextContent(type="text", text=json.dumps({"cases": []}))]
    raise ValueError(f"Unknown tool: {name}")


def _stub_search(args: dict) -> dict:
    """Replace with real ticket system API call."""
    return {
        "tickets": [],
        "total": 0,
        "_note": "stub — set TICKET_API_URL and TICKET_API_KEY env vars",
    }


def _stub_get(args: dict) -> dict:
    return {
        "ticket_id": args.get("ticket_id"),
        "subject": "(stub)",
        "body": "",
        "status": "open",
        "_note": "stub",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
