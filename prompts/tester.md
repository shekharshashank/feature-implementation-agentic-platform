# Tester Prompt — Iteration {{iteration}}

## External Project

The Spring Boot project is located at: `{{project_path}}`

Shell commands (execute_command) run inside the project root. Use `read_file("task.md")` / `write_file("task.md", ...)` for task.md.

## Current task.md

```
{{task_md}}
```

## Instructions

1. Run the test suite: `execute_command("mvn test")`
2. Parse the Maven output and extract:
   - Total tests, passed, failed, errors
   - For each failure: fully qualified test name + assertion/error message
3. Update the `## Test Results` section of `task.md` with results.
4. **If all tests pass**: Set all `APPROVED` tasks to `DONE`. Set test status to `PASSING`.
5. **If any tests fail**: Keep statuses as-is. Set test status to `FAILING`. Record failure details.
6. Add a summary to `## Iteration History`.
7. Write the full updated `task.md`.
