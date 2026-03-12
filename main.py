#!/usr/bin/env python3
"""
Entry point for the Multi-Agent Feature Implementation Platform.

Usage:
    # Fully interactive (prompts for everything missing):
    python main.py

    # From a Jira ticket (fetches via MCP):
    python main.py --project-dir /path/to/app --jira-ticket PROJ-123

    # From a text description:
    python main.py --project-dir /path/to/app "Add a REST endpoint for user registration"

    # From a file:
    python main.py --project-dir /path/to/app --file ticket.txt

    # Resume after a crash (picks up from task.md state):
    python main.py --resume
"""

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the framework root before anything else reads env vars
load_dotenv(Path(__file__).parent / ".env")

from orchestrator import Orchestrator


def parse_config_md(config_path: Path) -> dict:
    """Read config.md and extract key settings."""
    text = config_path.read_text(encoding="utf-8")
    def field(name: str, default: str = "") -> str:
        match = re.search(rf"\*\*{re.escape(name)}\*\*:\s*(.+)", text)
        return match.group(1).strip() if match else default

    return {
        "model": field("name", "us.anthropic.claude-sonnet-4-20250514-v1:0"),
        "max_tokens": int(field("max_tokens", "8192")),
        "max_iterations": int(field("max_iterations", "10")),
    }


