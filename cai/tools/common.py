"""
Basic utilities for executing tools
inside or outside of virtual containers.
"""
import subprocess  # nosec B404
import threading
import os
import pty
import signal
import time
import uuid
from wasabi import color  # pylint: disable=import-error
from typing import Optional, List, Dict, Any

# Global dictionary to store active sessions
ACTIVE_SESSIONS = {}

def _get_workspace_dir() -> str:
    """Determines the target workspace directory based on env vars for host."""
    # This function is for the HOST perspective. Container path is separate.
    
    if os.getenv('CTF_INSIDE', "false").lower() == "true":
        return "/"
        
    base_dir_env = os.getenv("CAI_WORKSPACE_DIR")
    workspace_name = os.getenv("CAI_WORKSPACE")

    # Determine the base directory
    if base_dir_env:
        # Use the specified base directory
        base_dir = os.path.abspath(base_dir_env)
    else:
        # Default base directory is 'workspaces' relative to CWD
        # unless workspace_name is not set, then it's just CWD.
        if workspace_name:
            base_dir = os.path.join(os.getcwd(), "workspaces")
        else:
            # If no workspace name is set, the workspace IS the CWD.
             return os.getcwd()

    # If a workspace name is provided, append it to the base directory
    if workspace_name:
        # Basic validation - allow alphanumeric, underscore, hyphen
        if not all(c.isalnum() or c in ['_', '-'] for c in workspace_name):
            print(color(f"Invalid CAI_WORKSPACE name '{workspace_name}'. "
                        f"Using directory '{base_dir}' instead.", fg="yellow"))
            # Fallback to base_dir if name is invalid
            target_dir = base_dir
        else:
             target_dir = os.path.join(base_dir, workspace_name)
    else:
         # If no workspace name, the target is the base directory itself.
         # This case is typically handled earlier, but included for clarity.
         target_dir = base_dir

    # Ensure the final target directory exists on the host
    try:
        # Use abspath to resolve any relative paths like '.'
        abs_target_dir = os.path.abspath(target_dir)
        os.makedirs(abs_target_dir, exist_ok=True)
        return abs_target_dir
    except OSError as e:
        print(color(f"Error creating/accessing host workspace directory '{abs_target_dir}': {e}",
                    fg="red")) # noqa E501
        # Critical fallback: If directory creation fails, revert to CWD
        print(color(f"Falling back to current directory: {os.getcwd()}", fg="yellow"))
        return os.getcwd()


def _get_container_workspace_path() -> str:
    """Determines the target workspace path inside the container."""
    workspace_name = os.getenv("CAI_WORKSPACE")
    ctf_inside = os.getenv('CTF_INSIDE', "true").lower() == "true"

    # When CTF_INSIDE is true, always use root directory
    if ctf_inside:
        return "/"

    if workspace_name:
        # Basic validation - allow alphanumeric, underscore, hyphen
        if not all(c.isalnum() or c in ['_', '-'] for c in workspace_name):
            print(color(f"Invalid CAI_WORKSPACE name '{workspace_name}' for container. "
                        f"Using '/workspace'.", fg="yellow"))
            # Fallback to default container workspace root if name invalid
            return "/"
        # Standard path inside CAI containers
        return f"/workspace/workspaces/{workspace_name}"
    else:
        # If CAI_WORKSPACE is not set, default to /workspace inside container
        return "/"


