"""
Generic agent runner.

Loads an agent definition from its .md file, builds the Claude API request,
and runs the tool-calling loop until the agent finishes or hits limits.
No agent-specific logic lives here — all behavior comes from the .md files.
"""

import json
import re
import time
from pathlib import Path
from typing import Any

import os

import httpx
from anthropic import AnthropicBedrock, APIError, RateLimitError

from tools import TOOL_SCHEMAS, TOOL_DISPATCH


class _BedrockBearerClient(AnthropicBedrock):
    """
    Mirrors how Claude Code connects to Bedrock:
    skip SigV4 signing, pass AWS_BEARER_TOKEN_BEDROCK as Authorization header.
    """

    def __init__(self, bearer_token: str, **kwargs):
        self._bearer_token = bearer_token
        super().__init__(**kwargs)

    def _prepare_request(self, request: httpx.Request) -> None:
        request.headers["Authorization"] = f"Bearer {self._bearer_token}"

# ── Markdown parsing helpers ────────────────────────────────────────────


def load_agent_config(agent_md_path: str) -> dict:
    """
    Parse an agent .md file and extract:
      - name: str
      - tools: list[str]
      - max_tool_calls: int
      - system_prompt: str (everything under '## System Prompt')
    """
    text = Path(agent_md_path).read_text(encoding="utf-8")

    name = _extract_field(text, "name") or "agent"
    tools_str = _extract_field(text, "tools") or ""
    tools = [t.strip() for t in tools_str.split(",") if t.strip()]
    max_calls = int(_extract_field(text, "max_tool_calls") or "40")

    # System prompt = everything after "## System Prompt"
    marker = "## System Prompt"
    idx = text.find(marker)
    if idx != -1:
        system_prompt = text[idx + len(marker):].strip()
    else:
        # Fallback: use everything after the Config section
        system_prompt = text

    return {
        "name": name,
        "tools": tools,
        "max_tool_calls": max_calls,
        "system_prompt": system_prompt,
    }


def load_prompt_template(template_path: str, variables: dict) -> str:
    """Load a prompt .md file and substitute {{variable}} placeholders."""
    text = Path(template_path).read_text(encoding="utf-8")
    for key, value in variables.items():
        text = text.replace(f"{{{{{key}}}}}", str(value))
    return text


def _extract_field(text: str, field_name: str) -> str | None:
    """Extract a **field**: value from markdown."""
    pattern = rf"\*\*{re.escape(field_name)}\*\*:\s*(.+)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


# ── Agent runner ────────────────────────────────────────────────────────


# Safety cap: any single tool result larger than this is truncated before
# being added to the conversation.  Prevents context-window blow-ups when
# commands like `mvn test` produce huge output.
_MAX_TOOL_RESULT_CHARS = 16_000