def prompt_missing(label: str, current: str | None, secret: bool = False) -> str:
    """Prompt the user for a value if it's missing or empty."""
    if current:
        return current
    while True:
        if secret:
            import getpass
            value = getpass.getpass(f"  {label}: ").strip()
        else:
            value = input(f"  {label}: ").strip()
        if value:
            return value
        print(f"  (required — please enter a value)")


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Agent AI Feature Implementation Platform",
    )

    # All arguments are optional — we prompt for anything missing
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("description", nargs="?",
                             help="JIRA ticket change description (text)")
    input_group.add_argument("--jira-ticket", "-j",
                             help="Jira ticket key (e.g., PROJ-123)")
    input_group.add_argument("--file", "-f",
                             help="Read JIRA description from a file")

    parser.add_argument("--project-dir",
                        help="Path to the external Spring Boot Java 21 project")
    parser.add_argument("--model", "-m",
                        help="Override Claude model from config.md")
    parser.add_argument("--max-iterations", type=int,
                        help="Override max iterations")
    parser.add_argument("--resume", "-r", action="store_true",
                        help="Resume from a previous crashed run using existing task.md")
    args = parser.parse_args()

    base_dir = Path(__file__).parent.resolve()
    config = parse_config_md(base_dir / "config.md")

    print(f"\n{'='*60}")
    print("  MULTI-AGENT FEATURE IMPLEMENTATION PLATFORM")
    print(f"{'='*60}\n")

    # ── 1. AWS Bedrock bearer token ──────────────────────────────────────

    bearer_token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "").strip()
    if not bearer_token:
        print("  AWS_BEARER_TOKEN_BEDROCK not found in environment (~/.bashrc).")
        bearer_token = prompt_missing("AWS_BEARER_TOKEN_BEDROCK", None, secret=True)
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bearer_token

    # ── 2. Detect resume opportunity ────────────────────────────────────

    task_md_path = base_dir / "shared" / "task.md"
    resume = args.resume

    if not resume and task_md_path.exists():
        print("  Found existing task.md from a previous run.")
        choice = input("  Resume from where it left off? [y/N]: ").strip().lower()
        resume = choice in ("y", "yes")

    if resume and not task_md_path.exists():
        print("  WARNING: --resume was requested but no task.md found. Starting fresh.\n")
        resume = False

    # ── 3. Gather inputs (project dir + JIRA info) ──────────────────────
    #    When resuming, we pull these from the existing task.md so the user
    #    doesn't have to re-enter everything after a crash.

    jira_desc = None
    jira_ticket_key = None

    if resume:
        task_content = task_md_path.read_text(encoding="utf-8")

        # Extract project_path from task.md metadata
        proj_match = re.search(r"\*\*project_path\*\*:\s*(.+)", task_content)
        project_dir = args.project_dir or (proj_match.group(1).strip() if proj_match else None)
        if not project_dir:
            project_dir = prompt_missing("Path to your Spring Boot project", None)
        project_dir = str(Path(project_dir).resolve())

        if not Path(project_dir).exists():
            print(f"\n  ERROR: Directory not found: {project_dir}")
            sys.exit(1)
        if not (Path(project_dir) / "pom.xml").exists():
            print(f"\n  ERROR: No pom.xml found in {project_dir}")
            sys.exit(1)

        # Extract JIRA info from task.md metadata
        desc_match = re.search(r"\*\*description\*\*:\s*(.+)", task_content)
        ticket_match = re.search(r"\*\*jira_ticket\*\*:\s*(\S+)", task_content)
        jira_desc = desc_match.group(1).strip() if desc_match else "Resumed from task.md"
        jira_ticket_key = ticket_match.group(1).strip() if ticket_match else None

        # Parse current state for display
        phase_match = re.search(r"\*\*current_phase\*\*:\s*(\S+)", task_content)
        iter_match = re.search(r"\*\*iteration\*\*:\s*(\d+)", task_content)
        print(f"  [resume] Iteration : {iter_match.group(1) if iter_match else '?'}")
        print(f"  [resume] Phase     : {phase_match.group(1) if phase_match else '?'}")
        print(f"  [resume] Ticket    : {jira_ticket_key or 'N/A'}")
        print(f"  [resume] Project   : {project_dir}")

    else:
        # ── Normal (non-resume) input collection ─────────────────────

        project_dir = args.project_dir
        if not project_dir:
            print("  No --project-dir provided.")
            project_dir = prompt_missing(
                "Path to your Spring Boot project", None
            )

        project_dir = str(Path(project_dir).resolve())

        if not Path(project_dir).exists():
            print(f"\n  ERROR: Directory not found: {project_dir}")
            project_dir = prompt_missing(
                "Path to your Spring Boot project (try again)", None
            )
            project_dir = str(Path(project_dir).resolve())

        if not (Path(project_dir) / "pom.xml").exists():
            print(f"\n  ERROR: No pom.xml found in {project_dir}")
            sys.exit(1)

        if args.jira_ticket:
            jira_ticket_key = args.jira_ticket.strip().upper()
        elif args.file:
            jira_desc = Path(args.file).read_text(encoding="utf-8").strip()
        elif args.description:
            jira_desc = args.description
        else:
            # Nothing provided — ask the user how they want to supply input
            print("  How would you like to provide the JIRA ticket info?\n")
            print("    1. Enter a Jira ticket key (e.g., PROJ-123)")
            print("    2. Type a description now")
            print("    3. Provide a file path\n")
            choice = prompt_missing("Choose [1/2/3]", None)

            if choice == "1":
                jira_ticket_key = prompt_missing(
                    "Jira ticket key (e.g., PROJ-123)", None
                ).strip().upper()
            elif choice == "3":
                file_path = prompt_missing("Path to description file", None)
                jira_desc = Path(file_path).read_text(encoding="utf-8").strip()
            else:
                jira_desc = prompt_missing("Describe the feature to implement", None)

        # ── Fetch Jira ticket via MCP if needed ──────────────────────

        if jira_ticket_key and not jira_desc:
            jira_token = os.environ.get("JIRA_PERSONAL_ACCESS_TOKEN", "").strip()
            if not jira_token:
                print("\n  Jira PAT not found in .env or environment.")
                jira_token = prompt_missing("JIRA_PERSONAL_ACCESS_TOKEN", None, secret=True)
                os.environ["JIRA_PERSONAL_ACCESS_TOKEN"] = jira_token

            jira_email = os.environ.get("JIRA_EMAIL", "").strip()
            if not jira_email:
                print("  Jira email not found in .env or environment.")
                jira_email = prompt_missing("JIRA_EMAIL (e.g., you@company.com)", None)
                os.environ["JIRA_EMAIL"] = jira_email

            print(f"\n  Fetching ticket {jira_ticket_key} from Jira MCP server…\n")
            try:
                from jira_mcp import fetch_ticket
                jira_desc = fetch_ticket(str(base_dir), jira_ticket_key)
            except Exception as e:
                print(f"  ERROR: Failed to fetch Jira ticket: {e}")
                print("  Falling back to manual description.\n")
                jira_desc = prompt_missing(
                    f"Describe the feature for {jira_ticket_key}", None
                )

    # ── 4. Run ──────────────────────────────────────────────────────────

    model = args.model or config["model"]
    max_iters = args.max_iterations or config["max_iterations"]

    orch = Orchestrator(
        base_dir=str(base_dir),
        project_root=project_dir,
        jira_description=jira_desc,
        jira_ticket_key=jira_ticket_key,
        model=model,
        max_tokens=config["max_tokens"],
        max_iterations=max_iters,
        resume=resume,
    )
    result = orch.run()

    # Final output
    print(f"\n{'='*60}")
    if result["success"]:
        print(f"  RESULT: SUCCESS in {result['iterations']} iteration(s)")
    else:
        print(f"  RESULT: INCOMPLETE — {result['message']}")
    print(f"{'='*60}\n")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