class ShellSession:  # pylint: disable=too-many-instance-attributes
    """Class to manage interactive shell sessions"""

    def __init__(self, command, session_id=None, ctf=None, workspace_dir=None, container_id=None): # noqa E501
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.original_command = command  # Store original for logging
        self.ctf = ctf
        self.container_id = container_id # Store container ID if applicable
        # Determine workspace based on context (container > ctf > local host)
        if self.container_id:
            self.workspace_dir = _get_container_workspace_path()
        elif self.ctf:
            # CTF context might specify its own workspace, otherwise use host logic
            self.workspace_dir = workspace_dir or _get_workspace_dir()
        else:
             # Local host context
            self.workspace_dir = _get_workspace_dir()

        self.process = None
        self.master = None
        self.slave = None
        self.output_buffer = []
        self.is_running = False
        self.last_activity = time.time()

        # Prepare the command based on context
        self.command = self._prepare_command(command)

    def _prepare_command(self, command):
        """Prepares the command for execution within the correct context."""
        if self.container_id:
             # For containers, the command runs via `docker exec -w WORKSPACE`
             # No need to prefix with 'cd' here. The wrapper handles it.
            return command
        if self.ctf:
             # For CTF, always change directory first
            return f"cd '{self.workspace_dir}' && {command}"
        # For local, cwd is handled by Popen/run, no prefix needed
        return command

    def start(self):
        """Start the shell session in the appropriate environment."""
        start_message_cmd = self.original_command # Use original for messages

        # --- Start in Container ---
        if self.container_id:
            try:
                self.master, self.slave = pty.openpty()
                # Command to start the interactive shell inside the container's workspace
                docker_cmd_list = [
                    "docker", "exec", "-i", # Use -i for interactive
                    "-w", self.workspace_dir, # Set working directory
                    self.container_id,
                    "sh", "-c", # Use shell to handle complex commands if needed
                    self.command # The actual command to run
                ]
                self.process = subprocess.Popen(
                    docker_cmd_list,
                    stdin=self.slave,
                    stdout=self.slave,
                    stderr=self.slave,
                    preexec_fn=os.setsid,
                    universal_newlines=True
                )
                self.is_running = True
                self.output_buffer.append(
                    f"[Session {self.session_id}] Started in container {self.container_id[:12]}: "
                    f"{start_message_cmd} in {self.workspace_dir}")
                threading.Thread(target=self._read_output, daemon=True).start()
            except Exception as e:
                self.output_buffer.append(f"Error starting container session: {str(e)}")
                self.is_running = False
            return

        # --- Start in CTF ---
        if self.ctf:
            self.is_running = True
            self.output_buffer.append(
                f"[Session {self.session_id}] Started CTF command: "
                f"{start_message_cmd} in {self.workspace_dir}")
            try:
                # Execute the prepared command (includes cd prefix)
                output = self.ctf.get_shell(self.command)
                self.output_buffer.append(output)
            except Exception as e:  # pylint: disable=broad-except
                self.output_buffer.append(f"Error executing CTF command: {str(e)}")
            self.is_running = False # CTF get_shell is typically blocking
            return

        # --- Start Locally (Host) ---
        try:
            self.master, self.slave = pty.openpty()
            self.process = subprocess.Popen(  # pylint: disable=subprocess-popen-preexec-fn, consider-using-with # noqa: E501
                self.command, # Local command doesn't need cd prefix
                shell=True,  # nosec B602 - Allows complex commands locally
                stdin=self.slave,
                stdout=self.slave,
                stderr=self.slave,
                cwd=self.workspace_dir, # Set CWD for local process
                preexec_fn=os.setsid,
                universal_newlines=True
            )
            self.is_running = True
            self.output_buffer.append(
                f"[Session {self.session_id}] Started locally: "
                f"{start_message_cmd} in {self.workspace_dir}")
            threading.Thread(target=self._read_output, daemon=True).start()
        except Exception as e:  # pylint: disable=broad-except
            self.output_buffer.append(f"Error starting local session: {str(e)}")
            self.is_running = False

    def _read_output(self):
        """Read output from the process (works for local and container)"""
        try:
            while self.is_running and self.master is not None:
                try:
                    # Check if process has exited before reading
                    if self.process and self.process.poll() is not None:
                        self.is_running = False
                        break
                    output = os.read(self.master, 1024).decode()
                    if output:
                        self.output_buffer.append(output)
                        self.last_activity = time.time()
                    else: # End of file usually means process terminated
                        self.is_running = False
                        break
                except OSError: # E.g., EIO when PTY closes
                    self.is_running = False
                    break
                except Exception as read_err: # Catch other potential errors
                     self.output_buffer.append(f"Error reading output buffer: {str(read_err)}")
                     self.is_running = False
                     break
                # Add a small sleep to prevent busy-waiting if no output
                if self.is_running:
                     time.sleep(0.05)

        except Exception as e: # Catch errors in the loop setup itself
            self.output_buffer.append(f"Error in read_output loop: {str(e)}")
            self.is_running = False
        finally:
             # Ensure PTYs are closed if master exists
             if self.master:
                 try:
                     os.close(self.master)
                 except OSError: pass # Ignore errors if already closed
                 self.master = None
             if self.slave:
                 try:
                     os.close(self.slave)
                 except OSError: pass # Ignore errors if already closed
                 self.slave = None
             # Mark as not running definitively
             self.is_running = False
             # Add final status message if process exited unexpectedly
             if self.process and self.process.poll() is not None:
                 self.output_buffer.append(f"[Session {self.session_id}] Process terminated.")


    def is_process_running(self):
        """Check if the process is still running"""
        if self.container_id or self.ctf: # Check session flag for remote
            return self.is_running
        # For local, check the process object
        if not self.process:
            return False
        return self.process.poll() is None

    def send_input(self, input_data):
        """Send input to the process (local or container)"""
        if not self.is_running:
            # If the session *thinks* it's not running, double-check the process
            # (primarily for local processes that might have finished quickly)
            if self.process and self.process.poll() is None:
                self.is_running = True # Correct the state if process is alive
            else:
                 return "Session is not running"


        try:
            # --- Send to CTF ---
            if self.ctf:
                output = self.ctf.get_shell(input_data)
                self.output_buffer.append(output)
                return "Input sent to CTF session"

            # --- Send to Local or Container PTY ---
            if self.master is not None:
                input_data_bytes = (input_data.rstrip() + "\n").encode()
                bytes_written = os.write(self.master, input_data_bytes)
                if bytes_written != len(input_data_bytes):
                     # Handle potential short writes (less likely with os.write)
                     self.output_buffer.append("[Session {self.session_id}] Warning: Partial input write.")
                self.last_activity = time.time()
                return "Input sent to session"
            else:
                return "Session PTY not available for input"

        except OSError as e:
             # Handle cases where the PTY might have closed unexpectedly
             self.output_buffer.append(f"Error sending input (OSError): {str(e)}")
             self.is_running = False # Mark session as dead
             return f"Error sending input: {str(e)}"
        except Exception as e:  # pylint: disable=broad-except
            self.output_buffer.append(f"Error sending input: {str(e)}")
            return f"Error sending input: {str(e)}"

    def get_output(self, clear=True):
        """Get and optionally clear the output buffer"""
        # Give a very brief moment for any final output to be read
        # time.sleep(0.05)
        output = "\n".join(self.output_buffer) # Join without extra newlines
        if clear:
            self.output_buffer = []
        return output

    def terminate(self):
        """Terminate the session (local or container)"""
        session_id_short = self.session_id[:8]
        if not self.is_running:
             # Double-check local process status
             if self.process and self.process.poll() is None:
                 pass # Process is running, proceed with termination
             else:
                 return f"Session {session_id_short} already terminated or finished."

        termination_message = f"Session {session_id_short} terminated."
        try:
            self.is_running = False # Mark as not running first

            # --- Terminate CTF ---
            if self.ctf:
                # CTF sessions usually finish on their own or don't support termination
                return f"Session {session_id_short} (CTF) finished or cannot be terminated externally." # noqa E501

            # --- Terminate Local or Container Process ---
            if self.process:
                pgid = None
                try:
                    # Get process group ID to terminate all children
                    pgid = os.getpgid(self.process.pid)
                    os.killpg(pgid, signal.SIGTERM) # Try graceful termination first
                    # Wait a very short time
                    self.process.wait(timeout=0.5)
                except ProcessLookupError:
                     pass # Process already gone
                except subprocess.TimeoutExpired:
                     print(color(f"Session {session_id_short} did not terminate gracefully, sending SIGKILL...", fg="yellow")) # noqa E501
                     try:
                          if pgid:
                              os.killpg(pgid, signal.SIGKILL) # Force kill
                          else:
                              self.process.kill()
                     except ProcessLookupError:
                          pass # Already gone
                     except Exception as kill_err:
                          termination_message += f" (Error during SIGKILL: {kill_err})"
                except Exception as term_err: # Catch other errors during SIGTERM
                     termination_message += f" (Error during SIGTERM: {term_err})"
                     # Fallback to simpler kill if killpg failed
                     try:
                         self.process.kill()
                     except Exception: pass # Ignore nested errors


                # Final check
                if self.process.poll() is None:
                     print(color(f"Session {session_id_short} process {self.process.pid} may still be running after termination attempts.", fg="red")) # noqa E501
                     termination_message += " (Warning: Process may still be running)"


            # Clean up PTY resources if they exist
            if self.master:
                try: os.close(self.master)
                except OSError: pass
                self.master = None
            if self.slave:
                try: os.close(self.slave)
                except OSError: pass
                self.slave = None

            return termination_message

        except Exception as e:  # pylint: disable=broad-except
            return f"Error terminating session {session_id_short}: {str(e)}"


