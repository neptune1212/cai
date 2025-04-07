"""
MCP (Model Context Protocol) command for CAI CLI.

Provides commands for connecting to MCP servers, managing connections,
and integrating MCP tools with CAI agents.
"""

# Standard library imports
import asyncio
import inspect
import re
import sys
import os
import time
import traceback
from typing import Any, Dict, List, Optional, Callable
from urllib.parse import urlparse
import threading
import queue
import weakref  # To prevent reference cycles with threads/sessions
import json

# Third-party imports
from rich.console import Console
from rich.table import Table

# Local imports
from cai.repl.commands.base import Command, register_command
from cai.types import Agent as CaiAgent

console = Console()

# Global store for active MCP connections
# {label: {'url': str, 'thread': Thread, 'loop': AbstractEventLoop, 'session': ClientSession, 'status': str, 'shutdown_event': Event}}
active_mcp_servers: Dict[str, Dict[str, Any]] = {}
mcp_tools_cache: Dict[str, List[Any]] = {}  # {label: [Tool objects]}
# Lock for thread-safe access to shared dictionaries
mcp_lock = threading.Lock()

# Debug mode - set to False to disable detailed logging
DEBUG = False

def debug_print(*args, **kwargs):
    """Print debug information if DEBUG is enabled."""
    if DEBUG:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        thread_id = threading.get_ident()
        
        # Escape any potential markup in the arguments
        escaped_args = []
        for arg in args:
            if isinstance(arg, str):
                escaped_arg = arg.replace("[", "\\[").replace("]", "\\]")
                escaped_args.append(escaped_arg)
            else:
                escaped_args.append(arg)
        
        console.print(f"[dim][DEBUG {timestamp} T:{thread_id}][/dim]", *escaped_args, **kwargs)

# Import MCP dependencies only when needed
def import_mcp_deps():
    """Import MCP dependencies on demand."""
    try:
        debug_print("Importing MCP dependencies...")
        import mcp
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        from mcp.types import Tool as McpTool
        debug_print("MCP dependencies imported successfully")
        return mcp, ClientSession, sse_client, McpTool
    except ImportError as e:
        console.print(f"[red]Error importing MCP dependencies: {e}[/red]")
        console.print("[yellow]Install with: pip install mcp-sdk[/yellow]")
        return None, None, None, None
    except Exception as e:
        console.print(f"[red]Unexpected error importing MCP dependencies: {e}[/red]")
        traceback.print_exc()
        return None, None, None, None

# --- Thread-Safe Async Execution ---
def run_coroutine_in_loop(coro, loop, timeout=None):
    """Runs a coroutine in a specific event loop and waits for the result."""
    debug_print(f"Running coroutine in loop {id(loop)} with timeout {timeout}")
    if not loop or loop.is_closed():
        debug_print("Error: Loop is invalid or closed.")
        raise RuntimeError("Invalid or closed event loop")

    # Default timeout is now 2 minutes for large responses
    if timeout is None:
        timeout = 120  # 2 minutes default
    
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        debug_print(f"Waiting for future result with timeout {timeout}")
        result = future.result(timeout=timeout)
        debug_print("Result obtained from future")
        return result
    except TimeoutError:
        debug_print("Timeout waiting for future result")
        future.cancel()  # Try to cancel the task in the loop
        raise TimeoutError("Operation exceeded time limit")
    except Exception as e:
        debug_print(f"Exception waiting for future result: {e}")
        traceback.print_exc()
        raise e

