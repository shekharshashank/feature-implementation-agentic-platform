# Multi-Agent Feature Implementation Platform

A multi-agent AI system that takes a JIRA ticket (or plain text description) and autonomously implements the feature in a Spring Boot project. Four specialized Claude agents — **Planner**, **Implementer**, **Reviewer**, and **Tester** — collaborate through a shared `task.md` file, iterating until all code is written, reviewed, and passing tests.

## How It Works

```
JIRA Ticket / Description
        |
        v
 ┌─────────────────┐
 │  Clarification   │  Planner evaluates if the ticket is clear enough.
 │     Phase        │  Asks user follow-up questions if needed.
 └────────┬────────┘
          v
 ┌──────────────────────────────────────────────────┐
 │                ITERATION LOOP                     │
 │                                                   │
 │  1. PLANNER   — Explores the project, breaks the │
 │                  ticket into granular tasks in     │
 │                  task.md                           │
 │                                                   │
 │  2. IMPLEMENTER — Writes Java code + unit tests   │
 │                    for each PLANNED task, runs     │
 │                    mvn compile                     │
 │                                                   │
 │  3. REVIEWER  — Reviews code quality, sets each   │
 │                  task to APPROVED or REWORK_NEEDED │
 │                                                   │
 │  4. TESTER    — Runs mvn test, records results,   │
 │                  promotes APPROVED tasks to DONE   │
 │                                                   │
 │  Exit when: all tasks DONE + tests PASSING        │
 │  Otherwise: loop (planner handles rework)         │
 └──────────────────────────────────────────────────┘
```

The agents communicate exclusively through `task.md`. No agent calls another directly — the orchestrator sequences them and each reads/writes the shared state file.

## Project Structure

```
.
├── main.py                  # CLI entry point
├── orchestrator.py          # Sequences agents, manages iterations and resume
├── agent_runner.py          # Executes any agent (API calls + tool loop)
├── tools.py                 # Tool implementations (file I/O, shell exec)
├── jira_mcp.py              # Jira MCP client for fetching tickets
├── config.md                # Central configuration (model, tools, pipeline)
├── requirements.txt         # Python dependencies
├── .env                     # Jira credentials (not committed)
├── agents/                  # Agent identity + system prompts
│   ├── planner-agent.md
│   ├── implementer-agent.md
│   ├── reviewer-agent.md
│   └── tester-agent.md
├── prompts/                 # Per-phase prompt templates with {{variables}}
│   ├── planner-first.md     # Planner prompt for iteration 1
│   ├── planner-next.md      # Planner prompt for rework iterations
│   ├── planner-clarify.md   # Planner prompt for clarification phase
│   ├── implementer.md
│   ├── reviewer.md
│   └── tester.md
├── shared/                  # Runtime state
│   ├── task-template.md     # Reference doc for task.md format
│   └── task.md              # Generated at runtime (gitignored)
└── mcp/
    └── jira-config.md       # Jira MCP server connection config
```

## Prerequisites

- **Python 3.12+**
- **AWS Bedrock access** with a bearer token (`AWS_BEARER_TOKEN_BEDROCK`)
- **Target project**: A Spring Boot 3.x / Java 21 / Maven project with a `pom.xml`
- **(Optional) Jira MCP server**: Only needed if fetching tickets directly from Jira

## Setup