def create_shell_session(command, ctf=None, container_id=None, **kwargs):
    """Create a new shell session in the correct workspace/environment."""
    if container_id:
        # Workspace is determined internally by ShellSession using _get_container_workspace_path
        session = ShellSession(command, ctf=ctf, container_id=container_id)
    else:
        # For local sessions, determine workspace using host logic
        workspace_dir = _get_workspace_dir()
        session = ShellSession(command, ctf=ctf, workspace_dir=workspace_dir)

    session.start()
    # Check if session started successfully before adding
    if session.is_running or (ctf and not session.is_running): # CTF might finish quickly
         ACTIVE_SESSIONS[session.session_id] = session
         return session.session_id
    else:
         # If start failed, return the error message from the buffer
         error_msg = session.get_output(clear=True)
         print(color(f"Failed to start session: {error_msg}", fg="red"))
         return f"Failed to start session: {error_msg}"


def list_shell_sessions():
    """List all active shell sessions"""
    result = []
    # Iterate over a copy of keys to allow deletion during iteration
    for session_id in list(ACTIVE_SESSIONS.keys()):
        session = ACTIVE_SESSIONS.get(session_id)
        if not session: continue # Should not happen, but safety check

        # Clean up sessions that are no longer running
        # For CTF, is_running might be False if it finished, keep it listed once.
        if not session.is_running and not session.ctf:
            # For local/container, double check process if possible
            process_truly_dead = True
            if session.process:
                process_truly_dead = session.process.poll() is not None

            if process_truly_dead:
                 del ACTIVE_SESSIONS[session_id]
                 continue # Don't list dead sessions

        # Format the output for active sessions
        env_type = "Local"
        if session.container_id:
            env_type = f"Container({session.container_id[:12]})"
        elif session.ctf:
            env_type = "CTF"

        result.append({
            "session_id": session_id,
            "command": session.original_command,
            "environment": env_type,
            "workspace": session.workspace_dir,
            "running": session.is_running, # Reflects current known state
            "last_activity": time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(session.last_activity))
        })
    return result


