"""Terminal Operator Console for Human Escalation.

Provides a clear, interactive terminal console for an operator to inspect
the paused session, execute manual fixes on the live browser, and resume automation.
"""

from __future__ import annotations
import asyncio
from typing import Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.escalation.handoff import EscalationSession

console = Console()


async def run_operator_console(
    session: EscalationSession,
    auto_commands: list[dict[str, Any]] | None = None,
) -> None:
    """Runs the operator console.
    
    If auto_commands is provided, executes those scripted operator commands sequentially
    before resuming (ideal for automated demonstration/testing).
    """
    state = await session.get_state_summary()

    console.print(Panel.fit(
        f"[bold red]HUMAN INTERVENTION REQUIRED[/bold red]\n"
        f"[yellow]Reason:[/yellow] {state['reason']}\n"
        f"[yellow]Step:[/yellow] {state['step_index']}\n"
        f"[yellow]URL:[/yellow] {state['url']}\n"
        f"[yellow]Title:[/yellow] {state['title']}\n"
        f"[yellow]Screenshot Saved:[/yellow] {state['screenshot_path']}",
        title="Escalation Operator Console",
        border_style="red",
    ))

    # Show top interactive elements
    table = Table(title="Live Interactive UI Elements")
    table.add_column("Role", style="cyan")
    table.add_column("Name / Text", style="green")
    table.add_column("Current Value", style="magenta")

    for elem in state["interactive_elements"][:15]:
        table.add_row(elem.get("role", ""), elem.get("name", ""), str(elem.get("value", "")))

    console.print(table)

    # Scripted automated operator commands (for non-interactive headless demo / test mode)
    if auto_commands:
        console.print("[cyan]Executing operator scripted intervention commands...[/cyan]")
        for cmd in auto_commands:
            action = cmd.get("action", "")
            role = cmd.get("role")
            name = cmd.get("name")
            text = cmd.get("text")
            console.print(f"[bold green]Operator Action:[/bold green] {action} role={role} name='{name}' text='{text}'")
            record = await session.execute_human_action(action=action, role=role, name=name, text=text)
            console.print(f" -> Result: {record.result}")
            await asyncio.sleep(0.5)

        session.resume()
        console.print("[bold green]Operator intervention completed. Automation resumed.[/bold green]")
        return

    # Interactive loop
    console.print("\n[bold]Commands:[/bold] click <role> <name> | type <role> <name> <text> | resume | exit")
    while session.is_paused:
        try:
            line = input("operator> ").strip()
            if not line:
                continue
            if line == "resume":
                session.resume()
                console.print("[green]Resuming automated session...[/green]")
                break
            if line == "exit":
                console.print("[red]Aborting session.[/red]")
                break

            parts = line.split(" ", 2)
            cmd = parts[0].lower()
            if cmd == "click" and len(parts) >= 3:
                rec = await session.execute_human_action("click", role=parts[1], name=parts[2])
                console.print(f"Action result: {rec.result}")
            elif cmd == "type" and len(parts) >= 3:
                # role name text
                sub_parts = parts[2].split(" ", 1)
                text_val = sub_parts[1] if len(sub_parts) > 1 else ""
                rec = await session.execute_human_action("type", role=parts[1], name=sub_parts[0], text=text_val)
                console.print(f"Action result: {rec.result}")
            else:
                console.print("[yellow]Invalid command. Format: click <role> <name> OR type <role> <name> <text>[/yellow]")
        except (EOFError, KeyboardInterrupt):
            session.resume()
            break
