"""MCP server: A/B experiment platform adapter."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("praxis-ab")

TOOLS: list[Tool] = [
    Tool(
        name="ab_create",
        description=(
            "Register a new A/B experiment for a policy change. "
            "Returns experiment_id."
        ),
        inputSchema={
            "type": "object",
            "required": ["name", "hs_id", "policy_version", "traffic_fraction"],
            "properties": {
                "name": {"type": "string"},
                "hs_id": {"type": "string"},
                "policy_version": {"type": "string"},
                "traffic_fraction": {
                    "type": "number",
                    "description": "0.0–0.5 fraction of traffic to expose to new policy",
                },
                "primary_metric": {"type": "string"},
                "duration_days": {"type": "integer", "default": 7},
            },
        },
    ),
    Tool(
        name="ab_status",
        description="Get current results of an A/B experiment.",
        inputSchema={
            "type": "object",
            "required": ["experiment_id"],
            "properties": {
                "experiment_id": {"type": "string"},
            },
        },
    ),
    Tool(
        name="ab_stop",
        description="Stop an experiment and optionally promote the winner.",
        inputSchema={
            "type": "object",
            "required": ["experiment_id", "action"],
            "properties": {
                "experiment_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["promote_treatment", "promote_control", "abandon"],
                },
            },
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "ab_create":
        result = {"experiment_id": "stub-001", "_note": "stub"}
    elif name == "ab_status":
        result = {
            "experiment_id": arguments["experiment_id"],
            "status": "running",
            "treatment_n": 0,
            "control_n": 0,
            "p_value": None,
            "_note": "stub",
        }
    elif name == "ab_stop":
        result = {"ok": True, "_note": "stub"}
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [TextContent(type="text", text=json.dumps(result))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