1. **Clone the repository**

   ```bash
   git clone <repo-url>
   cd feature-implementation-agent-platform
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Set your AWS Bedrock token**

   ```bash
   export AWS_BEARER_TOKEN_BEDROCK="your-token-here"
   ```

   If not set, `main.py` will prompt you interactively.

4. **(Optional) Configure Jira credentials in `.env`**

   ```
   JIRA_PERSONAL_ACCESS_TOKEN=your-jira-pat
   JIRA_EMAIL=you@company.com
   ```

## Usage

### From a text description

```bash
python main.py --project-dir /path/to/spring-boot-app "Add a REST endpoint for user registration"
```

### From a Jira ticket

```bash
python main.py --project-dir /path/to/spring-boot-app --jira-ticket PROJ-123
```

### From a file

```bash
python main.py --project-dir /path/to/spring-boot-app --file ticket-description.txt
```

### Fully interactive

```bash
python main.py
```

Prompts for everything: project path, input method, description.

### CLI Options

| Flag | Short | Description |
|------|-------|-------------|
| `description` | | Inline text description (positional) |
| `--jira-ticket` | `-j` | Jira ticket key (e.g., `PROJ-123`) |
| `--file` | `-f` | Path to a file containing the description |
| `--project-dir` | | Path to the Spring Boot project |
| `--model` | `-m` | Override the Claude model from `config.md` |
| `--max-iterations` | | Override max iteration count (default: 10) |
| `--resume` | `-r` | Resume from a previous crashed/interrupted run |

## Crash Recovery

If the process crashes or is interrupted mid-run, `task.md` retains the last known state (iteration number, current phase, task statuses). On restart:

```bash
# Explicit resume
python main.py --resume

# Or just run main.py — it auto-detects the existing task.md and prompts:
#   "Found existing task.md from a previous run."
#   "Resume from where it left off? [y/N]:"
```

When resuming:
- The project path, JIRA description, and ticket key are read from `task.md` metadata — no need to re-enter them.
- The clarification phase is skipped (it was already completed).
- The pipeline restarts from the agent that was in progress (e.g., if the tester was running, only the tester re-runs for that iteration, then continues with subsequent full iterations).

## The Agents

### Planner

**Role**: Software architect. Explores the project, breaks the ticket into granular tasks.

- **Tools**: `read_file`, `write_file`, `list_files`
- **Iteration 1**: Creates `task.md` with `PLANNED` tasks (one per Java class).
- **Iteration 2+**: Reads reviewer feedback and test failures, revises task descriptions, resets status to `PLANNED`.

### Implementer

**Role**: Java developer. Writes production code and unit tests.

- **Tools**: `read_file`, `write_file`, `list_files`, `execute_command`
- Implements each `PLANNED` task in dependency order (DTOs, services, controllers).
- Runs `mvn compile` to verify, fixes compilation errors, then marks tasks as `IMPLEMENTED`.

### Reviewer

**Role**: Code reviewer. Evaluates quality and correctness.

- **Tools**: `read_file`, `write_file`, `list_files`
- Reviews each `IMPLEMENTED` task against a checklist (Spring Boot conventions, test quality, error handling, security).
- Sets tasks to `APPROVED` or `REWORK_NEEDED` with specific feedback.

### Tester

**Role**: QA engineer. Runs the test suite and records results.

- **Tools**: `read_file`, `write_file`, `execute_command`, `list_files`
- Runs `mvn test`, parses results, updates the `## Test Results` section.
- If all tests pass: promotes `APPROVED` tasks to `DONE`.
- If any fail: records failure details for the next iteration.

## Task Status Flow

```
PLANNED  -->  IMPLEMENTED  -->  APPROVED  -->  DONE
                            \
                             -> REWORK_NEEDED  -->  PLANNED (next iteration)
```

The pipeline is complete when **all tasks are `DONE`** and **tests are `PASSING`**.

## Configuration

All configuration lives in `config.md`:

| Setting | Default | Description |
|---------|---------|-------------|
| Model | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Claude model on AWS Bedrock |
| Max tokens | `8192` | Max response tokens per agent call |
| Max iterations | `10` | Iteration limit before asking user for help |

The agent pipeline order and tool definitions are also declared in `config.md`.

## Safety

- **Path traversal protection**: All file operations are sandboxed to the project root.
- **Blocked commands**: Dangerous shell commands (`rm -rf /`, `mkfs`, `dd if=`, fork bombs, etc.) are rejected.
- **Command timeouts**: Shell commands are capped at 300 seconds.
- **Output truncation**: Large command output (e.g., `mvn test`) is truncated to prevent context window overflow, keeping the head and tail where build results and errors appear.

## User Assistance Fallback

If the pipeline exhausts all iterations without completing, it enters `NEEDS_USER_HELP` mode:
- Shows a summary of incomplete tasks with reviewer feedback and test failures.
- Prompts for guidance text.
- Runs one bonus iteration incorporating the user's input.

## License

Private / Internal use.
