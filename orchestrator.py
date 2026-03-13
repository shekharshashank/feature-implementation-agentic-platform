"""
Orchestrator — the main loop.

Runs the 4-agent pipeline (planner → implementer → reviewer → tester)
in a loop until all tasks are DONE and tests pass, or max iterations
is reached and it asks the user for help.

Supports crash recovery: if the process dies mid-run, restarting with
--resume (or auto-detected) picks up from the last phase recorded in
task.md instead of starting from scratch.

All agent behavior is defined in .md files. This file only handles:
  - Sequencing agents
  - Loading/rendering prompt templates
  - Checking completion
  - Counting iterations
  - Crash recovery / resume
  - User-assistance fallback
"""

import re
from pathlib import Path

from agent_runner import AgentRunner, load_agent_config, load_prompt_template

# Pipeline ordering — used by the resume logic to figure out where to restart.
_PHASE_AGENTS = ["planner", "implementer", "reviewer", "tester"]
_PHASE_TO_INDEX = {
    "PLANNING": 0,
    "IMPLEMENTING": 1,
    "REVIEWING": 2,
    "TESTING": 3,
}


class Orchestrator:
    def __init__(
        self,
        base_dir: str,
        project_root: str,
        jira_description: str,
        jira_ticket_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 8192,
        max_iterations: int = 10,
        resume: bool = False,
    ):
        self.base_dir = Path(base_dir)
        self.project_root = project_root
        self.jira_description = jira_description
        self.jira_ticket_key = jira_ticket_key or "JIRA-001"
        self.model = model
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations
        self.resume = resume

        # task.md lives inside the framework's shared/ dir, NOT in the external project
        self.task_md_path = self.base_dir / "shared" / "task.md"

        # skill.md lives under the framework's skills/ dir, keyed by project name
        project_name = Path(project_root).resolve().name
        self.skill_md_path = self.base_dir / "skills" / f"{project_name}.md"

        # Load agent configs from .md files (once)
        agents_dir = self.base_dir / "agents"
        self.agent_configs = {
            "planner":     load_agent_config(str(agents_dir / "planner-agent.md")),
            "implementer": load_agent_config(str(agents_dir / "implementer-agent.md")),
            "reviewer":    load_agent_config(str(agents_dir / "reviewer-agent.md")),
            "tester":      load_agent_config(str(agents_dir / "tester-agent.md")),
        }

        self.runner = AgentRunner(
            project_root=project_root,
            task_md_path=str(self.task_md_path),
            skill_md_path=str(self.skill_md_path),
            model=model,
            max_tokens=max_tokens,
        )

    # ── Public API ──────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Main loop. Returns {success: bool, iterations: int, message: str}.
        """
        self._print_banner()

        skill_md = self._read_skill_md()
        if skill_md:
            print(f"  [orchestrator] Found skill.md in project — agents will use cached knowledge")

        if self.resume and self.task_md_path.exists():
            result = self._run_with_resume()
        else:
            # ── Fresh run ────────────────────────────────────────────
            self._cleanup_stale_task_md()
            self._clarify_requirements()

            result = self._run_iterations(1, self.max_iterations)
            if not result:
                result = self._ask_user_for_help()

        # On success, capture project learnings into skill.md
        if result["success"]:
            self._generate_skill_md(result["iterations"])

        return result

    # ── Resume logic ──────────────────────────────────────────────────

    def _run_with_resume(self) -> dict:
        """Resume from where the previous run left off based on task.md."""
        state = self._parse_resume_state()
        start_iteration = state["iteration"]
        phase = state["phase"]

        # Nothing to resume if the previous run already finished
        if phase in ("COMPLETE", "NEEDS_USER_HELP"):
            print(f"\n  [orchestrator] Previous run ended with phase: {phase}. Nothing to resume.")
            return {
                "success": phase == "COMPLETE",
                "iterations": start_iteration,
                "message": f"Previous run ended with phase: {phase}",
            }

        print(f"\n  [orchestrator] RESUMING from iteration {start_iteration}, phase: {phase}")

        start_idx = _PHASE_TO_INDEX.get(phase, 0)

        # Edge case: if planner was running on iteration 1 but already created
        # tasks, skip it — re-running with planner-first.md would recreate
        # task.md from scratch and lose the work already done.
        if phase == "PLANNING" and start_iteration == 1:
            task_md = self._read_task_md()
            if "### Task " in task_md:
                start_idx = 1  # skip planner, jump to implementer
                print(f"  [orchestrator] Planner already created tasks — skipping to implementer")

        agents_to_run = _PHASE_AGENTS[start_idx:]
        print(f"  [orchestrator] Resuming agents: {', '.join(agents_to_run)}")

        # ── Run remaining phases for the interrupted iteration ──
        print(f"\n{'='*60}")
        print(f"  ITERATION {start_iteration} / {self.max_iterations} (resumed)")
        print(f"{'='*60}")

        for agent_name in agents_to_run:
            self._run_phase(agent_name, start_iteration)

        task_md = self._read_task_md()
        if self._is_complete(task_md):
            self._set_phase(task_md, "COMPLETE", start_iteration)
            print(f"\n{'='*60}")
            print(f"  SUCCESS — All tasks DONE, all tests PASSING")
            print(f"  Completed in {start_iteration} iteration(s)")
            print(f"{'='*60}")
            return {"success": True, "iterations": start_iteration,
                    "message": "All tasks completed and tests passing."}

        print(f"\n  [orchestrator] Resumed iteration {start_iteration} not complete. Continuing…")

        # ── Continue with subsequent full iterations ──
        if start_iteration < self.max_iterations:
            result = self._run_iterations(start_iteration + 1, self.max_iterations)
            if result:
                return result

        return self._ask_user_for_help()

    def _parse_resume_state(self) -> dict:
        """Parse task.md to determine where to resume from."""
        task_md = self._read_task_md()

        phase_match = re.search(r"\*\*current_phase\*\*:\s*(\S+)", task_md)
        phase = phase_match.group(1) if phase_match else "PLANNING"

        iter_match = re.search(r"\*\*iteration\*\*:\s*(\d+)", task_md)
        iteration = int(iter_match.group(1)) if iter_match else 1

        desc_match = re.search(r"\*\*description\*\*:\s*(.+)", task_md)
        description = desc_match.group(1).strip() if desc_match else ""

        ticket_match = re.search(r"\*\*jira_ticket\*\*:\s*(\S+)", task_md)
        ticket = ticket_match.group(1).strip() if ticket_match else ""

        return {
            "phase": phase,
            "iteration": iteration,
            "description": description,
            "ticket": ticket,
        }

    def _run_iterations(self, start: int, end: int) -> dict | None:
        """Run full iterations from *start* to *end* inclusive.

        Returns a success dict if all tasks complete, or None if we
        exhaust the range without completing.
        """
        for iteration in range(start, end + 1):
            print(f"\n{'='*60}")
            print(f"  ITERATION {iteration} / {self.max_iterations}")
            print(f"{'='*60}")

            self._run_phase("planner", iteration)
            self._run_phase("implementer", iteration)
            self._run_phase("reviewer", iteration)
            self._run_phase("tester", iteration)

            task_md = self._read_task_md()
            if self._is_complete(task_md):
                self._set_phase(task_md, "COMPLETE", iteration)
                print(f"\n{'='*60}")
                print(f"  SUCCESS — All tasks DONE, all tests PASSING")
                print(f"  Completed in {iteration} iteration(s)")
                print(f"{'='*60}")
                return {"success": True, "iterations": iteration,
                        "message": "All tasks completed and tests passing."}

            print(f"\n  [orchestrator] Iteration {iteration} not complete. Continuing…")

        return None

    # ── Internals ───────────────────────────────────────────────────────

    def _run_phase(self, agent_name: str, iteration: int) -> None:
        """Run a single agent phase."""
        task_md = self._read_task_md()

        # Only update phase marker if task.md already exists
        # (on iteration 1 the planner creates it, so it won't exist yet)
        if task_md:
            phase_map = {
                "planner": "PLANNING", "implementer": "IMPLEMENTING",
                "reviewer": "REVIEWING", "tester": "TESTING",
            }
            self._set_phase(task_md, phase_map[agent_name], iteration)

        # Build the user prompt from the template
        prompt = self._render_prompt(agent_name, iteration)

        # Run the agent
        self.runner.run(self.agent_configs[agent_name], prompt)

    def _clarify_requirements(self) -> None:
        """
        Ask the planner to evaluate the JIRA description. If it's unclear,
        collect answers from the user and loop until the planner says CLEAR.
        """
        print(f"\n{'='*60}")
        print("  CLARIFICATION PHASE")
        print(f"{'='*60}")

        clarification_context = ""  # accumulates Q&A across rounds

        for round_num in range(1, 6):  # max 5 clarification rounds
            print(f"\n  [clarify] Round {round_num} — asking planner to evaluate requirements…")

            prompt = self._render_clarify_prompt(clarification_context)
            response = self.runner.run(self.agent_configs["planner"], prompt)

            if "STATUS: CLEAR" in response:
                print(f"\n  [clarify] Requirements are clear. Proceeding to implementation.")
                return

            # Extract questions from the response
            questions = self._extract_questions(response)
            if not questions:
                # Planner didn't follow format but also didn't say CLEAR.
                # Treat the entire response as needing clarification.
                print(f"\n  [clarify] Planner response:")
                print(f"  {response[:500]}")
                questions = [response]

            # Show questions to user and collect answers
            print(f"\n{'─'*60}")
            print("  The JIRA description needs more detail.")
            print("  Please answer the following questions:")
            print(f"{'─'*60}")

            answers = []
            for i, q in enumerate(questions, 1):
                print(f"\n  Q{i}: {q}")
                answer = input(f"  A{i}: ").strip()
                if answer:
                    answers.append(f"Q: {q}\nA: {answer}")

            if not answers:
                print("  [clarify] No answers provided. Proceeding with what we have.")
                return

            # Accumulate context for next round
            round_block = f"\n### Clarification Round {round_num}\n" + "\n\n".join(answers)
            clarification_context += round_block

            # Also append to the stored JIRA description so all agents see it
            self.jira_description += f"\n\n--- Additional Details (Round {round_num}) ---\n"
            for a in answers:
                self.jira_description += a + "\n"

        print(f"\n  [clarify] Max clarification rounds reached. Proceeding with available info.")

    def _render_clarify_prompt(self, clarification_context: str) -> str:
        """Render the planner-clarify prompt template."""
        template = str(self.base_dir / "prompts" / "planner-clarify.md")

        ctx_block = ""
        if clarification_context:
            ctx_block = (
                "\n## Previous Clarifications\n"
                "The user has already provided these answers in earlier rounds:\n"
                f"{clarification_context}\n\n"
                "Evaluate whether these answers resolve all ambiguities. "
                "If more info is still needed, ask only about what remains unclear.\n"
            )

        variables = {
            "jira_description": self.jira_description,
            "project_path": self.project_root,
            "clarification_context": ctx_block,
        }
        return load_prompt_template(template, variables)

    @staticmethod
    def _extract_questions(response: str) -> list[str]:
        """Pull numbered questions from the planner's clarification response."""
        questions = []
        for line in response.split("\n"):
            stripped = line.strip()
            # Match lines like "1. Should the..." or "2. What format..."
            if stripped and len(stripped) > 3:
                match = re.match(r"^\d+\.\s+(.+)", stripped)
                if match:
                    questions.append(match.group(1))
        return questions

    def _render_prompt(self, agent_name: str, iteration: int) -> str:
        """Load and render the appropriate prompt template."""
        prompts_dir = self.base_dir / "prompts"
        task_md = self._read_task_md()
        skill_md = self._read_skill_md()
        variables = {
            "iteration": str(iteration),
            "task_md": task_md if task_md else "(task.md does not exist yet — you must create it)",
            "jira_description": self.jira_description,
            "jira_ticket": self.jira_ticket_key,
            "max_iterations": str(self.max_iterations),
            "project_path": self.project_root,
            "skill_md": skill_md if skill_md else "(no skill.md yet — first run on this project)",
        }

        if agent_name == "planner":
            if iteration == 1:
                template = str(prompts_dir / "planner-first.md")
            else:
                template = str(prompts_dir / "planner-next.md")
        else:
            template = str(prompts_dir / f"{agent_name}.md")

        return load_prompt_template(template, variables)

    def _cleanup_stale_task_md(self) -> None:
        """Remove any leftover task.md from a previous run."""
        if self.task_md_path.exists():
            self.task_md_path.unlink()
            print(f"  [orchestrator] Removed stale {self.task_md_path}")
        print(f"  [orchestrator] Planner agent will create task.md on first iteration")

    # ── skill.md — project knowledge cache ────────────────────────────

    def _read_skill_md(self) -> str:
        """Read skill.md from skills/<project-name>.md, if it exists."""
        if self.skill_md_path.exists():
            return self.skill_md_path.read_text(encoding="utf-8")
        return ""

    def _generate_skill_md(self, final_iteration: int) -> None:
        """After a successful run, generate/update skill.md with project learnings."""
        print(f"\n{'─'*60}")
        print(f"  GENERATING skill.md — capturing project learnings")
        print(f"  Target: {self.skill_md_path}")
        print(f"{'─'*60}")

        task_md = self._read_task_md()
        skill_md = self._read_skill_md()

        variables = {
            "project_path": self.project_root,
            "task_md": task_md,
            "existing_skill_md": skill_md if skill_md else "(no existing skill.md — creating from scratch)",
            "iteration": str(final_iteration),
        }

        template = str(self.base_dir / "prompts" / "skill-writer.md")
        prompt = load_prompt_template(template, variables)

        self.runner.run(self.agent_configs["planner"], prompt)
        print(f"  skill.md updated at {self.skill_md_path}")

    def _read_task_md(self) -> str:
        if self.task_md_path.exists():
            return self.task_md_path.read_text(encoding="utf-8")
        return ""

    def _set_phase(self, task_md: str, phase: str, iteration: int) -> None:
        """Update current_phase and iteration in task.md."""
        lines = task_md.split("\n")
        new_lines = []
        for line in lines:
            if line.strip().startswith("- **current_phase**:"):
                new_lines.append(f"- **current_phase**: {phase}")
            elif line.strip().startswith("- **iteration**:"):
                new_lines.append(f"- **iteration**: {iteration}")
            else:
                new_lines.append(line)
        self.task_md_path.write_text("\n".join(new_lines), encoding="utf-8")

    def _is_complete(self, task_md: str) -> bool:
        """
        True when:
          1. At least one task exists
          2. Every task status is DONE
          3. Test Results status is PASSING
        """
        # Must have tasks
        if "### Task " not in task_md:
            return False

        # All task statuses must be DONE
        status_pattern = re.compile(r"-\s*\*\*status\*\*:\s*(\S+)")
        statuses = status_pattern.findall(task_md)
        # Filter — only statuses inside ### Task sections (skip metadata)
        task_section = task_md.split("## Tasks")[-1].split("## Test Results")[0] if "## Tasks" in task_md else ""
        task_statuses = status_pattern.findall(task_section)
        if not task_statuses:
            return False
        if any(s != "DONE" for s in task_statuses):
            return False

        # Tests must be passing
        if "**status**: PASSING" not in task_md:
            return False

        return True

    def _ask_user_for_help(self) -> dict:
        """Prompt the user for guidance after max iterations."""
        task_md = self._read_task_md()
        self._set_phase(task_md, "NEEDS_USER_HELP", self.max_iterations)

        print(f"\n{'='*60}")
        print("  MAX ITERATIONS REACHED — USER ASSISTANCE NEEDED")
        print(f"{'='*60}")
        print()

        # Show summary of non-DONE tasks
        for line in task_md.split("\n"):
            if (line.startswith("### Task") or "**status**" in line
                    or "**review_feedback**" in line or "**failure_details**" in line):
                print(f"  {line}")

        print()
        print("  Options:")
        print("    1. Type guidance text and press Enter — runs one more iteration with your input")
        print("    2. Type 'quit' — abort")
        print()

        user_input = input("  Your guidance (or 'quit'): ").strip()
        if user_input.lower() == "quit":
            return {"success": False, "iterations": self.max_iterations,
                    "message": "Aborted by user."}

        # Append guidance to task.md
        content = self._read_task_md()
        content += (
            f"\n\n## User Guidance (after {self.max_iterations} iterations)\n"
            f"{user_input}\n"
        )
        self.task_md_path.write_text(content, encoding="utf-8")

        # Run one bonus iteration
        bonus = self.max_iterations + 1
        print(f"\n  Running bonus iteration {bonus} with your guidance…")
        self._run_phase("planner", bonus)
        self._run_phase("implementer", bonus)
        self._run_phase("reviewer", bonus)
        self._run_phase("tester", bonus)

        task_md = self._read_task_md()
        if self._is_complete(task_md):
            return {"success": True, "iterations": bonus,
                    "message": "Completed with user guidance."}
        return {"success": False, "iterations": bonus,
                "message": "Still incomplete after user guidance."}

    def _print_banner(self) -> None:
        skill_exists = self.skill_md_path.exists()
        print(f"\n{'='*60}")
        print("  MULTI-AGENT FEATURE IMPLEMENTATION PLATFORM")
        print(f"{'='*60}")
        print(f"  Model       : {self.model}")
        print(f"  Project     : {self.project_root}")
        print(f"  Max iters   : {self.max_iterations}")
        print(f"  Ticket      : {self.jira_ticket_key}")
        print(f"  Skill cache : {'YES — ' + str(self.skill_md_path) if skill_exists else 'NO — first run on this project'}")
        desc = self.jira_description
        if len(desc) > 80:
            desc = desc[:80] + "…"
        print(f"  Description : {desc}")
        print(f"{'='*60}")