# --- Connection Management Thread ---
def manage_connection(label: str, server_url: str, result_queue: queue.Queue, shutdown_event: threading.Event):
    """Runs in a separate thread to manage an MCP connection."""
    mcp, ClientSession, sse_client, McpTool = import_mcp_deps()
    if not mcp:
        result_queue.put(Exception("MCP dependencies not found"))
        return

    loop = None
    session_ref = None  # Use weakref to store session temporarily
    try:
        debug_print(f"Starting management thread for '{label}'")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        debug_print(f"New event loop created and started: {id(loop)}")

        # Define the main async logic for this thread
        async def connection_logic():
            nonlocal session_ref
            client_cm = None
            session_cm = None
            try:
                debug_print(f"[{label}] Attempting to connect to {server_url}")
                client_cm = sse_client(server_url)
                debug_print(f"[{label}] Entering sse_client context")
                
                # Capture any exceptions during connection and don't let them propagate to user
                try:
                    streams = await asyncio.wait_for(client_cm.__aenter__(), timeout=15)
                    debug_print(f"[{label}] SSE connection established, streams obtained")
                except asyncio.TimeoutError:
                    debug_print(f"[{label}] Connection timeout")
                    result_queue.put(TimeoutError(f"Connection to server '{label}' timed out"))
                    return
                except asyncio.CancelledError:
                    debug_print(f"[{label}] Connection task cancelled")
                    result_queue.put(Exception(f"Connection to server '{label}' was cancelled"))
                    return
                except Exception as e:
                    # Silently log but don't expose full error to user
                    debug_print(f"[{label}] Connection error: {e}")
                    result_queue.put(Exception(f"Could not connect to server '{label}': {type(e).__name__}"))
                    return
                
                read_stream, write_stream = streams

                session_cm = ClientSession(read_stream, write_stream)
                debug_print(f"[{label}] Entering ClientSession context")
                
                # Also handle ClientSession initialization errors
                try:
                    # Use weakref to avoid holding strong reference in this scope
                    _session = await asyncio.wait_for(session_cm.__aenter__(), timeout=10)
                    session_ref = weakref.ref(_session)
                    debug_print(f"[{label}] Session created: {session_ref()}")
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception) as e:
                    debug_print(f"[{label}] Session creation error: {e}")
                    result_queue.put(Exception(f"Failed to create MCP session: {type(e).__name__}"))
                    return

                debug_print(f"[{label}] Initializing MCP session...")
                # Increase timeout for initialization
                await asyncio.wait_for(_session.initialize(), timeout=20)
                debug_print(f"[{label}] MCP session initialized successfully")

                # Store session and loop globally (thread-safe)
                with mcp_lock:
                    if label in active_mcp_servers:  # Check if still relevant
                        active_mcp_servers[label].update({
                            'session': _session,  # Store strong reference now
                            'loop': loop,
                            'status': 'connected',
                            'client_cm': client_cm,  # Store context managers for cleanup
                            'session_cm': session_cm,
                        })
                    else:  # Unloaded before connection finished
                        debug_print(f"[{label}] Connection canceled (unload called before connecting)")
                        result_queue.put(None)  # Indicate cancellation
                        return  # Exit coroutine

                debug_print(f"[{label}] Session and loop stored globally")

                # List tools
                debug_print(f"[{label}] Listing tools...")
                tools_result = await asyncio.wait_for(_session.list_tools(), timeout=15)
                tools = []
                if hasattr(tools_result, 'tools'):
                    tools = tools_result.tools
                    with mcp_lock:
                        mcp_tools_cache[label] = tools
                    debug_print(f"[{label}] Found and cached {len(tools)} tools")
                else:
                    debug_print(f"[{label}] No tools found")

                # Signal success to main thread
                result_queue.put({'status': 'success', 'tools_count': len(tools)})

                # Keep the connection alive by waiting for shutdown signal
                debug_print(f"[{label}] Active connection. Waiting for shutdown signal...")
                while not shutdown_event.is_set():
                    # Send periodic pings to keep alive if needed by server/protocol
                    # try:
                    #     await asyncio.wait_for(session.send_ping(), timeout=5)
                    #     debug_print(f"[{label}] Ping sent")
                    # except Exception:
                    #     debug_print(f"[{label}] Error sending ping, connection may be lost.")
                    #     # Handle potential disconnection detected by ping failure
                    #     break
                    await asyncio.sleep(1)  # Check shutdown event periodically

                debug_print(f"[{label}] Shutdown signal received.")

            except asyncio.TimeoutError as e:
                error_msg = f"Timeout during connection/initialization for '{label}': {e}"
                debug_print(f"[{label}] {error_msg}")
                traceback.print_exc()
                result_queue.put(TimeoutError(error_msg))
            except Exception as e:
                error_msg = f"Error in connection thread for '{label}': {e}"
                debug_print(f"[{label}] {error_msg}")
                traceback.print_exc()
                result_queue.put(e)
            finally:
                debug_print(f"[{label}] Starting cleanup in connection_logic")
                # Ensure context managers are exited cleanly
                session = session_ref() if session_ref else None
                if session_cm:
                    try:
                        debug_print(f"[{label}] Exiting ClientSession context")
                        await session_cm.__aexit__(None, None, None)
                        debug_print(f"[{label}] ClientSession context closed")
                    except Exception as e_sess:
                        debug_print(f"[{label}] Error closing ClientSession: {e_sess}")
                if client_cm:
                    try:
                        debug_print(f"[{label}] Exiting sse_client context")
                        await client_cm.__aexit__(None, None, None)
                        debug_print(f"[{label}] sse_client context closed")
                    except Exception as e_sse:
                        debug_print(f"[{label}] Error closing sse_client: {e_sse}")
                # Clear global state associated with this label
                with mcp_lock:
                    if label in active_mcp_servers:
                        debug_print(f"[{label}] Removing server from active list")
                        # Don't remove the entire entry here, just update status or wait for unload
                        active_mcp_servers[label]['status'] = 'disconnected'
                        active_mcp_servers[label]['session'] = None  # Remove session object
                        active_mcp_servers[label]['loop'] = None
                    if label in mcp_tools_cache:
                        debug_print(f"[{label}] Removing tools from cache")
                        del mcp_tools_cache[label]

        # Wrap the entire coroutine execution to catch exceptions at the loop level
        try:
            loop.run_until_complete(connection_logic())
        except Exception as e:
            # This will catch any otherwise uncaught exceptions
            debug_print(f"Unhandled error in connection thread for '{label}': {e}")
            # Don't put this in the result queue if it's already been filled
            if result_queue.empty():
                result_queue.put(Exception(f"Connection error: {type(e).__name__}"))

    finally:
        if loop and not loop.is_closed():
            debug_print(f"Closing event loop {id(loop)} in thread {threading.get_ident()}")
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                # Silently ignore errors during cleanup
                pass
        debug_print(f"Management thread for '{label}' finished.")

