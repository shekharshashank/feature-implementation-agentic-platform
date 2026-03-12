# Reviewer Prompt — Iteration {{iteration}}

## External Project

The Spring Boot project is located at: `{{project_path}}`

All file tools operate relative to this project root. Use `read_file("task.md")` / `write_file("task.md", ...)` for task.md.

## Current task.md

```
{{task_md}}
```

## Instructions

Review all tasks with status `IMPLEMENTED` in the task.md above.

For each `IMPLEMENTED` task:

1. **Read the implementation file** at the `file` path.
2. **Read the test file** at the `test_file` path.
3. **Evaluate** against the review checklist in your system prompt.
4. **Set status** to `APPROVED` or `REWORK_NEEDED`.
5. **Write review_feedback**: If approving, briefly note what's good. If rejecting, explain exactly what's wrong and how to fix it.

After reviewing all tasks:

6. Write the full updated `task.md` preserving all sections.