def send_to_session(session_id, input_data):
    """Send input to a specific session"""
    if session_id not in ACTIVE_SESSIONS:
        return f"Session {session_id} not found or already terminated."

    session = ACTIVE_SESSIONS[session_id]
    return session.send_input(input_data)


def get_session_output(session_id, clear=True):
    """Get output from a specific session"""
    if session_id not in ACTIVE_SESSIONS:
        return f"Session {session_id} not found or already terminated."

    session = ACTIVE_SESSIONS[session_id]
    return session.get_output(clear)


def terminate_session(session_id):
    """Terminate a specific session"""
    if session_id not in ACTIVE_SESSIONS:
        return f"Session {session_id} not found or already terminated."

    session = ACTIVE_SESSIONS[session_id]
    result = session.terminate()
    # Remove from active sessions only after successful termination attempt
    if session_id in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[session_id]
    return result


def _run_ctf(ctf, command, stdout=False, timeout=100, workspace_dir=None):
    """Runs command in CTF env, changing to workspace_dir first."""
    target_dir = workspace_dir or _get_workspace_dir()
    full_command = f"cd '{target_dir}' && {command}"
    original_cmd_for_msg = command # For logging
    context_msg = f"(ctf:{target_dir})"
    try:
        output = ctf.get_shell(full_command, timeout=timeout)
        if stdout:
            print(f"\033[32m{context_msg} $ {original_cmd_for_msg}\n{output}\033[0m") # noqa E501
        return output
    except Exception as e:  # pylint: disable=broad-except
        error_msg = f"Error executing CTF command '{original_cmd_for_msg}' in '{target_dir}': {e}" # noqa E501
        print(color(error_msg, fg="red"))
        return error_msg


