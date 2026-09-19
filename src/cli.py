"""Main Command Line Interface for Computer-Use Automation System.

Supports:
- discover: Runs LLM-driven discovery against real live UI and compiles artifact
- replay: Executes deterministic replay with typed inputs and error taxonomy
- escalate-test: Executes escalation demo with broken locator and human takeover
- serve: Launches interactive Web Dashboard & Operator Console on port 3000
"""

from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agent.loop import DiscoveryAgent
from src.agent.model_client import GeminiDiscoveryClient
from src.artifact.recorder import ArtifactRecorder
from src.artifact.schema import CapabilityArtifact, Locator, Step
from src.escalation.handoff import EscalationSession
from src.escalation.operator_cli import run_operator_console
from src.replay.executor import ReplayEngine

console = Console()


def parse_params(param_list: list[str] | None) -> dict[str, str]:
    """Parses key=value strings into a dictionary."""
    params: dict[str, str] = {}
    if not param_list:
        return params
    for item in param_list:
        if "=" in item:
            k, v = item.split("=", 1)
            params[k.strip()] = v.strip()
    return params


async def handle_discover(args: argparse.Namespace) -> None:
    """Executes the LLM discovery run."""
    console.print(Panel(
        f"[bold cyan]Discovery Goal:[/bold cyan] {args.goal}\n"
        f"[bold cyan]Target URL:[/bold cyan] {args.url}\n"
        f"[bold cyan]Headless:[/bold cyan] {args.headless}",
        title="[bold green]Starting LLM Computer-Use Discovery[/bold green]",
    ))

    client = GeminiDiscoveryClient()
    agent = DiscoveryAgent(model_client=client, max_steps=args.max_steps, timeout_seconds=args.timeout)

    try:
        transcript = await agent.run(
            goal=args.goal,
            entry_url=args.url,
            headless=args.headless,
        )
    except Exception as e:
        console.print(f"[bold red]Discovery encountered an error: {e}[/bold red]")
        sys.exit(1)

    console.print(Panel(
        f"[bold]Success:[/bold] {transcript.success}\n"
        f"[bold]Reason:[/bold] {transcript.reason}\n"
        f"[bold]Steps Executed:[/bold] {len(transcript.steps)}\n"
        f"[bold]Evidence Directory:[/bold] {transcript.evidence_dir}",
        title="[bold green]Discovery Complete[/bold green]",
    ))

    # Compile and save capability artifact
    if transcript.success:
        artifact = ArtifactRecorder.compile_saucedemo_checkout(
            transcript=transcript,
            artifact_id=args.artifact_id,
        )
        saved_path = ArtifactRecorder.save_artifact(artifact)
        console.print(f"[bold green][SUCCESS] Compiled capability artifact saved to:[/bold green] {saved_path}")


async def handle_replay(args: argparse.Namespace) -> None:
    """Executes deterministic replay without LLM."""
    artifact_path = Path("artifacts") / f"{args.artifact}.json"
    if not artifact_path.exists():
        console.print(f"[bold red]Artifact file not found: {artifact_path}[/bold red]")
        sys.exit(1)

    with open(artifact_path, "r", encoding="utf-8") as f:
        artifact_data = json.load(f)
    artifact = CapabilityArtifact.model_validate(artifact_data)

    params = parse_params(args.params)

    console.print(Panel(
        f"[bold cyan]Artifact:[/bold cyan] {artifact.id} (v{artifact.version})\n"
        f"[bold cyan]Target App:[/bold cyan] {artifact.target_app}\n"
        f"[bold cyan]Supplied Params:[/bold cyan] {list(params.keys())}\n"
        f"[bold cyan]Execution Mode:[/bold cyan] Deterministic (Zero LLM in loop)",
        title="[bold blue]Starting Deterministic Replay[/bold blue]",
    ))

    engine = ReplayEngine()
    result = await engine.execute(
        artifact=artifact,
        params=params,
        headless=args.headless,
    )

    status_color = "green" if result.status == "success" else "yellow" if result.status == "business_outcome" else "red"
    console.print(Panel(
        f"[bold]Status:[/bold] [{status_color}]{result.status.upper()}[/{status_color}]\n"
        f"[bold]Outcome Code:[/bold] {result.outcome_code or 'N/A'}\n"
        f"[bold]Message:[/bold] {result.message}\n"
        f"[bold]Extracted Outputs:[/bold] {json.dumps(result.outputs, indent=2)}\n"
        f"[bold]Evidence Saved:[/bold] {result.evidence_path}",
        title="[bold]Replay Result Summary[/bold]",
        border_style=status_color,
    ))


