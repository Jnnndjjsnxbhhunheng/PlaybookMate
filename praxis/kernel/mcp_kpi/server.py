"""MCP server: KPI dashboard adapter (read-only)."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("praxis-kpi")

TOOLS: list[Tool] = [
    Tool(
        name="kpi_get",
        description=(
            "Fetch current value of a named KPI. "
            "Returns value, unit, timestamp, and 7-day trend."
        ),
        inputSchema={
            "type": "object",
            "required": ["metric_name"],
            "properties": {
                "metric_name": {"type": "string"},
                "granularity": {
                    "type": "string",
                    "enum": ["hourly", "daily", "weekly"],
                    "default": "daily",
                },
            },
        },
    ),
    Tool(
        name="kpi_compare",
        description="Compare two time windows for a KPI (e.g. before/after a policy change).",
        inputSchema={
            "type": "object",
            "required": ["metric_name", "window_a_start", "window_b_start"],
            "properties": {
                "metric_name": {"type": "string"},
                "window_a_start": {"type": "string", "format": "date"},
                "window_b_start": {"type": "string", "format": "date"},
                "window_days": {"type": "integer", "default": 7},
            },
        },
    ),
    Tool(
        name="kpi_list",
        description="List all available KPI metric names.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "kpi_get":
        result = {"metric": arguments["metric_name"], "value": None, "_note": "stub"}
    elif name == "kpi_compare":
        result = {"delta": None, "_note": "stub"}
    elif name == "kpi_list":
        result = {"metrics": [], "_note": "stub — set KPI_API_URL env var"}
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [TextContent(type="text", text=json.dumps(result))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
