"""
Shell command for CAI REPL.
This module provides commands for executing shell commands.
"""
import os
import signal
import subprocess  # nosec B404
from typing import (
    Dict,
    List,
    Optional
)
from rich.console import Console  # pylint: disable=import-error

from cai.repl.commands.base import Command, register_command
# Import common workspace functions
from cai.tools.common import _get_workspace_dir, _get_container_workspace_path

console = Console()


class ShellCommand(Command):
    """Command for executing shell commands."""

    def __init__(self):
        """Initialize the shell command."""
        super().__init__(
            name="/shell",
            description="Execute shell commands in the current environment",
            aliases=["/s", "$"]
        )

    def handle(self, args: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the shell command.

        Args:
            args: Optional list of command arguments
            messages: Optional list of conversation messages

        Returns:
            True if the command was handled successfully, False otherwise
        """
        if not args:
            console.print("[red]Error: No command specified[/red]")
            return False

        return self.handle_shell_command(args)
    def handle_shell_command(self, command_args: List[str], messages: Optional[List[Dict]] = None) -> bool:
        """Execute a shell command, potentially changing directory first.

        Args:
            command_args: The shell command and its arguments
            messages: Optional list of conversation messages

        Returns:
            bool: True if the command was executed successfully
        """
        if not command_args:
            console.print("[red]Error: No command specified[/red]")
            return False

        original_command = " ".join(command_args)
        shell_command_to_execute = original_command
        
        # Check for active virtualization container
        active_container = os.getenv("CAI_ACTIVE_CONTAINER", "")
        
        if active_container:
            console.print(f"[dim]Running in container: {active_container[:12]}...[/dim]")

            # Get the target workspace path inside the container
            container_workspace = _get_container_workspace_path()

            # Use docker exec with -w flag to run the command in the container's workspace
            # Ensure the command string is properly quoted for the inner shell
            # Use repr() for robust quoting of the command
            docker_command = f"docker exec -w '{container_workspace}' {active_container} sh -c {shell_command_to_execute!r}"
            console.print(f"[blue]Executing in container workspace '{container_workspace}':[/blue] {original_command}")
            
            # Save original signal handler
            original_sigint_handler = signal.getsignal(signal.SIGINT)
            
            try:
                # Set temporary handler for SIGINT that only affects shell command
                def shell_sigint_handler(sig, frame):  # pylint: disable=unused-argument
                    # Just allow KeyboardInterrupt to propagate
                    if original_sigint_handler:
                        signal.signal(signal.SIGINT, original_sigint_handler)
                    raise KeyboardInterrupt

                signal.signal(signal.SIGINT, shell_sigint_handler)
                
                # Determine if the command suggests async execution
                async_commands = [
                    'nc', 'netcat', 'ncat', 'telnet', 'ssh',
                    'python -m http.server'
                ]
                is_async = any(cmd in original_command for cmd in async_commands)
                
                if is_async:
                    # For async commands, use os.system
                    console.print(
                        "[yellow]Running in async mode "
                        "(Ctrl+C to return to REPL)[/yellow]"
                    )
                    os.system(docker_command)  # nosec B605
                    console.print(
                        "[green]Async command completed or detached[/green]"
                    )
                    return True
                    
                # For regular commands, use subprocess.Popen
                process = subprocess.Popen(  # nosec B602 # pylint: disable=consider-using-with
                    docker_command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    bufsize=1
                )
                
                # Show output in real time
                for line in iter(process.stdout.readline, ''):
                    print(line, end='')
                    
                # Wait for process to finish
                process.wait()
                
                if process.returncode == 0:
                    console.print(
                        "[green]Command completed successfully[/green]")
                else:
                    console.print(
                        f"[yellow]Command exited with code {process.returncode}"
                        f"[/yellow]")
                        
                    # If the command failed because the container is not running,
                    # fallback to running locally
                    if "Error response from daemon" in process.stdout.read():
                        console.print(
                            "[yellow]Error en contenedor. Ejecutando en el host local.[/yellow]"
                        )
                        # Eliminar la variable de entorno para ejecutar localmente
                        os.environ.pop("CAI_ACTIVE_CONTAINER", None)
                        # Intentar nuevamente en el host
                        return self.handle_shell_command(command_args)
                        
                return True
                
            except KeyboardInterrupt:
                # Handle CTRL+C only for this command
                try:
                    if not is_async:
                        process.terminate()
                    console.print("\n[yellow]Command interrupted by user[/yellow]")
                except Exception:  # pylint: disable=broad-except
                    pass
                return True
            except Exception as e:  # pylint: disable=broad-except
                console.print(f"[red]Error executing command in container '{active_container[:12]}': {str(e)}[/red]")
                console.print("[yellow]Ejecutando en el host local.[/yellow]")
                # Ejecutar en el host como fallback
                os.environ.pop("CAI_ACTIVE_CONTAINER", None)
                # Intentar nuevamente en el host
                return self.handle_shell_command(command_args)
            finally:
                # Restore original signal handler
                signal.signal(signal.SIGINT, original_sigint_handler)
        
        # No container, run locally
        # Get the target host workspace directory using the common function
        host_workspace_dir = _get_workspace_dir()

        # Check if we are already in the target workspace directory
        is_in_target_workspace = os.path.abspath(os.getcwd()) == os.path.abspath(host_workspace_dir)

        if is_in_target_workspace:
            console.print(f"[dim]Running in workspace (current dir): {host_workspace_dir}[/dim]")
            # Command to execute for async (os.system)
            # No need for cd prefix if already in the directory
            async_command_to_execute = original_command
        else:
            console.print(f"[dim]Running in workspace: {host_workspace_dir}[/dim]")
            # Command to execute for async (os.system) needs cd prefix
            async_command_to_execute = f"cd {host_workspace_dir!r} && {original_command}"

        console.print(f"[blue]Executing:[/blue] {original_command}")

        # Save original signal handler
        original_sigint_handler = signal.getsignal(signal.SIGINT)

        try:
            # Set temporary handler for SIGINT that only affects shell command
            def shell_sigint_handler(sig, frame):  # pylint: disable=unused-argument
                # Just allow KeyboardInterrupt to propagate
                if original_sigint_handler:
                    signal.signal(signal.SIGINT, original_sigint_handler)
                raise KeyboardInterrupt

            signal.signal(signal.SIGINT, shell_sigint_handler)

            # Determine if the *original* command suggests async execution
            async_commands = [
                'nc', 'netcat', 'ncat', 'telnet', 'ssh',
                'python -m http.server'
            ]
            is_async = any(cmd in original_command for cmd in async_commands)

            if is_async:
                # For async commands, use os.system. It respects the shell's cd
                console.print(
                    "[yellow]Running in async mode "
                    "(Ctrl+C to return to REPL)[/yellow]"
                )
                # os.system runs in a subshell, inheriting the environment
                # The shell handles the `cd ... && ...` part correctly.
                os.system(async_command_to_execute)  # nosec B605
                console.print(
                    "[green]Async command completed or detached[/green]"
                )
                return True

            # For regular commands, use subprocess.Popen
            # Pass the potentially modified command (with cd)
            # Use cwd parameter for Popen for reliability
            process = subprocess.Popen(  # nosec B602 # pylint: disable=consider-using-with
                original_command, # Execute original command directly
                shell=True,       # Shell handles cd if present in command_to_execute
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                cwd=host_workspace_dir # Set the CWD for the subprocess
            )

            # Show output in real time
            for line in iter(process.stdout.readline, ''):
                print(line, end='')

            # Wait for process to finish
            process.wait()

            if process.returncode == 0:
                console.print(
                    "[green]Command completed successfully[/green]")
            else:
                console.print(
                    f"[yellow]Command exited with code {process.returncode}"
                    f"[/yellow]")
            return True

        except KeyboardInterrupt:
            # Handle CTRL+C only for this command
            try:
                if not is_async:
                    process.terminate()
                console.print("\n[yellow]Command interrupted by user[/yellow]")
            except Exception:  # pylint: disable=broad-except
                pass
            return True
        except Exception as e:  # pylint: disable=broad-except
            console.print(f"[red]Error executing command: {str(e)}[/red]")
            return False
        finally:
            # Restore original signal handler
            signal.signal(signal.SIGINT, original_sigint_handler)

# Register the command
register_command(ShellCommand())