class AgentRunner:
    """
    Runs a single agent turn: sends a prompt to Claude with the agent's
    system prompt and tools, executes tool calls in a loop, and returns
    the final text response.
    """

    def __init__(self, project_root: str, task_md_path: str, model: str,
                 max_tokens: int = 8192, skill_md_path: str = ""):
        self.project_root = project_root
        self.task_md_path = task_md_path    # absolute path to shared/task.md
        self.skill_md_path = skill_md_path  # absolute path to skills/<project>.md
        self.model = model
        self.max_tokens = max_tokens
        self.client = _BedrockBearerClient(
            bearer_token=os.environ["AWS_BEARER_TOKEN_BEDROCK"],
            aws_region=os.environ.get("AWS_REGION", "us-west-2"),
        )

    def run(self, agent_config: dict, user_prompt: str) -> str:
        """
        Execute one agent's full tool-calling loop.

        Args:
            agent_config: Parsed agent .md config (from load_agent_config).
            user_prompt: The rendered prompt for this phase/iteration.

        Returns:
            The agent's final text response.
        """
        name = agent_config["name"]
        max_tool_calls = agent_config["max_tool_calls"]

        # Build tool list from agent's declared tool names
        tools = [TOOL_SCHEMAS[t] for t in agent_config["tools"] if t in TOOL_SCHEMAS]

        print(f"\n{'─'*60}")
        print(f"  {name.upper()} AGENT STARTED")
        print(f"  Tools: {', '.join(agent_config['tools'])}")
        print(f"{'─'*60}")

        messages: list[dict] = [{"role": "user", "content": user_prompt}]
        tool_call_count = 0
        final_text = ""

        while tool_call_count < max_tool_calls:
            response = self._call_api(agent_config["system_prompt"], tools, messages)

            # Parse response blocks
            assistant_content: list[dict] = []
            tool_use_blocks: list[Any] = []
            text_parts: list[str] = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_use_blocks.append(block)
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            messages.append({"role": "assistant", "content": assistant_content})

            # Done if no tool calls
            if response.stop_reason == "end_turn" or not tool_use_blocks:
                final_text = "\n".join(text_parts)
                break

            # Execute tools
            tool_results: list[dict] = []
            for tb in tool_use_blocks:
                tool_call_count += 1
                summary = json.dumps(tb.input)
                if len(summary) > 100:
                    summary = summary[:100] + "…"
                print(f"  [{name}] Tool #{tool_call_count}: {tb.name}({summary})")

                result = self._execute_tool(tb.name, tb.input)

                # Safety-net: truncate any oversized tool result so we
                # don't blow the model's context window.
                if len(result) > _MAX_TOOL_RESULT_CHARS:
                    head_len = 2000
                    tail_len = _MAX_TOOL_RESULT_CHARS - head_len
                    dropped = len(result) - _MAX_TOOL_RESULT_CHARS
                    result = (
                        result[:head_len]
                        + f"\n\n… [{dropped} chars truncated — showing first {head_len}"
                        + f" and last {tail_len} chars] …\n\n"
                        + result[-tail_len:]
                    )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tb.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        if tool_call_count >= max_tool_calls:
            print(f"  [{name}] WARNING: Hit max tool calls ({max_tool_calls})")

        print(f"  {name.upper()} AGENT FINISHED ({tool_call_count} tool calls)")
        print(f"{'─'*60}\n")
        return final_text

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """
        Route tool calls. task.md and skill.md reads/writes are redirected
        to framework-managed paths. Everything else targets the external project.
        """
        from tools import read_file, write_file

        path = tool_input.get("path", "")

        # Intercept task.md — lives in framework's shared/ dir
        if path in ("task.md", "./task.md"):
            if tool_name == "read_file":
                try:
                    return Path(self.task_md_path).read_text(encoding="utf-8")
                except Exception as e:
                    return f"ERROR: {e}"
            elif tool_name == "write_file":
                try:
                    Path(self.task_md_path).write_text(
                        tool_input["content"], encoding="utf-8"
                    )
                    return f"OK: Written {len(tool_input['content'])} bytes to task.md"
                except Exception as e:
                    return f"ERROR: {e}"

        # Intercept skill.md — lives in framework's skills/ dir
        if path in ("skill.md", "./skill.md") and self.skill_md_path:
            if tool_name == "read_file":
                try:
                    p = Path(self.skill_md_path)
                    if not p.exists():
                        return "(skill.md does not exist yet)"
                    return p.read_text(encoding="utf-8")
                except Exception as e:
                    return f"ERROR: {e}"
            elif tool_name == "write_file":
                try:
                    p = Path(self.skill_md_path)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(tool_input["content"], encoding="utf-8")
                    return f"OK: Written {len(tool_input['content'])} bytes to skill.md ({p})"
                except Exception as e:
                    return f"ERROR: {e}"

        # Everything else goes to the external project root
        handler = TOOL_DISPATCH.get(tool_name)
        if handler:
            try:
                return handler(self.project_root, tool_input)
            except Exception as e:
                return f"ERROR: {e}"
        return f"ERROR: Unknown tool: {tool_name}"

    def _call_api(self, system: str, tools: list, messages: list, retries: int = 3) -> Any:
        """Call Claude API with retry for rate limits and server errors."""
        for attempt in range(retries):
            try:
                return self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system,
                    tools=tools,
                    messages=messages,
                )
            except RateLimitError:
                wait = (2 ** attempt) * 10
                print(f"  Rate limited. Waiting {wait}s…")
                time.sleep(wait)
                if attempt == retries - 1:
                    raise
            except APIError as e:
                if e.status_code and e.status_code >= 500 and attempt < retries - 1:
                    wait = (2 ** attempt) * 5
                    print(f"  API error {e.status_code}. Retrying in {wait}s…")
                    time.sleep(wait)
                else:
                    raise
