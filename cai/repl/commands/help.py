"""
Help command for CAI REPL.
This module provides commands for displaying help information.
"""
from typing import Dict, List, Optional
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.columns import Columns
    from rich.markdown import Markdown
except ImportError as exc:
    raise ImportError(
        "The 'rich' package is required. Please install it with: "
        "pip install rich"
    ) from exc

from cai.repl.commands.base import (
    Command,
    register_command,
    COMMANDS,
    COMMAND_ALIASES
)

try:
    from cai import is_caiextensions_platform_available
    from caiextensions.platform.base.platform_manager import PlatformManager
    HAS_PLATFORM_EXTENSIONS = True
except ImportError:
    HAS_PLATFORM_EXTENSIONS = False
from cai.repl.commands.mcp import McpCommand # Import McpCommand to access its details if needed

console = Console()


def create_styled_table(
    title: str,
    headers: List[tuple[str, str]],
    header_style: str = "bold white"
) -> Table:
    """Create a styled table with consistent formatting.

    Args:
        title: The table title
        headers: List of (header_name, style) tuples
        header_style: Style for the header row

    Returns:
        A configured Table instance
    """
    table = Table(
        title=title,
        show_header=True,
        header_style=header_style
    )
    for header, style in headers:
        table.add_column(header, style=style)
    return table


def create_notes_panel(
    notes: List[str],
    title: str = "Notes",
    border_style: str = "yellow"
) -> Panel:
    """Create a notes panel with consistent formatting.

    Args:
        notes: List of note strings
        title: Panel title
        border_style: Style for the panel border

    Returns:
        A configured Panel instance
    """
    notes_text = Text.from_markup(
        "\n".join(f"• {note}" for note in notes)
    )
    return Panel(
        notes_text,
        title=title,
        border_style=border_style
    )


