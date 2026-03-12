# Configuration

## Jira MCP Integration
- **enabled**: true
- **config_file**: mcp/jira-config.md
- **server_path**: /Users/shashankshekhar/workspace/AI/adobe-mcp-servers/src/corp-jira/dist/index.js
- **required_env**: JIRA_PERSONAL_ACCESS_TOKEN, JIRA_EMAIL

## AWS Bedrock
- **auth**: AWS_BEARER_TOKEN_BEDROCK (from ~/.bashrc)

## Model
- **name**: us.anthropic.claude-sonnet-4-20250514-v1:0
- **max_tokens**: 8192

## Orchestrator
- **max_iterations**: 10
- **task_file**: shared/task.md

## Project
- **path**: (provided via --project-dir CLI argument)
- **type**: spring-boot
- **java_version**: 21
- **build_tool**: maven

## Agent Pipeline Order
1. planner
2. implementer
3. reviewer
4. tester

## Tool Definitions

### read_file
- **description**: Read the contents of a file at the given path relative to the project root. Returns the full file contents as a string.
- **parameters**:
  - path (string, required): Relative path from the project root.

### write_file
- **description**: Write content to a file at the given path relative to the project root. Creates parent directories if needed. Overwrites if the file exists.
- **parameters**:
  - path (string, required): Relative path from the project root.
  - content (string, required): The full content to write.

### list_files
- **description**: List all files and directories at the given path relative to the project root.
- **parameters**:
  - path (string, required): Relative directory path. Use '.' for root.

### execute_command
- **description**: Execute a shell command in the project root directory. Returns stdout, stderr, and exit code. Use for Maven commands, compilation checks, etc.
- **parameters**:
  - command (string, required): The shell command to execute.
  - timeout (integer, optional, default=120): Timeout in seconds (max 300).

## Blocked Commands
- rm -rf /
- rm -rf /*
- mkfs
- dd if=
- :(){ :|:&
- > /dev/sd
- chmod -R 777 /
