# Planner Prompt — Iteration {{iteration}}

This is **iteration {{iteration}}**. Previous work has been done but issues remain.

## External Project

The Spring Boot project is located at: `{{project_path}}`

All file tools operate relative to this project root. Use `read_file("task.md")` / `write_file("task.md", ...)` for task.md.

## Project Knowledge (from previous runs)

{{skill_md}}

## Current task.md

```
{{task_md}}
```

## Instructions

1. Review tasks with status `REWORK_NEEDED` — read their `review_feedback` carefully.
2. Review the `## Test Results` section — note any failing tests and their error messages.
3. For tasks needing rework:
   - Update the task `description` with specific fixes based on feedback.
   - Copy the reviewer's feedback into `rework_notes` for the implementer.
   - Reset their status to `PLANNED`.
4. If test failures point to issues in `APPROVED` tasks, change them back to `PLANNED` with fix instructions.
5. Do NOT modify tasks that are already `DONE`.
6. Write the full updated `task.md`.
7. Add an entry to `## Iteration History` summarizing what was re-planned.