class HelpCommand(Command):
    """Command for displaying help information."""

    def __init__(self):
        """Initialize the help command."""
        super().__init__(
            name="/help",
            description=(
                "Display help information about commands "
                "and features"
            ),
            aliases=["/h"]
        )

        # Add subcommands
        self.add_subcommand(
            "memory",
            "Display help for memory commands",
            self.handle_memory
        )
        self.add_subcommand(
            "agent",
            "Display help for agent commands",
            self.handle_agents
        )
        self.add_subcommand(
            "graph",
            "Display help for graph commands",
            self.handle_graph
        )
        self.add_subcommand(
            "platform",
            "Display help for platform commands",
            self.handle_platform
        )
        self.add_subcommand(
            "shell",
            "Display help for shell commands",
            self.handle_shell
        )
        self.add_subcommand(
            "env",
            "Display help for environment commands",
            self.handle_env
        )
        self.add_subcommand(
            "aliases",
            "Display command aliases",
            self.handle_aliases
        )
        self.add_subcommand(
            "model",
            "Display help for model commands",
            self.handle_model
        )
        self.add_subcommand(
            "turns",
            "Display help for turns commands",
            self.handle_turns
        )
        self.add_subcommand(
            "config",
            "Display help for config commands",
            self.handle_config
        )
        self.add_subcommand(
            "virtualization",
            "Display help for virtualization commands",
            self.handle_virtualization
        )
        self.add_subcommand(
            "workspace",
            "Display help for workspace commands",
            self.handle_workspace
        )
        self.add_subcommand(
            "kill",
            "Display help for kill commands",
            self.handle_kill
        )
        self.add_subcommand(
            "flush",
            "Display help for flush commands",
            self.handle_flush
        )
        self.add_subcommand(
            "exit",
            "Display help for exit command",
            self.handle_help_exit
        )
        self.add_subcommand(
            "history",
            "Display help for history command",
            self.handle_help_history
        )
        # Add MCP help subcommand
        self.add_subcommand(
            "mcp",
            "Display help for MCP commands",
            self.handle_mcp_help  # New handler method
        )

        # Add alias handlers as subcommands
        self.add_subcommand("ws", "Display help for workspace commands (alias)", self.handle_ws)
        self.add_subcommand("virt", "Display help for virtualization commands (alias)", self.handle_virt)
        self.add_subcommand("mem", "Display help for memory commands (alias)", self.handle_mem)
        self.add_subcommand("mod", "Display help for model commands (alias)", self.handle_mod)
        self.add_subcommand("s", "Display help for shell commands (alias)", self.handle_s)
        self.add_subcommand("p", "Display help for platform commands (alias)", self.handle_p)
        self.add_subcommand("g", "Display help for graph commands (alias)", self.handle_g)
        self.add_subcommand("e", "Display help for environment commands (alias)", self.handle_e)
        self.add_subcommand("k", "Display help for kill commands (alias)", self.handle_k)
        self.add_subcommand("t", "Display help for turns commands (alias)", self.handle_t)
        self.add_subcommand("a", "Display help for agent commands (alias)", self.handle_a)
        self.add_subcommand("cfg", "Display help for config commands (alias)", self.handle_cfg)
        self.add_subcommand("hist", "Display help for history commands (alias)", self.handle_hist)
        self.add_subcommand("clear", "Display help for flush commands (alias)", self.handle_clear)
        self.add_subcommand("quit", "Display help for exit command (alias)", self.handle_quit)
        self.add_subcommand("h", "Display general help (alias)", self.handle_h)
        # Add MCP alias handler
        self.add_subcommand("m", "Display help for MCP commands (alias)", self.handle_m) # New alias handler

    def handle(self, args: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the help command."""
        if not args:
            # Dynamically import repl module to avoid circular imports
            # and access display_quick_guide function
            try:
                from importlib import import_module
                repl_module = import_module('cai.repl.repl')
                display_quick_guide_func = getattr(repl_module, 'display_quick_guide', None)
                if display_quick_guide_func:
                    display_quick_guide_func()
                # Show standard command list
                return self.handle_help()
            except ImportError:
                # Fallback to just showing help if there's an import error
                return self.handle_help()

        # If arguments are provided, check for subcommands
        subcommand = args[0]
        if subcommand in self.subcommands:
            handler = self.subcommands[subcommand]["handler"]
            return handler(args[1:] if len(args) > 1 else None, messages)

        # If not a known subcommand, show error and general help
        console.print(f"[yellow]Unknown help topic: {subcommand}[/yellow]")
        return self.handle_help()

    def handle_memory(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show help for memory commands."""
        # Get the memory command and show its help
        memory_cmd = next((cmd for cmd in COMMANDS.values()
                          if cmd.name == "/memory"), None)
        if memory_cmd and hasattr(memory_cmd, 'show_help'):
            memory_cmd.show_help()
            return True

        # Fallback if memory command not found or doesn't have show_help
        self.handle_help_memory()
        return True

    def handle_agents(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show help for agent-related features."""
        console.print(Panel(
            "Agents are autonomous AI assistants that can perform specific "
            "tasks.\n\n"
            "[bold]Available Commands:[/bold]\n"
            "• [yellow]/agent [/yellow] - List all available agents\n"
            "• [yellow]/agent <n>[/yellow] - Switch to a specific agent via number\n"
            "• [yellow]/agent <name>[/yellow] - Switch to a specific agent via name\n"
            "agent\n\n"
            "[bold]Examples:[/bold]\n"
            "• [green]/agent redteam_agent[/green] - Switch to the CLI "
            "security testing agent\n"
            "• [green]/agent bug_bounter_agent[/green] - Switch to the "
            "bug bounty agent",
            title="Agent Commands",
            border_style="blue"
        ))
        return True

    def handle_graph(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show help for graph visualization."""
        console.print(Panel(
            "Graph visualization helps understand the agent's step-by-step "
            "process.\n\n"
            "[bold]Available Commands:[/bold]\n"
            "• [yellow]/graph[/yellow] - Display the current conversation graph\n"
            "• [yellow]/g[/yellow] - Alias for /graph\n\n"
            "[bold]Description:[/bold]\n"
            "The graph command displays an ASCII representation of the conversation graph, "
            "showing the interaction between the user and the agent. This helps visualize "
            "the flow of the conversation and the agent's reasoning process.",
            title="Graph Visualization Command (/graph)",
            border_style="blue"
        ))
        return True

    def handle_platform(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show help for platform-specific features."""
        platform_cmd = next(
            (cmd for cmd in COMMANDS.values() if cmd.name == "/platform"),
            None
        )

        if platform_cmd and hasattr(platform_cmd, 'show_help'):
            platform_cmd.show_help()
            return True

        console.print(Panel(
            "Platform commands provide access to platform-specific "
            "features.\n\n"
            "[bold]Available Commands:[/bold]\n"
            "• [yellow]/platform list[/yellow] - List available platforms\n"
            "• [yellow]/platform <platform> <command>[/yellow] - Run "
            "platform-specific command\n\n"
            "[bold]Examples:[/bold]\n"
            "• [green]/platform list[/green] - Show all available platforms\n"
            "• [green]/p list[/green] - Shorthand for platform list",
            title="Platform Commands",
            border_style="blue"
        ))
        return True

    def handle_shell(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show help for shell command execution."""
        console.print(Panel(
            "Shell commands execute system commands directly in the current "
            "environment (host or active container).\n\n"
            "[bold]Available Commands:[/bold]\n"
            "• [yellow]/shell <command> [args...][/yellow] - Execute a shell command\n"
            "• [yellow]/! <command> [args...][/yellow] - Alias for /shell\n"
            "• [yellow]$ <command> [args...][/yellow] - Alias for /shell\n\n"
            "[bold]Execution Environment:[/bold]\n"
            "- If a [cyan]/virtualization[/cyan] container is active, commands run inside it via `docker exec`.\n"
            "- Otherwise, commands run on the host system.\n"
            "- If a [cyan]/workspace[/cyan] is set, commands run in that directory (host or container).\n"
            "- Commands suggesting async execution (nc, python http.server, etc.) run using `os.system`.\n"
            "- Other commands run via `subprocess.Popen` with real-time output.\n"
            "- Use [yellow]Ctrl+C[/yellow] to interrupt the running command.",
            title="Shell Commands (/shell, /!, $)",
            border_style="blue"
        ))
        return True

    def handle_env(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show help for environment variables."""
        console.print(Panel(
            "The /env command displays CAI and CTF related environment "
            "variables currently set in the session.\n\n"
            "[bold]Usage:[/bold]\n"
            "• [yellow]/env[/yellow] - Show all CAI_ and CTF_ environment variables\n"
            "• [yellow]/e[/yellow] - Alias for /env\n\n"
            "[bold]Description:[/bold]\n"
            "This command provides a quick way to view the configuration "
            "derived from environment variables specific to CAI's operation "
            "and any active CTF context. Sensitive values like API keys "
            "will be partially masked.",
            title="Environment Variables Display (/env)",
            border_style="blue"
        ))
        return True

    def handle_aliases(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show all command aliases."""
        return self.handle_help_aliases()

    def handle_model(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show help for model selection."""
        return self.handle_help_model()

    def handle_turns(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show help for managing turns."""
        return self.handle_help_turns()

    def handle_config(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Display help for config commands.

        Args:
            _: Ignored arguments

        Returns:
            True if successful
        """
        return self.handle_help_config()

    def handle_virtualization(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show help for virtualization commands."""
        console.print(Panel(
            "Virtualization commands allow you to run CAI in Docker containers for enhanced "
            "security and tool access. While CAI provides predefined environments, you can use "
            "any Docker container.\n\n"
            "[bold]Available Commands:[/bold]\n"
            "• [yellow]/virtualization[/yellow] - Show all available virtualized environments\n"
            "• [yellow]/virtualization <image_name>[/yellow] - Activate any Docker container by image name\n"
            "• [yellow]/virtualization <image_id>[/yellow] - Activate a predefined container by ID (e.g., sec1, pen1)\n"
            "• [yellow]/virtualization pull <image>[/yellow] - Pull any Docker image without activating\n"
            "• [yellow]/virtualization run <image>[/yellow] - Run any Docker container from an image\n"
            "• [yellow]/virtualization host[/yellow] - Return to host system environment\n\n"
            "[bold]Predefined Environment Categories:[/bold]\n"
            "• [green]Offensive Pentesting[/green] - Tools for pentesting (IDs: pen1-pen5)\n"
            "• [green]Forensic Analysis[/green] - Tools for digital forensics (IDs: for1-for5)\n"
            "• [green]Malware Analysis[/green] - Safe environments for malware (IDs: mal1-mal5)\n"
            "• [green]Reverse Engineering[/green] - Tools for decompiling applications (IDs: rev1-rev5)\n"
            "• [green]Container Security[/green] - Container security scanners (IDs: sec2-sec6)\n\n"
            "[bold]Custom Containers:[/bold]\n"
            "You can use any Docker image available locally or from Docker Hub. CAI will handle "
            "network configuration and workspace mapping automatically.\n\n"
            "[bold]Examples:[/bold]\n"
            "• [green]/virtualization sec1[/green] - Activate CAI environment by ID\n"
            "• [green]/virtualization ubuntu:latest[/green] - Activate standard Ubuntu container\n"
            "• [green]/virtualization python:3.9[/green] - Use a Python development environment\n"
            "• [green]/virtualization pull nginx[/green] - Download nginx image without activating\n"
            "• [green]/virt[/green] - Show all available environments (short form)",
            title="Virtualization Commands",
            border_style="blue"
        ))
        return True

    def handle_workspace(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the workspace help subcommand."""
        return self.handle_help_workspace()

    def handle_kill(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the kill help subcommand."""
        return self.handle_help_kill()

    def handle_flush(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the flush help subcommand."""
        return self.handle_help_flush()

    # Added placeholder help for exit and history
    def handle_help_exit(self) -> bool:
        """Show help for exit command."""
        console.print(Panel(
            "Exits the CAI REPL session.\n\n"
            "[bold]Usage:[/bold]\n"
            "• [yellow]/exit[/yellow]\n"
            "• [yellow]/quit[/yellow] (Alias)\n"
            "• [yellow]Ctrl+D[/yellow] (EOF character)",
            title="Exit Command (/exit, /quit)",
            border_style="red"
        ))
        return True

    def handle_help_history(self, args=None, messages=None):
        """Display help for the history command.
        
        Args:
            args: Optional list of command arguments
            messages: Optional list of conversation messages (unused but needed for compatibility)
        """
        console.print(Panel(
            Markdown("""
            # History Command
            
            The history command displays the conversation history between you and the AI.
            
            ## Usage
            
            ```
            /history
            /h
            ```
            
            This command displays a table showing the conversation history, including:
            - Message number
            - Role (user or assistant)
            - Content (truncated for long messages)
            
            User messages are shown in cyan, and assistant messages in yellow.
            """),
            title="History Command Help",
            border_style="green"
        ))
        return True

    # Alias handlers
    def handle_ws(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /ws alias help."""
        return self.handle_workspace(_, messages)

    def handle_virt(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /virt alias help."""
        return self.handle_virtualization(_, messages)

    def handle_mem(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /mem alias help."""
        return self.handle_memory(_, messages)

    def handle_mod(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /mod alias help."""
        return self.handle_model(_, messages)

    def handle_s(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /s alias help."""
        return self.handle_shell(_, messages)

    def handle_p(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /p alias help."""
        return self.handle_platform(_, messages)

    def handle_g(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /g alias help."""
        return self.handle_graph(_, messages)

    def handle_e(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /e alias help."""
        return self.handle_env(_, messages)

    def handle_k(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /k alias help."""
        return self.handle_kill(_, messages)

    def handle_t(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /t alias help."""
        return self.handle_turns(_, messages)

    def handle_a(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /a alias help."""
        return self.handle_agents(_, messages)

    def handle_cfg(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /cfg alias help."""
        return self.handle_config(_, messages)

    def handle_hist(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /hist alias help."""
        return self.handle_help_history()

    def handle_clear(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /clear alias help."""
        return self.handle_flush(_, messages)

    def handle_quit(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /quit alias help."""
        return self.handle_help_exit()

    def handle_h(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /h alias help."""
        return self.handle_help()

    # Restore missing methods
    def _print_command_table(
        self,
        title: str,
        commands: List[tuple[str, str, str]],
        header_style: str = "bold yellow",
        command_style: str = "yellow"
    ) -> None:
        """Print a table of commands with consistent formatting.

        Args:
            title: The table title
            commands: List of (command, description, alias) tuples
            header_style: Style for the header row
            command_style: Style for the command column
        """
        table = create_styled_table(
            title,
            [
                ("Command", command_style),
                ("Alias", "green"),
                ("Description", "white")
            ],
            header_style
        )

        for cmd, desc, alias in commands:
            table.add_row(cmd, alias, desc)

        console.print(table)

    def handle_help(self) -> bool:
        """Display general help information."""
        # Print title
        console.print(
            "\n[bold]CAI Commands[/bold]",
            style="bold blue"
        )

        # Group commands by category
        core_commands = [
            ("/help", "Display help information", "/h"),
            ("/exit", "Exit cai", "/quit"),
            ("/agent", "Manage AI agents", "/a"),
            ("/model", "Change the LLM model", "/mod"),
            ("/turns", "Manage conversation turns", "/t"),
            ("/memory", "Manage memory and context", "/mem")
        ]
        
        environment_commands = [
            ("/shell", "Execute shell commands", "/!"),
            ("/env", "Display CAI/CTF environment variables", "/e"),
            ("/platform", "Access platform features", "/p"),
            ("/virtualization", "Manage Docker environments", "/virt"),
            ("/workspace", "Manage workspace within environments", "/ws"),
            ("/kill", "Terminate background jobs/processes", "/k")
        ]
        
        utility_commands = [
            ("/config", "Configure CAI settings via env vars", "/cfg"),
            ("/graph", "Visualize memory graph", "/g"),
            ("/history", "Manage command history", "/hist"),
            ("/flush", "Flush context/message list", "/clear"),
            # Add MCP to the utility commands list
            ("/mcp", "Manage Model Context Protocol servers", "/m"),
        ]

        # Print command tables by category
        self._print_command_table("Core Commands", core_commands)
        self._print_command_table(
            "Environment Commands",
            environment_commands
        )
        self._print_command_table("Utility Commands", utility_commands)

        # Display notes
        notes = [
            "Use [yellow]/help <command>[/yellow] for detailed help on a "
            "specific command",
            "Commands can be abbreviated with their aliases (shown in "
            "parentheses)",
            "Use tab completion for commands and arguments",
            "Command shadowing will suggest previously used commands"
        ]
        console.print(create_notes_panel(notes))

        return True

    def handle_help_aliases(self) -> bool:
        """Show all command aliases in a well-formatted table."""
        # Create a styled header
        console.print(
            Panel(
                "Command Aliases Reference",
                border_style="magenta",
                title="Aliases"
            )
        )

        # Create a table for aliases
        alias_table = create_styled_table(
            "Command Aliases",
            [
                ("Alias", "green"),
                ("Command", "yellow"),
                ("Description", "white")
            ],
            "bold magenta"
        )

        # Add rows for each alias, ensuring command exists
        # Use sorted items for consistent order
        for alias, command_name in sorted(COMMAND_ALIASES.items()):
            cmd = COMMANDS.get(command_name)
            description = cmd.description if cmd else "[red]Command not found[/red]"
            alias_table.add_row(alias, command_name, description)

        console.print(alias_table)

        # Add tips
        tips = [
            "Aliases can be used anywhere the full command would be used",
            (
                "Example: [green]/m list[/green] instead of "
                "[yellow]/memory list[/yellow]"
            )
        ]
        console.print("\n")
        console.print(create_notes_panel(tips, "Tips", "cyan"))

        return True

    def handle_help_memory(self) -> bool:
        """Show help for memory commands with rich formatting."""
        # Create a styled header
        header = Text("Memory Command Help", style="bold yellow")
        console.print(Panel(header, border_style="yellow"))

        # Usage table
        usage_table = create_styled_table(
            "Usage",
            [("Command", "yellow"), ("Description", "white")]
        )

        usage_table.add_row(
            "/memory list",
            "Display all available memory collections"
        )
        usage_table.add_row(
            "/memory load <collection>",
            "Set the active memory collection"
        )
        usage_table.add_row(
            "/memory delete <collection>",
            "Delete a memory collection"
        )
        usage_table.add_row(
            "/memory create <collection>",
            "Create a new memory collection"
        )
        usage_table.add_row("/m", "Alias for /memory")

        console.print(usage_table)

        # Examples table
        examples_table = create_styled_table(
            "Examples",
            [("Example", "cyan"), ("Description", "white")],
            "bold cyan"
        )

        examples = [
            ("/memory list", "List all available collections"),
            ("/memory load _all_", "Load the semantic memory collection"),
            ("/memory load my_ctf", "Load the episodic memory for 'my_ctf'"),
            (
                "/memory create new_collection",
                "Create a new collection named 'new_collection'"
            ),
            (
                "/memory delete old_collection",
                "Delete the collection named 'old_collection'"
            )
        ]

        for example, desc in examples:
            examples_table.add_row(example, desc)

        console.print(examples_table)

        # Collection types table
        types_table = create_styled_table(
            "Collection Types",
            [("Type", "green"), ("Description", "white")],
            "bold green"
        )

        types = [
            ("_all_", "Semantic memory across all CTFs"),
            ("<CTF_NAME>", "Episodic memory for a specific CTF"),
            ("<custom_name>", "Custom memory collection")
        ]

        for type_name, desc in types:
            types_table.add_row(type_name, desc)

        console.print(types_table)

        # Notes panel
        notes = [
            "Memory collections are stored in the Qdrant vector database",
            "The active collection is stored in the CAI_MEMORY_COLLECTION "
            "env var",
            "Episodic memory is used for specific CTFs or tasks",
            "Semantic memory (_all_) is used across all CTFs",
            "Memory is used to provide context to the agent"
        ]

        console.print(create_notes_panel(notes))

        return True

    def handle_help_model(self) -> bool:
        """Show help for model command with rich formatting."""
        # Updated based on cai/repl/commands/model.py
        # Create a styled header
        header = Text("Model Command Help", style="bold magenta")
        console.print(Panel(header, border_style="magenta"))

        # Usage table
        usage_table = create_styled_table(
            "Usage",
            [("Command", "magenta"), ("Description", "white")]
        )

        usage_commands = [
            ("/model", "Display current model and list available models"),
            ("/model <model_name>", "Change the model to <model_name>"),
            (
                "/model <number>",
                "Change the model using its number from the list"
            ),
            ("/mod", "Alias for /model")
        ]

        for cmd, desc in usage_commands:
            usage_table.add_row(cmd, desc)

        console.print(usage_table)

        # Examples table
        examples_table = create_styled_table(
            "Examples",
            [("Example", "cyan"), ("Description", "white")],
            "bold cyan"
        )

        examples = [
            # Examples updated slightly
            (
                "/model 1",
                "Switch to the first model in the list"
            ),
            (
                "/model claude-3-5-sonnet-20240620",
                "Switch to Claude 3.5 Sonnet model by name"
            ),
            (
                "/model o1-mini",
                "Switch to OpenAI's O1-mini model"
            ),
            (
                "/model qwen2.5:14b",
                "Switch to a specific Ollama model (if available)"
            ),
            (
                "/mod 10",
                "Switch using alias and number"
            )
        ]

        for example, desc in examples:
            examples_table.add_row(example, desc)

        console.print(examples_table)

        # Model categories table
        categories_table = create_styled_table(
            "Model Categories",
            [("Category", "green"), ("Description", "white")],
            "bold green"
        )

        categories = [
            # Simplified categories
            (
                "Google Gemini",
                "Advanced models from Google (Gemini 2.0, 2.5)"
            ),
            (
                "Anthropic Claude",
                "High-performance models (Claude 3, 3.5, 3.7)"
            ),
            (
                "OpenAI",
                "Powerful models including GPT-4o and O-series for reasoning"
            ),
            (
                "DeepSeek",
                "Models specialized in coding and reasoning (V3, R1)"
            ),
            (
                "Ollama",
                "Local models running on your machine (e.g., llama3, mistral)"
            )
        ]

        for category, desc in categories:
            categories_table.add_row(category, desc)

        console.print(categories_table)

        # Notes panel
        notes = [
            "The model change takes effect on the next agent interaction",
            "The model is stored in the CAI_MODEL environment variable",
            "Some models may require specific API keys to be set",
            "OpenAI models require OPENAI_API_KEY to be set",
            "Anthropic models require ANTHROPIC_API_KEY to be set",
            "Ollama models require Ollama to be running locally",
            (
                "Use [yellow]/model-show[/yellow] to see all models from LiteLLM"
            )
        ]

        console.print(create_notes_panel(notes))

        # Add /model-show help section here for consolidation
        console.print(Panel(
            Text("Model Show Command Help", style="bold magenta"),
            border_style="magenta"
        ))

        usage_table_show = create_styled_table(
            "Usage (/model-show)",
            [("Command", "magenta"), ("Description", "white")]
        )
        usage_table_show.add_row(
            "/model-show",
            "Show all models available via LiteLLM repository data"
        )
        usage_table_show.add_row(
            "/model-show supported",
            "Show only models supporting function calling"
        )
        usage_table_show.add_row(
            "/model-show <search>",
            "Filter models by a search term in the name"
        )
        usage_table_show.add_row(
            "/model-show supported <search>",
            "Filter supported models by search term"
        )
        usage_table_show.add_row(
            "/mod-show",
            "Alias for /model-show"
        )
        console.print(usage_table_show)

        notes_show = [
            "Shows model provider, context window size, costs, and features.",
            "Helps discover models beyond the curated list shown by /model."
        ]
        console.print(create_notes_panel(notes_show, title="/model-show Notes"))

        return True

    def handle_help_turns(self) -> bool:
        """Show help for turns command with rich formatting."""
        # Updated based on cai/repl/commands/turns.py
        # Create a styled header
        header = Text("Turns Command Help", style="bold magenta")
        console.print(Panel(header, border_style="magenta"))

        # Usage table
        usage_table = create_styled_table(
            "Usage",
            [("Command", "magenta"), ("Description", "white")]
        )

        usage_commands = [
            ("/turns", "Display current maximum number of turns"),
            ("/turns <number>", "Change the maximum number of turns"),
            ("/turns inf", "Set unlimited turns"),
            ("/t", "Alias for /turns")
        ]

        for cmd, desc in usage_commands:
            usage_table.add_row(cmd, desc)

        console.print(usage_table)

        # Examples table
        examples_table = create_styled_table(
            "Examples",
            [("Example", "cyan"), ("Description", "white")],
            "bold cyan"
        )

        examples = [
            ("/turns", "Show current maximum turns"),
            ("/turns 10", "Set maximum turns to 10"),
            ("/turns inf", "Set unlimited turns"),
            ("/t 5", "Set maximum turns to 5 (using alias)")
        ]

        for example, desc in examples:
            examples_table.add_row(example, desc)

        console.print(examples_table)

        # Notes panel
        notes = [
            (
                "The maximum turns limit controls how many responses the "
                "agent will give"
            ),
            "Setting turns to 'inf' allows unlimited responses",
            (
                "The turns count is stored in the CAI_MAX_TURNS "
                "environment variable"
            ),
            "Each agent response counts as one turn"
        ]

        console.print(create_notes_panel(notes))

        return True

    def handle_help_platform_manager(self) -> bool:
        """Show help for platform manager commands."""
        if HAS_PLATFORM_EXTENSIONS and is_caiextensions_platform_available():
            try:
                from caiextensions.platform.base import platform_manager
                platforms = platform_manager.list_platforms()

                if not platforms:
                    console.print(
                        "[yellow]No platforms registered.[/yellow]"
                    )
                    return True

                platform_table = create_styled_table(
                    "Available Platforms",
                    [
                        ("Platform", "magenta"),
                        ("Description", "white")
                    ],
                    "bold magenta"
                )

                for platform_name in platforms:
                    platform = platform_manager.get_platform(platform_name)
                    description = getattr(
                        platform, 'description', platform_name.capitalize())
                    platform_table.add_row(
                        platform_name,
                        description
                    )

                console.print(platform_table)

                # Add platform command examples
                examples = []
                for platform_name in platforms:
                    platform = platform_manager.get_platform(platform_name)
                    commands = platform.get_commands()
                    if commands:
                        examples.append(
                            f"[green]/platform {platform_name} {commands[0]}[/green] - Example {platform_name} command")

                if examples:
                    console.print(Panel(
                        "\n".join(examples),
                        title="Platform Command Examples",
                        border_style="blue"
                    ))

                return True
            except (ImportError, Exception) as e:
                console.print(
                    f"[yellow]Error loading platforms: {e}[/yellow]"
                )
                return True

        console.print(
            "[yellow]No platform extensions available.[/yellow]"
        )
        return True

    def handle_help_config(self) -> bool:
        """Display help for config commands.

        Returns:
            True if successful
        """
        console.print(
            Panel(
                Text.from_markup(
                    "The [bold yellow]/config[/bold yellow] command allows you"
                    "to view and configure environment variables that control"
                    "the behavior of CAI."
                ),
                title="Config Commands",
                border_style="yellow"
            )
        )

        # Create table for subcommands
        table = create_styled_table(
            "Available Subcommands",
            [("Command", "yellow"), ("Description", "white")]
        )

        table.add_row(
            "/config",
            "List all environment variables and their current values"
        )
        table.add_row(
            "/config list",
            "List all environment variables and their current values"
        )
        table.add_row(
            "/config get <number>",
            "Get the value of a specific environment variable by its number"
        )
        table.add_row(
            "/config set <number> <value>",
            "Set the value of a specific environment variable by its number"
        )

        console.print(table)

        # Create notes panel
        notes = [
            "Environment variables control various aspects of CAI behavior.",
            "Changes environment variables only affect the current session.",
            "Use the [yellow]/config list[/yellow] command to see options.",
            "Each variable is assigned a number for easy reference."
        ]
        console.print(create_notes_panel(notes))

        return True

    def handle_help_workspace(self) -> bool:
        """Show help for workspace commands."""
        console.print(Panel(
            "Workspace commands manage the working directory and files, "
            "especially when using virtualization.\n\n"
            "[bold]Available Commands:[/bold]\n"
            "• [yellow]/workspace[/yellow] - Show current workspace info and contents\n"
            "• [yellow]/workspace set <name>[/yellow] - Set the active workspace name\n"
            "• [yellow]/workspace get[/yellow] - Display current workspace info\n"
            "• [yellow]/workspace ls [path][/yellow] - List files in the workspace (relative path optional)\n"
            "• [yellow]/workspace exec <cmd>[/yellow] - Execute a shell command within the workspace directory\n"
            "• [yellow]/workspace copy <src> <dst>[/yellow] - Copy files between host and container (use 'container:' prefix)\n"
            "• [yellow]/ws[/yellow] - Alias for /workspace\n\n"
            "[bold]Description:[/bold]\n"
            "Workspaces help organize files related to different tasks or "
            "projects. When a virtual environment (container) is active, "
            "these commands operate on the mapped workspace directory inside "
            "the container (usually `/workspace/workspaces/<name>`). Otherwise, "
            "they operate on the host.",
            title="Workspace Commands (/workspace)",
            border_style="blue"
        ))
        return True

    def handle_help_kill(self) -> bool:
        """Show help for kill commands."""
        console.print(Panel(
            "The kill command terminates background shell sessions or potentially other processes managed by CAI.\n\n"
            "[bold]Usage:[/bold]\n"
            "• [yellow]/kill <session_id>[/yellow] - Terminate a background shell session by its ID\n"
            "• [yellow]/k <session_id>[/yellow] - Alias for /kill\n\n"
            "[bold]Description:[/bold]\n"
            "Use this command to kill a process",
            title="Kill Command (/kill)",
            border_style="red"
        ))
        return True

    def handle_help_flush(self) -> bool:
        """Show help for flush commands."""
        console.print(Panel(
            "The flush command is used to clear the context/message list.\n\n"
            "Is highly recommended that before using this command you should save the context/message list.\n\n"
            "CAI> save all your findings in findings.txt\n"
            "CAI> /flush\n"
            "CAI> Continue from findings.txt\n\n"
            "[bold]Usage:[/bold]\n"
            "• [yellow]/flush[/yellow] - Execute the flush operation\n\n"
            "[bold]Description:[/bold]\n"
            "This command currently triggers specific flush operations within "
            "the system (e.g., potentially related to data recorders or "
            "memory components). Its exact behavior might depend on the "
            "system's state.",
            title="Flush Command (/flush)",
            border_style="cyan"
        ))
        return True

    def handle_mcp_help(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Show help for MCP commands with rich formatting."""
        console.print(Panel(
            Text.from_markup(
                "Interact with [bold cyan]Model Context Protocol (MCP)[/bold cyan] servers.\n\n"
                "MCP allows CAI to connect to external servers that provide additional tools and context for the AI agent. "
                "These tools can be dynamically loaded and added to agents during a session."
            ),
            title="MCP Command Help (/mcp)",
            border_style="blue",
            title_align="center"
        ))

        # Subcommand Table
        mcp_subcommands_table = create_styled_table(
            "Available Subcommands",
            [("Subcommand", "cyan"), ("Usage", "yellow"), ("Description", "white")],
            header_style="bold blue"
        )

        mcp_subcommands = [
            (
                "load",
                "/mcp load <url> <label>",
                "Connect to an MCP server at the given URL and assign a unique label."
            ),
            (
                "unload",
                "/mcp unload <label>",
                "Disconnect from the MCP server identified by the label."
            ),
            (
                "add",
                "/mcp add <label> <agent_name>",
                "Add all tools provided by the connected server (label) to the specified agent."
            ),
            (
                "list",
                "/mcp list [label]",
                "List all active MCP connections. If a label is provided, list tools for that server."
            )
        ]

        for subcmd, usage, desc in mcp_subcommands:
            mcp_subcommands_table.add_row(f"[bold]{subcmd}[/bold]", usage, desc)

        console.print(mcp_subcommands_table)

        # Examples Table
        examples_table = create_styled_table(
            "Examples",
            [("Example Command", "green"), ("Action", "white")],
            header_style="bold blue"
        )

        examples = [
            (
                "/mcp load http://localhost:9876/sse burp_local",
                "Connect to an MCP server running locally and label it 'burp_local'."
            ),
            (
                "/mcp list",
                "Show the status of all connected MCP servers."
            ),
            (
                "/mcp add burp_local redteam_agent",
                "Add tools from the 'burp_local' server to the 'redteam_agent'."
            ),
            (
                "/mcp unload burp_local",
                "Disconnect from the 'burp_local' server."
            ),
            (
                "/mcp list burp_local",
                 "List the specific tools available from the 'burp_local' server."
             )
        ]

        for example, action in examples:
            examples_table.add_row(example, action)

        console.print(examples_table)

        # Notes Panel
        notes = [
            "Connections run in background threads for persistence.",
            "Tools added via `/mcp add` become available to the agent like built-in functions.",
            "Use `/mcp list` to check connection status and available tools.",
            "Agent names for `/mcp add` can be the actual name or special values like `current` or `active`."
        ]
        console.print(create_notes_panel(notes, title="MCP Notes", border_style="blue"))

        return True

    def handle_m(self, _: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the /m alias help."""
        return self.handle_mcp_help(_, messages)


# Register the command
register_command(HelpCommand())