def _run_ssh(command, stdout=False, timeout=100, workspace_dir=None):
    """Runs command via SSH. Assumes SSH agent or passwordless setup unless sshpass is used externally.""" # noqa E501
    ssh_user = os.environ.get('SSH_USER')
    ssh_host = os.environ.get('SSH_HOST')
    ssh_pass = os.environ.get('SSH_PASS') # Check if password provided

    # NOTE: Workspace dir for SSH is less standard. Commands run relative to user's home dir on remote. # noqa E501
    # If a specific remote path is needed, it should be part of the 'command' itself (e.g., "cd /remote/path && ls") # noqa E501
    remote_command = command
    original_cmd_for_msg = command
    context_msg = f"({ssh_user}@{ssh_host})"

    # Construct base SSH command list
    if ssh_pass:
        # Use sshpass if password is provided
        ssh_cmd_list = ["sshpass", "-p", ssh_pass, "ssh", f"{ssh_user}@{ssh_host}"] # noqa E501
    else:
        # Use regular SSH if no password (assuming key-based auth)
        ssh_cmd_list = ["ssh", f"{ssh_user}@{ssh_host}"]

    # Add the remote command to execute
    ssh_cmd_list.append(remote_command)

    try:
        # Use subprocess.run with list of args for better security than shell=True
        result = subprocess.run(
            ssh_cmd_list,
            capture_output=True,
            text=True,
            check=False, # Don't raise exception on non-zero exit code
            timeout=timeout
        )
        output = result.stdout if result.stdout else result.stderr
        if stdout:
            print(f"\033[32m{context_msg} $ {original_cmd_for_msg}\n{output}\033[0m") # noqa E501
        # Return combined output, potentially including errors
        return output.strip()
    except subprocess.TimeoutExpired as e:
        error_output = e.stdout if e.stdout else str(e)
        timeout_msg = f"Timeout executing SSH command: {error_output}"
        if stdout:
            print(f"\033[33m{context_msg} $ {original_cmd_for_msg}\nTIMEOUT\n{error_output}\033[0m") # noqa E501
        return timeout_msg
    except FileNotFoundError:
         # Handle case where ssh or sshpass isn't installed
         error_msg = f"'sshpass' or 'ssh' command not found. Ensure they are installed and in PATH." # noqa E501
         print(color(error_msg, fg="red"))
         return error_msg
    except Exception as e:  # pylint: disable=broad-except
        error_msg = f"Error executing SSH command '{original_cmd_for_msg}' on {ssh_host}: {e}" # noqa E501
        print(color(error_msg, fg="red"))
        return error_msg


def _run_local(command, stdout=False, timeout=100, workspace_dir=None):
    """Runs command locally in the specified workspace_dir."""
    target_dir = workspace_dir or _get_workspace_dir()
    original_cmd_for_msg = command # For logging
    context_msg = f"(local:{target_dir})"
    try:
        # Use subprocess.run with shell=True carefully for local commands
        # This allows shell features like pipes, redirection if needed in the command string # noqa E501
        # Consider security implications if command string comes from untrusted input.
        result = subprocess.run(
            command,
            shell=True,  # nosec B602
            capture_output=True,
            text=True,
            check=False, # Don't raise exception on non-zero exit
            timeout=timeout,
            cwd=target_dir # Set CWD for local process
        )
        output = result.stdout if result.stdout else result.stderr
        if stdout:
            print(f"\033[32m{context_msg} $ {original_cmd_for_msg}\n{output}\033[0m") # noqa E501
        # Return combined output, potentially including errors
        return output.strip()
    except subprocess.TimeoutExpired as e:
        error_output = e.stdout if e.stdout else str(e)
        timeout_msg = f"Timeout executing local command: {error_output}"
        if stdout:
            print(f"\033[33m{context_msg} $ {original_cmd_for_msg}\nTIMEOUT\n{error_output}\033[0m") # noqa E501
        return timeout_msg
    except Exception as e:  # pylint: disable=broad-except
        error_msg = f"Error executing local command '{original_cmd_for_msg}' in '{target_dir}': {e}" # noqa E501
        print(color(error_msg, fg="red"))
        return error_msg


