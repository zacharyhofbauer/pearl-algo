"""Help and cheat sheet command for PearlAlgo CLI."""

from __future__ import annotations

import click
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich import box

console = Console()


def get_cheat_sheet_path(short: bool = False) -> Path:
    """Get path to cheat sheet markdown file."""
    # Try to find cheat sheet relative to project root
    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent.parent.parent.parent

    if short:
        cheat_sheet = project_root / "CHEAT_SHEET_SHORT.md"
    else:
        cheat_sheet = project_root / "CHEAT_SHEET.md"

    if not cheat_sheet.exists():
        # Fallback: try current directory
        if short:
            cheat_sheet = Path("CHEAT_SHEET_SHORT.md")
        else:
            cheat_sheet = Path("CHEAT_SHEET.md")

    return cheat_sheet


def get_sections(content: str) -> list[tuple[str, int]]:
    """Extract section headers and their line numbers."""
    sections = []
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("## "):
            section_name = line.replace("## ", "").strip()
            sections.append((section_name, i))
    return sections


@click.command(name="help")
@click.option(
    "--section",
    "-s",
    help="Show specific section (e.g., 'trading', 'dashboard', 'troubleshooting')",
)
@click.option(
    "--full",
    "--long",
    "-f",
    is_flag=True,
    help="Show full comprehensive cheat sheet (default: short quick reference)",
)
@click.option(
    "--pager",
    "-p",
    is_flag=True,
    default=True,
    help="Use pager for long output (default: True)",
)
@click.option(
    "--no-pager",
    is_flag=True,
    help="Disable pager and show all content at once",
)
def help_cmd(
    section: str | None = None,
    full: bool = False,
    pager: bool = True,
    no_pager: bool = False,
) -> None:
    """
    Display the PearlAlgo cheat sheet.

    By default shows quick reference (daily commands). Use --full for comprehensive guide.

    Options:
      --full, --long    Show full comprehensive cheat sheet
      --section <name>  Show specific section from full version
      --no-pager        Disable pagination
    """
    # Default to short, unless --full is specified
    short = not full
    cheat_sheet_path = get_cheat_sheet_path(short=short)

    if not cheat_sheet_path.exists():
        console.print(f"[red]Error: Cheat sheet not found at {cheat_sheet_path}[/red]")
        console.print("\n[yellow]Available commands:[/yellow]")
        console.print("  pearlalgo status      - System status")
        console.print("  pearlalgo gateway    - Gateway management")
        console.print("  pearlalgo trade      - Start trading")
        console.print("  pearlalgo dashboard  - View dashboard")
        return

    try:
        content = cheat_sheet_path.read_text()

        # If section specified, filter content
        if section:
            lines = content.split("\n")
            filtered_lines = []
            in_section = False
            section_found = False

            for line in lines:
                # Check if this is the section we want
                if line.startswith("## ") and section.lower() in line.lower():
                    in_section = True
                    section_found = True
                    filtered_lines.append(line)
                elif line.startswith("## ") and in_section:
                    # Hit next section, stop
                    break
                elif in_section:
                    filtered_lines.append(line)

            if filtered_lines and section_found:
                content = "\n".join(filtered_lines)
            else:
                # Show available sections
                sections = get_sections(content)
                console.print(f"[yellow]Section '{section}' not found.[/yellow]\n")
                console.print("[cyan]Available sections:[/cyan]")
                for sec_name, _ in sections:
                    console.print(f"  • {sec_name}")
                console.print(
                    "\n[yellow]Showing full cheat sheet instead...[/yellow]\n"
                )

        # Use pager if enabled and not disabled
        use_pager = pager and not no_pager

        # Display header
        console.print()
        if short:
            title = "[bold cyan]🎯 PearlAlgo Quick Reference[/bold cyan]"
            subtitle = "[dim]Daily commands - Use --full for comprehensive guide[/dim]"
        else:
            title = "[bold cyan]🎯 PearlAlgo Complete Cheat Sheet[/bold cyan]"
            subtitle = "[dim]Comprehensive documentation[/dim]"

        console.print(
            Panel.fit(
                f"{title}\n{subtitle}",
                border_style="cyan",
                box=box.DOUBLE,
            )
        )
        console.print()

        # Render markdown
        markdown = Markdown(content)

        if use_pager and console.is_terminal:
            # Use rich pager for better readability (scrollable)
            with console.pager(styles=True):
                console.print(markdown)
        else:
            # Print directly (for non-terminal or when pager disabled)
            console.print(markdown)

        console.print()
        if not section:
            if short:
                console.print(
                    "[dim]💡 For full documentation: 'pearlalgo help --full'[/dim]"
                )
                console.print(
                    "[dim]   Or 'pearlalgo help --section <name>' for specific sections[/dim]"
                )
            else:
                sections = get_sections(content)
                if sections:
                    console.print(
                        "[dim]💡 Tip: Use 'pearlalgo help' (without --full) for quick daily reference[/dim]"
                    )
                    console.print(
                        "[dim]   Or 'pearlalgo help --section <name>' for specific sections[/dim]"
                    )
        console.print()

    except Exception as e:
        console.print(f"[red]Error reading cheat sheet: {e}[/red]")
        import traceback

        if console.is_terminal:
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


@click.command(name="cheat-sheet")
@click.option(
    "--section",
    "-s",
    help="Show specific section (e.g., 'trading', 'dashboard', 'troubleshooting')",
)
@click.option(
    "--full",
    "--long",
    "-f",
    is_flag=True,
    help="Show full comprehensive cheat sheet (default: short quick reference)",
)
@click.option(
    "--pager",
    "-p",
    is_flag=True,
    default=True,
    help="Use pager for long output (default: True)",
)
@click.option(
    "--no-pager",
    is_flag=True,
    help="Disable pager and show all content at once",
)
def cheat_sheet_cmd(
    section: str | None = None,
    full: bool = False,
    pager: bool = True,
    no_pager: bool = False,
) -> None:
    """Alias for 'help' command - displays the cheat sheet."""
    # Call the same function as help_cmd
    help_cmd.callback(section, full, pager, no_pager)


if __name__ == "__main__":
    help_cmd()
