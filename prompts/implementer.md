# Implementer Prompt — Iteration {{iteration}}

## External Project

The Spring Boot project is located at: `{{project_path}}`

All file tools operate relative to this project root. Use `read_file("task.md")` / `write_file("task.md", ...)` for task.md. Shell commands (execute_command) run inside the project root.

## Current task.md

```
{{task_md}}
```

## Instructions

Implement all tasks with status `PLANNED` in the task.md above.

For each `PLANNED` task (process them in dependency order):

1. **Read context**: Read existing related files to understand the current code.
2. **Write implementation**: Create/update the file at the `file` path specified in the task.
3. **Write unit test**: Create/update the test file at the `test_file` path specified in the task.
4. **If the task has `rework_notes`**: Follow those instructions precisely — they contain the reviewer's fix requirements.

After writing ALL files:

5. Run `mvn compile -q` to verify everything compiles.
6. If compilation fails, read the errors, fix the code, and recompile until it succeeds.
7. Re-read `task.md`, set each implemented task's status to `IMPLEMENTED`, and write the full updated file.