# --- Tool Wrapper Creation ---
def create_tool_wrapper(server_label: str, tool_name: str, tool_desc: str, schema: Dict) -> Callable:
    """Create a synchronous wrapper for an MCP tool that executes in the correct thread."""
    debug_print(f"Creating wrapper for tool '{tool_name}' from server '{server_label}'")
    safe_name = re.sub(r'\W|^(?=\d)', '_', tool_name)

    def tool_wrapper(**kwargs):
        """MCP tool wrapper."""
        console.print(f"[dim]Calling MCP tool '{tool_name}' on server '{server_label}'...[/dim]")
        debug_print(f"Arguments for {tool_name}: {kwargs}")

        # Get the correct loop and session for this server (thread-safe)
        loop = None
        session = None
        with mcp_lock:
            server_info = active_mcp_servers.get(server_label)
            if server_info and server_info.get('status') == 'connected':
                loop = server_info.get('loop')
                session = server_info.get('session')
            else:
                status = server_info.get('status', 'not found') if server_info else 'not found'
                debug_print(f"Error: Server '{server_label}' is not connected (status: {status}).")
                return f"Error: MCP server '{server_label}' not found or not connected."

        if not loop or not session:
            debug_print(f"Error: Missing loop ({loop}) or session ({session}) for '{server_label}'.")
            return f"Error: Invalid internal state for MCP server '{server_label}'."

        async def call_tool_async():
            try:
                # Verify connection with a ping
                await asyncio.wait_for(session.send_ping(), timeout=5)
                
                # Increase timeout for tools that return large data
                # and use a more robust try/except block
                try:
                    # Execute the tool call with a generous timeout
                    result = await asyncio.wait_for(
                        session.call_tool(name=tool_name, arguments=kwargs),
                        timeout=180  # 3 minutes for very large responses
                    )
                    
                    # Process the result
                    if hasattr(result, 'value'):
                        value = result.value
                        
                        # Handle large results
                        if isinstance(value, str) and len(value) > 1000000:  # 1MB
                            return f"⚠️ Result too large ({len(value)} bytes). Showing first 1MB:\n\n{value[:1000000]}..."
                        
                        return value
                    
                    return str(result)
                    
                except asyncio.TimeoutError:
                    # Specific timeout for the tool call
                    return f"Error: Call to '{tool_name}' exceeded maximum wait time (3 min). Response might be too large."
                    
                except Exception as e:
                    error_str = str(e).lower()
                    
                    # Detect specific JSON errors
                    if any(msg in error_str for msg in ["invalid json", "eof while parsing", "json_invalid"]):
                        return (f"Error processing response from '{tool_name}': Response contains invalid JSON or is too large. "
                                f"Try with less data or split the operation into smaller parts.")
                    
                    # Re-raise other exceptions
                    raise e
                    
            except asyncio.TimeoutError:
                # Timeout on initial ping
                with mcp_lock:
                    if server_label in active_mcp_servers:
                        active_mcp_servers[server_label]['status'] = 'timeout'
                
                return f"Error: Could not verify connection to server '{server_label}' (ping timeout)"
                
            except Exception as e:
                with mcp_lock:
                    if server_label in active_mcp_servers:
                        active_mcp_servers[server_label]['status'] = 'error'
                
                return f"Error calling '{tool_name}': {str(e)}"

        try:
            # Execute in the correct loop
            return run_coroutine_in_loop(call_tool_async(), loop, timeout=180)
        except Exception as e:
            # Generic and simple error message
            return f"Error executing '{tool_name}': {str(e)}"

    # --- Set metadata (unchanged) ---
    tool_wrapper.__name__ = safe_name
    tool_wrapper.__doc__ = tool_desc or f"MCP tool '{tool_name}' from server '{server_label}'"
    if schema and isinstance(schema, dict) and schema.get('properties'):
        debug_print(f"Creating signature from schema: {schema}")
        params = []
        required = schema.get('required', [])
        type_map = {
            'string': str, 'integer': int, 'number': float,
            'boolean': bool, 'array': list, 'object': dict
        }
        for name, prop in schema.get('properties', {}).items():
            prop_type = prop.get('type', 'string')
            param_type = type_map.get(prop_type, str)
            default = None if name not in required else inspect.Parameter.empty
            params.append(
                inspect.Parameter(
                    name=name,
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    default=default,
                    annotation=param_type
                )
            )
        tool_wrapper.__signature__ = inspect.Signature(parameters=params)
        debug_print(f"Signature created: {tool_wrapper.__signature__}")
    else:
         tool_wrapper.__signature__ = inspect.Signature([
             inspect.Parameter('kwargs', inspect.Parameter.VAR_KEYWORD)
         ])
         debug_print(f"No valid schema found, using default signature: {tool_wrapper.__signature__}")

    return tool_wrapper