async def handle_escalate_test(args: argparse.Namespace) -> None:
    """Demonstrates live session pause, human intervention, and resumption."""
    from src.escalation.handoff import run_escalation_demo

    console.print(Panel(
        "[bold yellow]Simulating Broken Locator to Test Human Escalation on Live Browser Session[/bold yellow]\n"
        "1. Replay starts on live browser session.\n"
        "2. Step hits an intentionally broken locator -> LOCATOR_NOT_FOUND.\n"
        "3. Session is paused; human operator takes over.\n"
        "4. Operator performs manual fix in console.\n"
        "5. Control is handed back -> session resumes to completion.",
        title="Human Escalation Test Scenario",
    ))

    result = await run_escalation_demo(headless=args.headless, non_interactive=args.non_interactive)
    for line in result["events"]:
        console.print(f"[cyan]{line}[/cyan]")
    console.print(
        f"[bold green][SUCCESS] Flow completed after human intervention! "
        f"Final Total: {result['final_total']}[/bold green]"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Computer-Use Automation System CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # discover
    disc_parser = subparsers.add_parser("discover", help="Run LLM discovery loop")
    disc_parser.add_argument("--goal", required=True, help="Natural language goal")
    disc_parser.add_argument("--url", default="https://www.saucedemo.com", help="Entry URL")
    disc_parser.add_argument("--artifact-id", default="checkout_backpack_v1", help="Artifact ID")
    disc_parser.add_argument("--max-steps", type=int, default=25, help="Max discovery steps")
    disc_parser.add_argument("--timeout", type=int, default=240, help="Timeout in seconds")
    disc_parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True, help="Run browser in headless mode (or --no-headless)")
    disc_parser.add_argument("--headed", dest="headless", action="store_false", help="Run browser in visible (headed) mode")

    # replay
    rep_parser = subparsers.add_parser("replay", help="Run deterministic replay")
    rep_parser.add_argument("--artifact", required=True, help="Artifact ID (e.g. checkout_backpack_v1)")
    rep_parser.add_argument("--params", nargs="*", help="Key=value parameters (e.g. username=standard_user password=secret_sauce)")
    rep_parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True, help="Run browser in headless mode (or --no-headless)")
    rep_parser.add_argument("--headed", dest="headless", action="store_false", help="Run browser in visible (headed) mode")

    # escalate-test
    esc_parser = subparsers.add_parser("escalate-test", help="Test live session escalation and takeover")
    esc_parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True, help="Run browser in headless mode (or --no-headless)")
    esc_parser.add_argument("--headed", dest="headless", action="store_false", help="Run browser in visible (headed) mode")
    esc_parser.add_argument("--non-interactive", action=argparse.BooleanOptionalAction, default=True, help="Run scripted operator fix for CI/demo")

    # serve
    srv_parser = subparsers.add_parser("serve", help="Launch interactive Web App & Operator Console at localhost:3000")
    srv_parser.add_argument("--port", type=int, default=3000, help="Server port (default: 3000)")
    srv_parser.add_argument("--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)")

    args = parser.parse_args()

    if args.command == "discover":
        asyncio.run(handle_discover(args))
    elif args.command == "replay":
        asyncio.run(handle_replay(args))
    elif args.command == "escalate-test":
        asyncio.run(handle_escalate_test(args))
    elif args.command == "serve":
        from src.web.app import start_server
        start_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