def run_command(command: str, ctf=None, stdout: bool = False,
                async_mode: bool = False, session_id: Optional[str] = None,
                timeout: int = 100) -> str:
    """
    Run command in the appropriate environment (Docker, CTF, SSH, Local)
    and workspace.

    Args:
        command: The command string to execute.
        ctf: CTF environment object (if running in CTF).
        stdout: Whether to print command and output to stdout with context.
        async_mode: Whether to run the command asynchronously in a session.
        session_id: ID of an existing session to send the command to.
        timeout: Timeout for synchronous commands (in seconds).

    Returns:
        str: Command output, status message, or session ID.
    """
    # 1. Handle Session Interaction
    if session_id:
        if session_id not in ACTIVE_SESSIONS:
            return f"Session {session_id} not found or already terminated."
        session = ACTIVE_SESSIONS[session_id]
        result = session.send_input(command) # Send the raw command string
        if stdout:
            # Output is read from the session, reflects its context
            output = get_session_output(session_id, clear=False)
            env_type = "Local"
            if session.container_id:
                 env_type = f"Container({session.container_id[:12]})"
            elif session.ctf:
                 env_type = "CTF"
            print(f"\033[32m(Session {session_id} in {env_type}:{session.workspace_dir}) >> {command}\n{output}\033[0m") # noqa E501
        return result # Return the result of sending input ("Input sent..." or error)

    # 2. Determine Execution Environment (Container > CTF > SSH > Local)
    active_container = os.getenv("CAI_ACTIVE_CONTAINER", "")
    is_ssh_env = all(os.getenv(var) for var in ['SSH_USER', 'SSH_HOST'])

    # --- Docker Container Execution ---
    if active_container and not ctf and not is_ssh_env:
        container_id = active_container
        container_workspace = _get_container_workspace_path()
        context_msg = f"(docker:{container_id[:12]}:{container_workspace})"

        # Handle Async Session Creation in Container
        if async_mode:
            # Create a session specifically for the container environment
            new_session_id = create_shell_session(command, container_id=container_id) # noqa E501
            if "Failed" in new_session_id: # Check if session creation failed
                 return new_session_id
            if stdout:
                # Wait a moment for initial output
                time.sleep(0.2)
                output = get_session_output(new_session_id, clear=False)
                print(f"\033[32m(Started Session {new_session_id} in {context_msg})\n{output}\033[0m") # noqa E501
            return f"Started async session {new_session_id} in container {container_id[:12]}. Use this ID to interact." # noqa E501

        # Handle Synchronous Execution in Container
        try:
            # Ensure container workspace exists (best effort)
            # Consider moving this to workspace set/container activation
            mkdir_cmd = ["docker", "exec", container_id, "mkdir", "-p", container_workspace] # noqa E501
            subprocess.run(mkdir_cmd, capture_output=True, text=True, check=False, timeout=10) # noqa E501

            # Construct the docker exec command with workspace context
            cmd_list = [
                "docker", "exec",
                "-w", container_workspace, # Set working directory
                container_id,
                "sh", "-c", command # Execute command via shell
            ]
            result = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                check=False, # Don't raise exception on non-zero exit
                timeout=timeout
            )

            output = result.stdout if result.stdout else result.stderr
            output = output.strip() # Clean trailing newline

            if stdout:
                print(f"\033[32m{context_msg} $ {command}\n{output}\033[0m") # noqa E501

            # Check if command failed specifically because container isn't running
            if result.returncode != 0 and "is not running" in result.stderr:
                print(color(f"{context_msg} Container is not running. Attempting execution on host instead.", fg="yellow")) # noqa E501
                 # Fallback to local execution, preserving workspace context
                return _run_local(command, stdout, timeout, _get_workspace_dir()) # noqa E501

            return output # Return combined stdout/stderr

        except subprocess.TimeoutExpired:
            timeout_msg = "Timeout executing command in container."
            if stdout:
                print(f"\033[33m{context_msg} $ {command}\nTIMEOUT\033[0m") # noqa E501
                print(color("Attempting execution on host instead.", fg="yellow"))
             # Fallback to local execution on timeout
            return _run_local(command, stdout, timeout, _get_workspace_dir()) # noqa E501
        except Exception as e:  # pylint: disable=broad-except
            error_msg = f"Error executing command in container: {str(e)}"
            print(color(f"{context_msg} {error_msg}", fg="red"))
            print(color("Attempting execution on host instead.", fg="yellow"))
             # Fallback to local execution on other errors
            return _run_local(command, stdout, timeout, _get_workspace_dir()) # noqa E501

    # --- CTF Execution ---
    if ctf:
         # Async for CTF might need specific implementation if get_shell is blocking
         if async_mode:
              return "Async mode not fully supported for CTF environment via this function yet." # noqa E501
         # _run_ctf handles workspace internally using _get_workspace_dir() default
         return _run_ctf(ctf, command, stdout, timeout) # Pass None for workspace_dir

    # --- SSH Execution ---
    if is_ssh_env:
         # Async for SSH would require session management via SSH client features
         if async_mode:
              return "Async mode not fully supported for SSH environment via this function yet." # noqa E501
         # _run_ssh handles command execution, workspace is relative to remote home
         return _run_ssh(command, stdout, timeout) # Workspace dir less relevant here # noqa E501

    # --- Local Execution (Default Fallback) ---
    # Let _run_local handle determining the host workspace
    # Handle Async Session Creation Locally
    if async_mode:
        # create_shell_session uses _get_workspace_dir() when container_id is None
        new_session_id = create_shell_session(command)
        if isinstance(new_session_id, str) and "Failed" in new_session_id: # Check failure
             return new_session_id
        # Retrieve the actual workspace dir the session is using
        session = ACTIVE_SESSIONS.get(new_session_id)
        actual_workspace = session.workspace_dir if session else "unknown"
        if stdout:
            time.sleep(0.2) # Allow session buffer to populate
            output = get_session_output(new_session_id, clear=False)
            print(f"\033[32m(Started Session {new_session_id} in local:{actual_workspace})\n{output}\033[0m") # noqa E501
        return f"Started async session {new_session_id} locally. Use this ID to interact." # noqa E501

    # Handle Synchronous Execution Locally using _run_local default
    return _run_local(command, stdout, timeout)

