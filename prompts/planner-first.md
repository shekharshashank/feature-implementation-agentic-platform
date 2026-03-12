# Planner Prompt — First Iteration

This is **iteration 1**. You are starting fresh from a JIRA ticket.

**There is no `task.md` yet. You must create it.**

## External Project

The Spring Boot project is located at: `{{project_path}}`

All file tools (read_file, write_file, list_files) operate **relative to this project root**.
The `task.md` file is a special case — just use `write_file("task.md", ...)` to create it.

## JIRA Ticket Description

{{jira_description}}

## Instructions

1. Use `list_files(".")` to explore the project root.
2. Use `list_files("src/main/java")` to discover the existing package structure.
3. Read `pom.xml` to understand dependencies and the base package name.
4. Explore existing source code to understand the project's conventions and patterns.
5. Break the JIRA ticket into granular implementation tasks.
6. **Create `task.md`** using `write_file("task.md", ...)` following the exact format below.

## Required task.md Format

You MUST create `task.md` with this exact structure:

```markdown
# Task Tracking

## Metadata
- **jira_ticket**: {{jira_ticket}}
- **description**: {{jira_description}}
- **project_path**: {{project_path}}
- **current_phase**: PLANNING
- **iteration**: 1
- **max_iterations**: {{max_iterations}}
- **overall_status**: IN_PROGRESS

## Tasks

### Task 1: <Short Title>
- **status**: PLANNED
- **file**: <relative path to implementation file>
- **test_file**: <relative path to test file>
- **description**: <Detailed implementation instructions>
- **review_feedback**:
- **rework_notes**:

### Task 2: <Short Title>
...repeat for each task...

## Test Results
- **last_run**: N/A
- **status**: NOT_RUN
- **total**: 0
- **passed**: 0
- **failed**: 0
- **errors**: 0
- **output_summary**: No tests run yet.
- **failure_details**: N/A

## Iteration History

### Iteration 1
- **planner**: <summary of what you planned>
```
