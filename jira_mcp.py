"""
Jira MCP client.

Connects to the corp-jira MCP server over stdio, fetches ticket details
(summary, description, comments), and returns them as a formatted string
for use as the JIRA description in the agent pipeline.

Configuration is loaded from mcp/jira-config.md.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _load_mcp_config(base_dir: str) -> dict:
    """Parse mcp/jira-config.md for server connection details."""
    config_path = Path(base_dir) / "mcp" / "jira-config.md"
    text = config_path.read_text(encoding="utf-8")

    def field(name: str, default: str = "") -> str:
        match = re.search(rf"\*\*{re.escape(name)}\*\*:\s*(.+)", text)
        return match.group(1).strip() if match else default

    return {
        "command": field("command", "node"),
        "args": field("args", ""),
        "transport": field("transport", "stdio"),
    }


async def _fetch_ticket_async(base_dir: str, ticket_key: str) -> str:
    """Connect to Jira MCP server and fetch ticket details."""
    config = _load_mcp_config(base_dir)

    # Validate required env vars
    if not os.environ.get("JIRA_PERSONAL_ACCESS_TOKEN"):
        raise RuntimeError(
            "JIRA_PERSONAL_ACCESS_TOKEN environment variable is not set.\n"
            "  Generate a PAT from your Jira profile and set it:\n"
            "  export JIRA_PERSONAL_ACCESS_TOKEN='your-token'"
        )
    if not os.environ.get("JIRA_EMAIL"):
        raise RuntimeError(
            "JIRA_EMAIL environment variable is not set.\n"
            "  export JIRA_EMAIL='your.email@company.com'"
        )

    # Build server params — pass Jira env vars to the subprocess
    env = {
        "JIRA_PERSONAL_ACCESS_TOKEN": os.environ["JIRA_PERSONAL_ACCESS_TOKEN"],
        "JIRA_EMAIL": os.environ["JIRA_EMAIL"],
        "PATH": os.environ.get("PATH", ""),
        "NODE_PATH": os.environ.get("NODE_PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }
    # Forward optional Jira env vars if set
    for key in ("JIRA_API_BASE_URL", "JIRA_MAX_RESULTS", "JIRA_TIMEOUT", "JIRA_STRICT_SSL"):
        if os.environ.get(key):
            env[key] = os.environ[key]

    server_params = StdioServerParameters(
        command=config["command"],
        args=[config["args"]],
        env=env,
    )

    print(f"  [jira-mcp] Connecting to Jira MCP server…")
    print(f"  [jira-mcp] Fetching ticket: {ticket_key}")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. Fetch ticket details via search
            search_result = await session.call_tool(
                "search_jira_issues",
                {"jql": f"key = {ticket_key}", "minimizeOutput": False},
            )
            ticket_data = _extract_text(search_result)

            # 2. Fetch comments for additional context
            try:
                comments_result = await session.call_tool(
                    "get_jira_comments",
                    {"issueKey": ticket_key},
                )
                comments_data = _extract_text(comments_result)
            except Exception:
                comments_data = "(no comments)"

    # Format into a clean description
    description = _format_ticket(ticket_key, ticket_data, comments_data)
    print(f"  [jira-mcp] Fetched {len(description)} chars of ticket data")
    return description


def _extract_text(result: Any) -> str:
    """Extract text content from an MCP tool result."""
    if hasattr(result, "content"):
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts)
    return str(result)


def _format_ticket(ticket_key: str, ticket_data: str, comments_data: str) -> str:
    """Format raw Jira data into a structured description for agents."""
    sections = [f"# Jira Ticket: {ticket_key}", ""]

    # Try to parse as JSON for cleaner formatting
    try:
        data = json.loads(ticket_data)
        issues = data.get("issues", [data] if "key" in data else [])
        if issues:
            issue = issues[0]
            fields = issue.get("fields", {})
            sections.append(f"## Summary\n{fields.get('summary', 'N/A')}\n")
            sections.append(f"## Type\n{_nested(fields, 'issuetype', 'name', 'N/A')}\n")
            sections.append(f"## Priority\n{_nested(fields, 'priority', 'name', 'N/A')}\n")
            sections.append(f"## Status\n{_nested(fields, 'status', 'name', 'N/A')}\n")

            desc = fields.get("description", "No description provided")
            sections.append(f"## Description\n{desc}\n")

            # Acceptance criteria (often in customfield or description)
            if fields.get("customfield_10100"):
                sections.append(f"## Acceptance Criteria\n{fields['customfield_10100']}\n")

            # Labels
            labels = fields.get("labels", [])
            if labels:
                sections.append(f"## Labels\n{', '.join(labels)}\n")

            # Components
            components = fields.get("components", [])
            if components:
                names = [c.get("name", "") for c in components]
                sections.append(f"## Components\n{', '.join(names)}\n")
    except (json.JSONDecodeError, TypeError, KeyError):
        # Not JSON or unexpected structure — use raw text
        sections.append(f"## Ticket Data\n{ticket_data}\n")

    # Add comments
    if comments_data and comments_data != "(no comments)":
        sections.append(f"## Comments\n{comments_data}\n")

    return "\n".join(sections)


def _nested(d: dict, key1: str, key2: str, default: str) -> str:
    """Safely get nested dict value."""
    val = d.get(key1)
    if isinstance(val, dict):
        return val.get(key2, default)
    return default


def fetch_ticket(base_dir: str, ticket_key: str) -> str:
    """
    Public sync interface. Starts the Jira MCP server, fetches the ticket,
    and returns a formatted description string.
    """
    return asyncio.run(_fetch_ticket_async(base_dir, ticket_key))
