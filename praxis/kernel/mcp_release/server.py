"""MCP server: gradual release / feature flag adapter."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("praxis-release")

TOOLS: list[Tool] = [
    Tool(
        name="release_deploy",
        description=(
            "Deploy a policy version to an environment at a given traffic percentage. "
            "Always starts at ≤10% for first deployment."
        ),
        inputSchema={
            "type": "object",
            "required": ["hs_id", "policy_version", "env", "traffic_pct"],
            "properties": {
                "hs_id": {"type": "string"},
                "policy_version": {"type": "string"},
                "env": {
                    "type": "string",
                    "enum": ["staging", "canary", "production"],
                },
                "traffic_pct": {
                    "type": "number",
                    "description": "0–100. For env=production, max 10 on first deploy.",
                },
            },
        },
    ),
    Tool(
        name="release_status",
        description="Get current deployment status for an HS.",
        inputSchema={
            "type": "object",
            "required": ["hs_id"],
            "properties": {
                "hs_id": {"type": "string"},
                "env": {"type": "string", "enum": ["staging", "canary", "production", "all"]},
            },
        },
    ),
    Tool(
        name="release_rollback",
        description="Immediately roll back an HS to its previous policy version.",
        inputSchema={
            "type": "object",
            "required": ["hs_id", "env"],
            "properties": {
                "hs_id": {"type": "string"},
                "env": {"type": "string"},
                "reason": {"type": "string"},
            },
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "release_deploy":
        result = {"deployment_id": "stub-deploy-001", "ok": True, "_note": "stub"}
    elif name == "release_status":
        result = {"hs_id": arguments["hs_id"], "deployments": [], "_note": "stub"}
    elif name == "release_rollback":
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
