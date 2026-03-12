"""
Tool implementations for agents.

Provides file I/O and command execution. These are the only operations
agents can perform on the project filesystem.
"""

import os
import subprocess
from pathlib import Path

# Commands that are never allowed
BLOCKED_PATTERNS = [
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=",
    ":(){ :|:&", "> /dev/sd", "chmod -R 777 /",
]


def _validate_path(project_root: str, path: str) -> tuple[bool, str, Path]:
    """Ensure path stays within project_root."""
    full = (Path(project_root) / path).resolve()
    try:
        full.relative_to(Path(project_root).resolve())
        return True, "", full
    except ValueError:
        return False, f"ERROR: Path traversal blocked: {path}", full


def read_file(project_root: str, path: str) -> str:
    ok, err, full = _validate_path(project_root, path)
    if not ok:
        return err
    if not full.exists():
        return f"ERROR: File not found: {path}"
    if not full.is_file():
        return f"ERROR: Not a file: {path}"
    try:
        return full.read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR: {e}"


def write_file(project_root: str, path: str, content: str) -> str:
    ok, err, full = _validate_path(project_root, path)
    if not ok:
        return err
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return f"OK: Written {len(content)} bytes to {path}"
    except Exception as e:
        return f"ERROR: {e}"


def list_files(project_root: str, path: str) -> str:
    ok, err, full = _validate_path(project_root, path)
    if not ok:
        return err
    if not full.exists():
        return f"ERROR: Directory not found: {path}"
    if not full.is_dir():
        return f"ERROR: Not a directory: {path}"
    entries = []
    for entry in sorted(full.iterdir()):
        prefix = "[DIR]  " if entry.is_dir() else "[FILE] "
        entries.append(f"{prefix}{entry.name}")
    return "\n".join(entries) if entries else "(empty directory)"


# Max chars to keep from stdout / stderr of a command.
# Maven/Gradle test output can be enormous; the *tail* usually holds
# the test summary, failures, and BUILD SUCCESS/FAILURE line.
_CMD_OUTPUT_MAX = 8000
_CMD_OUTPUT_HEAD = 1000   # first N chars kept when truncating


def _truncate_output(text: str, limit: int = _CMD_OUTPUT_MAX) -> str:
    """Truncate long command output, keeping head + tail."""
    if len(text) <= limit:
        return text
    head = text[:_CMD_OUTPUT_HEAD]
    tail = text[-(limit - _CMD_OUTPUT_HEAD):]
    dropped = len(text) - limit
    return f"{head}\n\n… [{dropped} chars truncated] …\n\n{tail}"


def execute_command(project_root: str, command: str, timeout: int = 120) -> str:
    timeout = min(max(timeout, 1), 300)
    for pat in BLOCKED_PATTERNS:
        if pat in command.lower():
            return f"ERROR: Blocked dangerous command: '{pat}'"
    try:
        result = subprocess.run(
            command, shell=True,
            cwd=str(Path(project_root).resolve()),
            capture_output=True, text=True,
            timeout=timeout, env=os.environ.copy(),
        )
        parts = []
        if result.stdout:
            parts.append(f"STDOUT:\n{_truncate_output(result.stdout)}")
        if result.stderr:
            parts.append(f"STDERR:\n{_truncate_output(result.stderr)}")
        parts.append(f"EXIT CODE: {result.returncode}")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return f"ERROR: Timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


# ── Claude API tool schemas (built from config.md definitions) ──────────

TOOL_SCHEMAS = {
    "read_file": {
        "name": "read_file",
        "description": "Read the contents of a file at the given path relative to the project root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from project root."}
            },
            "required": ["path"],
        },
    },
    "write_file": {
        "name": "write_file",
        "description": "Write content to a file. Creates parent dirs if needed. Overwrites existing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from project root."},
                "content": {"type": "string", "description": "Full content to write."},
            },
            "required": ["path", "content"],
        },
    },
    "list_files": {
        "name": "list_files",
        "description": "List files and directories at the given path relative to the project root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative dir path. '.' for root."}
            },
            "required": ["path"],
        },
    },
    "execute_command": {
        "name": "execute_command",
        "description": "Execute a shell command in the project root. Returns stdout, stderr, exit code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run."},
                "timeout": {"type": "integer", "description": "Timeout seconds (default 120, max 300)."},
            },
            "required": ["command"],
        },
    },
}

# Dispatch table: tool name → function
TOOL_DISPATCH = {
    "read_file":       lambda root, inp: read_file(root, inp["path"]),
    "write_file":      lambda root, inp: write_file(root, inp["path"], inp["content"]),
    "list_files":      lambda root, inp: list_files(root, inp["path"]),
    "execute_command": lambda root, inp: execute_command(root, inp["command"], inp.get("timeout", 120)),
}