# --- MCP Command Class ---
class McpCommand(Command):
    """Command for managing MCP server connections and tools."""

    def __init__(self):
        """Initialize the MCP command."""
        debug_print("Initializing MCP command")
        super().__init__(
            name="/mcp",
            description="Manage MCP server connections and tools",
            aliases=["/m"]
        )

        self._subcommands = {
            "load": "Connect to an MCP server: load {url} {label}",
            "unload": "Disconnect from an MCP server: unload {label}",
            "add": "Add tools from an MCP server to an agent: add {label} {agent_name}",
            "list": "List active MCP connections and tools"
        }
        debug_print("MCP command initialized")

    def get_subcommands(self) -> List[str]:
        return list(self._subcommands.keys())

    def get_subcommand_description(self, subcommand: str) -> str:
        return self._subcommands.get(subcommand, "")

    def handle(self, args: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Handle the MCP command."""
        debug_print(f"Handling MCP command with args: {args}")
        if not args:
            console.print("[yellow]Usage: /mcp {subcommand} [options...][/yellow]")
            for subcmd, desc in self._subcommands.items():
                console.print(f"  [cyan]{subcmd}[/cyan]: {desc}")
            return True

        subcommand = args[0].lower()
        remaining_args = args[1:] if len(args) > 1 else []
        debug_print(f"Subcommand: {subcommand}, remaining args: {remaining_args}")

        handler_map = {
            "load": self.handle_load,
            "unload": self.handle_unload,
            "add": self.handle_add,
            "list": self.handle_list,
        }
        handler = handler_map.get(subcommand)
        if handler:
            return handler(remaining_args, messages)
        else:
            console.print(f"[red]Unknown subcommand: {subcommand}[/red]")
            return False

    def handle_list(self, args: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """List active MCP connections and tools."""
        debug_print("Executing 'list' subcommand")
        with mcp_lock:
            if not active_mcp_servers:
                console.print("[yellow]No active MCP connections.[/yellow]")
                return True

            table = Table(title="Active MCP Connections")
            table.add_column("Label", style="green")
            table.add_column("URL", style="blue")
            table.add_column("Status", style="magenta")
            table.add_column("Tools", style="cyan")

            # Create a copy to avoid issues if dictionary changes during iteration (though lock helps)
            servers_copy = dict(active_mcp_servers)

            for label, data in servers_copy.items():
                tools_count = len(mcp_tools_cache.get(label, []))
                status = data.get('status', 'unknown')
                table.add_row(label, data['url'], status, str(tools_count))

            console.print(table)
            
            # If a label is specified, show tools for that server
            if args and args[0] in servers_copy:
                label = args[0]
                tools = mcp_tools_cache.get(label, [])
                debug_print(f"Showing tools for server '{label}': {len(tools)} found")
                
                if not tools:
                    console.print(f"[yellow]No cached tools found for server '{label}'.[/yellow]")
                    return True
                    
                tools_table = Table(title=f"Cached Tools from MCP server '{label}'")
                tools_table.add_column("Name", style="green")
                tools_table.add_column("Description", style="blue")
                
                for tool in tools:
                    tools_table.add_row(tool.name, tool.description or "")
                    
                console.print(tools_table)
                
        return True

    def handle_load(self, args: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Connect to an MCP server using a background thread."""
        debug_print(f"Executing 'load' subcommand with args: {args}")
        if not args or len(args) != 2:
            console.print("[red]Usage: /mcp load {server_url} {label}[/red]")
            return False

        mcp, _, _, _ = import_mcp_deps()
        if not mcp: return False

        server_url, label = args[0], args[1]
        debug_print(f"URL: {server_url}, label: {label}")

        # Basic URL validation
        parsed_url = urlparse(server_url)
        if parsed_url.scheme not in ("http", "https"):
            console.print("[red]Invalid server URL. Must start with http:// or https://[/red]")
            return False

        with mcp_lock:
            if label in active_mcp_servers:
                # Allow reloading if disconnected? Maybe add a 'force' flag later.
                if active_mcp_servers[label].get('status') != 'disconnected':
                    console.print(f"[red]Error: Label '{label}' is already in use by an active or connecting connection.[/red]")
                    return False
                else:
                    debug_print(f"Retrying connection for previously disconnected label '{label}'.")

            result_queue = queue.Queue()
            shutdown_event = threading.Event()

            thread = threading.Thread(
                target=manage_connection,
                args=(label, server_url, result_queue, shutdown_event),
                daemon=True  # Allows main program to exit even if threads are running
            )

            # Store preliminary info (thread-safe)
            active_mcp_servers[label] = {
                'url': server_url,
                'thread': thread,
                'status': 'connecting',
                'shutdown_event': shutdown_event,
                'session': None,  # Will be set by the thread
                'loop': None,  # Will be set by the thread
            }

        console.print(f"Starting connection to MCP server '{label}' in background...")
        thread.start()
        debug_print(f"Connection thread for '{label}' started.")

        # Wait for result from the connection thread (with timeout)
        try:
            # Increased timeout to allow for connection and initialization
            result = result_queue.get(timeout=45)
            debug_print(f"Result received from queue for '{label}': {result}")

            if isinstance(result, Exception):
                # Instead of re-raising, just show a user-friendly message
                error_type = type(result).__name__
                error_msg = str(result)
                console.print(f"[red]Connection to MCP server '{label}' failed: {error_msg}[/red]")
                
                with mcp_lock:
                    if label in active_mcp_servers:
                        active_mcp_servers[label]['status'] = 'failed'
                return False

            if isinstance(result, dict) and result.get('status') == 'success':
                console.print(f"[green]Successfully connected to MCP server '{label}' ({result.get('tools_count', 0)} tools found).[/green]")
                # Status already updated by the thread
                return True
            else:
                # Handle potential cancellation or unexpected None result
                console.print(f"[red]Connection for '{label}' did not complete properly (may have been canceled).[/red]")
                with mcp_lock:  # Ensure cleanup if thread signaled cancellation implicitly
                    if label in active_mcp_servers:
                        active_mcp_servers[label]['status'] = 'failed'
                return False

        except KeyboardInterrupt:
            console.print(f"\n[yellow]Connection attempt to '{label}' was interrupted.[/yellow]")
            # Signal the thread to shutdown
            with mcp_lock:
                if label in active_mcp_servers:
                    active_mcp_servers[label]['status'] = 'canceled'
                    if active_mcp_servers[label].get('shutdown_event'):
                        active_mcp_servers[label]['shutdown_event'].set()
            return False
        except queue.Empty:
            console.print(f"[red]Timeout: No response received from connection to '{label}' after 45s.[/red]")
            # Signal the thread to shutdown if it's still running
            with mcp_lock:
                if label in active_mcp_servers:
                    active_mcp_servers[label]['status'] = 'timeout'
                    if active_mcp_servers[label].get('shutdown_event'):
                        active_mcp_servers[label]['shutdown_event'].set()
            return False
        except Exception as e:
            # Generic handler for any other exceptions
            console.print(f"[red]Error connecting to MCP server '{label}'[/red]")
            with mcp_lock:
                if label in active_mcp_servers:
                    active_mcp_servers[label]['status'] = 'failed'
            return False

    def handle_unload(self, args: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Disconnect from an MCP server."""
        debug_print(f"Executing 'unload' subcommand with args: {args}")
        if not args or len(args) != 1:
            console.print("[red]Usage: /mcp unload {label}[/red]")
            return False

        label = args[0]
        debug_print(f"Disconnecting server with label: {label}")

        with mcp_lock:
            server_info = active_mcp_servers.pop(label, None)  # Remove immediately
            if label in mcp_tools_cache:
                del mcp_tools_cache[label]
                
        if not server_info:
            console.print(f"[red]Error: No active or connecting MCP server found with label '{label}'.[/red]")
            return False

        console.print(f"Signaling shutdown for MCP server '{label}'...")

        shutdown_event = server_info.get('shutdown_event')
        thread = server_info.get('thread')

        if shutdown_event:
            debug_print(f"Sending shutdown signal to thread for '{label}'")
            shutdown_event.set()
        else:
            debug_print(f"No shutdown event found for '{label}' (may have already failed)")

        if thread and thread.is_alive():
            debug_print(f"Waiting for '{label}' thread to terminate (timeout 5s)...")
            thread.join(timeout=5)
            if thread.is_alive():
                console.print(f"[yellow]Warning: Connection thread for '{label}' did not terminate within 5s.[/yellow]")
                debug_print(f"Thread for '{label}' still alive after join.")
            else:
                debug_print(f"Thread for '{label}' terminated.")
        else:
            debug_print(f"No thread found or not alive for '{label}'")

        console.print(f"[green]Disconnected (or shutdown signal sent) from MCP server '{label}'.[/green]")
        return True

    def handle_add(self, args: Optional[List[str]] = None, messages: Optional[List[Dict]] = None) -> bool:
        """Add tools from MCP server to an agent."""
        debug_print(f"Executing 'add' subcommand with args: {args}")
        if not args or len(args) != 2:
            console.print("[red]Usage: /mcp add {label} {agent_name}[/red]")
            return False

        label, agent_name = args[0], args[1]
        debug_print(f"Label: {label}, agent name: {agent_name}")

        with mcp_lock:
            if label not in active_mcp_servers or active_mcp_servers[label].get('status') != 'connected':
                console.print(f"[red]Error: MCP server '{label}' not found or not connected.[/red]")
                return False

            # Get the tools for this server from cache
            tools = mcp_tools_cache.get(label, [])
            if not tools:
                debug_print(f"No cached tools found for server '{label}'")
                console.print(f"[yellow]No cached tools found for MCP server '{label}'.[/yellow]")
                # Optionally try listing again? For now, rely on cache populated during load.
                return False

        # Find the agent (agent search code unchanged)
        agent = None
        debug_print("Looking for agent in REPL context")
        if 'cai.repl.repl' in sys.modules:
            repl = sys.modules['cai.repl.repl']
            debug_print(f"REPL module found: {repl}")
            if hasattr(repl, 'client') and repl.client:
                debug_print("Client found in REPL")
                if agent_name == 'current' and hasattr(repl, 'current_agent'):
                    agent = repl.current_agent
                    debug_print(f"Using current agent: {agent.name if agent else None}")
                elif agent_name == 'active' and hasattr(repl.client, 'active_agent'):
                    agent = repl.client.active_agent
                    debug_print(f"Using active agent: {agent.name if agent else None}")
                elif hasattr(repl, 'get_available_agents'):
                    try:
                        debug_print("Looking in get_available_agents")
                        agents = repl.get_available_agents()
                        debug_print(f"Available agents: {list(agents.keys())}")
                        if agent_name in agents:
                            agent = agents[agent_name]
                            debug_print(f"Agent found by name: {agent.name}")
                    except Exception as e:
                        debug_print(f"Error getting available agents: {e}")
        
        # Alternative method from cai.agents module
        if not agent:
            debug_print("Trying alternative method from cai.agents")
            try:
                from cai.agents import get_available_agents
                agents = get_available_agents()
                debug_print(f"Available agents (from cai.agents): {list(agents.keys())}")
                if agent_name in agents:
                    agent = agents[agent_name]
                    debug_print(f"Agent found in cai.agents: {agent.name}")
            except Exception as e:
                debug_print(f"Error importing from cai.agents: {e}")
                traceback.print_exc()
        
        # Final check - specific to REPL context
        if not agent and 'cai.repl.repl' in sys.modules:
            repl = sys.modules['cai.repl.repl']
            if hasattr(repl, 'agent') and repl.agent:
                debug_print(f"Checking global agent in REPL: {repl.agent.name}")
                if agent_name == repl.agent.name:
                    agent = repl.agent
                    debug_print("Using global REPL agent")
        
        if not agent:
            debug_print(f"Could not find agent '{agent_name}'")
            console.print(f"[red]Error: Could not find agent '{agent_name}'.[/red]")
            console.print("[yellow]Special values available: 'current', 'active'[/yellow]")
            return False

        console.print(f"Adding tools from MCP server '{label}' to agent '{agent.name}'...")
        debug_print(f"Agent found: {agent.name}, adding {len(tools)} tools")

        # Add tools to the agent
        if not hasattr(agent, 'functions') or not isinstance(agent.functions, list):
            agent.functions = []
            debug_print("Initializing agent functions list")
            
        # Keep track of existing function names
        existing_names = {f.__name__ for f in agent.functions if callable(f)}
        debug_print(f"Existing function names: {existing_names}")
        
        # Track results
        added_count = 0
        skipped_count = 0
        error_count = 0
        
        # Create a table to display results
        results_table = Table(title=f"Adding tools to {agent.name}")
        results_table.add_column("Tool", style="cyan")
        results_table.add_column("Status", style="green")
        results_table.add_column("Details", style="yellow")
        
        for tool in tools:
            debug_print(f"Processing tool: {tool.name}")
            
            try:
                # Create wrapper function for this tool
                wrapper = create_tool_wrapper(
                    server_label=label,
                    tool_name=tool.name,
                    tool_desc=tool.description,
                    schema=tool.inputSchema
                )
                
                # Check for name conflicts
                if wrapper.__name__ in existing_names:
                    debug_print(f"Skipping tool '{tool.name}' - name conflict with '{wrapper.__name__}'")
                    results_table.add_row(
                        tool.name, 
                        "[yellow]Skipped[/yellow]", 
                        f"Name conflict with existing function: {wrapper.__name__}"
                    )
                    skipped_count += 1
                    continue
                    
                # Add tool to agent's functions
                agent.functions.append(wrapper)
                existing_names.add(wrapper.__name__)
                added_count += 1
                
                debug_print(f"Tool added: {tool.name} as {wrapper.__name__}")
                results_table.add_row(
                    tool.name,
                    "[green]Added[/green]",
                    f"Available as: {wrapper.__name__}"
                )
                
            except Exception as e:
                debug_print(f"Error creating wrapper for tool '{tool.name}': {e}")
                results_table.add_row(
                    tool.name,
                    "[red]Error[/red]",
                    str(e)
                )
                error_count += 1
        
        # Print results table
        console.print(results_table)
        
        # Print summary
        if added_count > 0:
            console.print(f"[green]Added {added_count} tools from server '{label}' to agent '{agent.name}'.[/green]")
        if skipped_count > 0:
            console.print(f"[yellow]Skipped {skipped_count} tools due to name conflicts.[/yellow]")
        if error_count > 0:
            console.print(f"[red]Encountered {error_count} errors while processing tools.[/red]")
        
        return True

# Register the command
register_command(McpCommand())