# Example Usage (for testing purposes)
# if __name__ == '__main__':
#     print("Testing Local Execution:")
#     print(run_command("pwd", stdout=True))
#     print(run_command("ls -la", stdout=True))
#     print(run_command("echo 'hello local' > test_local.txt && cat test_local.txt", stdout=True)) # noqa E501

#     print("\nTesting Async Local Session:")
#     session_id = run_command("sleep 5 && echo 'Async done'", async_mode=True, stdout=True) # noqa E501
#     print(f"Session ID: {session_id}")
#     time.sleep(1)
#     print("Session output:", get_session_output(session_id))
#     time.sleep(6)
#     print("Final session output:", get_session_output(session_id))
#     print("Terminating session:", terminate_session(session_id))

#     # To test container execution, manually set CAI_ACTIVE_CONTAINER
#     # os.environ['CAI_ACTIVE_CONTAINER'] = 'YOUR_CONTAINER_ID'
#     # print("\nTesting Container Execution (if CAI_ACTIVE_CONTAINER is set):")
#     # if os.getenv('CAI_ACTIVE_CONTAINER'):
#     #      print(run_command("pwd", stdout=True))
#     #      print(run_command("ls -la /workspace/workspaces/cai_default", stdout=True)) # noqa E501
#     #      print(run_command("echo 'hello container' > test_container.txt && cat test_container.txt", stdout=True)) # noqa E501
#     # else:
#     #      print("Skipping container tests. Set CAI_ACTIVE_CONTAINER.")
