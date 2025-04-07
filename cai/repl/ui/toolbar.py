"""
Module for the CAI REPL toolbar functionality.
"""
import datetime
import os
import socket
import platform
import threading
import time
from functools import lru_cache
import requests  # pylint: disable=import-error
from prompt_toolkit.formatted_text import HTML  # pylint: disable=import-error

# Variable to track when to refresh the toolbar
toolbar_last_refresh = [datetime.datetime.now()]

# Cache for toolbar data
toolbar_cache = {
    'html': None,
    'last_update': datetime.datetime.now(),
    'refresh_interval': 5  # Refresh every 5 seconds
}

# Cache for system information that rarely changes
system_info = {
    'ip_address': None,
    'os_name': None,
    'os_version': None
}


@lru_cache(maxsize=1)
def get_system_info():
    """Get system information that rarely changes (cached)."""
    if not system_info['ip_address']:
        try:
            # Get local IP addresses
            hostname = socket.gethostname()
            system_info['ip_address'] = socket.gethostbyname(hostname)
            
            # Get OS information
            system_info['os_name'] = platform.system()
            system_info['os_version'] = platform.release()
        except Exception:  # pylint: disable=broad-except
            system_info['ip_address'] = "unknown"
            system_info['os_name'] = "unknown"
            system_info['os_version'] = "unknown"
    
    return system_info


def update_toolbar_in_background():
    """Update the toolbar cache in a background thread."""
    try:
        # Get system info (cached)
        sys_info = get_system_info()
        ip_address = sys_info['ip_address']
        os_name = sys_info['os_name']
        os_version = sys_info['os_version']

        # Get current logical workspace name from environment variable
        workspace_name = os.getenv("CAI_WORKSPACE", "")
        
        # Get full workspace path
        workspace_path = ""
        if workspace_name:
            # Construct the standard workspace path
            base_dir = os.getenv("CAI_WORKSPACE_DIR", "workspaces")
            standard_workspace_path = os.path.join(base_dir, workspace_name)
            
            # Check if the standard path exists
            if os.path.isdir(standard_workspace_path):
                workspace_path = standard_workspace_path
            elif os.path.isdir(workspace_name):
                # Fallback to direct path if it exists
                workspace_path = os.path.abspath(workspace_name)
            else:
                # Not a valid directory, but show the expected path anyway
                workspace_path = standard_workspace_path

        # Get current active container info
        active_container = os.getenv("CAI_ACTIVE_CONTAINER", "")
        active_env_name = "Host System"
        active_env_icon = "💻"
        active_env_color = "ansiblue"
        
        # If there's an active container, get more details
        if active_container:
            try:
                # Try to get container image name
                import subprocess
                import json
                
                result = subprocess.run(
                    ["docker", "inspect", "--format", "{{.Config.Image}}", active_container],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0:
                    image_name = result.stdout.strip()
                    active_env_name = image_name
                    active_env_icon = "🐳"
                    active_env_color = "ansigreen"
                    
                    # Set more specific icons based on image type
                    if "kali" in image_name.lower():
                        active_env_icon = "🔒"
                    elif "parrot" in image_name.lower():
                        active_env_icon = "🔒"
                    elif "cai" in image_name.lower():
                        active_env_icon = "⭐"
                    
                    # Check if the container is actually running
                    status_check = subprocess.run(
                        ["docker", "ps", "--filter", f"id={active_container}", "--format", "{{.Status}}"],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    if not status_check.stdout.strip():
                        # Container exists but is not running
                        active_env_name = f"{image_name} (stopped)"
                        active_env_color = "ansiyellow"
                
            except Exception:
                # If there's an error getting container details, just show container ID
                active_env_name = f"Container {active_container[:12]}"

        # Get current time for the toolbar refresh indicator
        current_time = datetime.datetime.now().strftime("%H:%M")

        # Add timezone information to show it's local time
        timezone_name = datetime.datetime.now().astimezone().tzname()
        current_time_with_tz = f"{current_time} {timezone_name}"

        # Build the toolbar content
        parts = []
        
        # Environment (always show first and prominently)
        parts.append(f"<{active_env_color}><b>ENV:</b> {active_env_icon} {active_env_name}</{active_env_color}>")
        parts.append(" │ ")
        
        # IP Address
        parts.append("<ansired><b>IP:</b></ansired> ")
        parts.append(f"<ansigreen>{ip_address}</ansigreen>")
        parts.append(" │ ")
        
        # OS Info (shorter version)
        parts.append("<ansiyellow><b>OS:</b></ansiyellow> ")
        parts.append(f"<ansiblue>{os_name}</ansiblue>")
        parts.append(" │ ")
        
        # Workspace (only if set)
        if workspace_name:
            parts.append("<ansimagenta><b>WS:</b></ansimagenta> ")
            parts.append(f"<ansiwhite>{workspace_name}</ansiwhite>")
            parts.append(" │ ")
        
        # Model
        parts.append("<ansiyellow><b>Model:</b></ansiyellow> ")
        parts.append(f"<ansigreen>{os.getenv('CAI_MODEL', 'default')}</ansigreen>")
        parts.append(" │ ")
        
        # Time
        parts.append(f"<ansigray>{current_time_with_tz}</ansigray>")
        
        # Join everything and create HTML formatted text
        toolbar_html = "".join(parts)
        toolbar_cache['html'] = HTML(toolbar_html)
        toolbar_cache['last_update'] = datetime.datetime.now()
        
    except Exception as e:  # pylint: disable=broad-except
        # If there's an error, set a simple toolbar
        error_time = datetime.datetime.now().strftime('%H:%M')
        toolbar_cache['html'] = HTML(f"<ansigray>Error: {str(e)[:30]}... {error_time}</ansigray>")


def get_bottom_toolbar():
    """Get the bottom toolbar with system information (cached)."""
    # If the toolbar is empty, initialize it
    if toolbar_cache['html'] is None:
        # Create a simple initial toolbar while the full one loads
        current_time = datetime.datetime.now().strftime("%H:%M")
        toolbar_cache['html'] = HTML(f"<ansigray>Loading... {current_time}</ansigray>")
        
        # Start background update
        threading.Thread(
            target=update_toolbar_in_background,
            daemon=True
        ).start()
    
    # Return the cached toolbar HTML
    return toolbar_cache['html']


def get_toolbar_with_refresh():
    """Get toolbar with refresh control."""
    now = datetime.datetime.now()
    seconds_elapsed = (now - toolbar_cache['last_update']).total_seconds()
    
    # Check if we need to refresh the toolbar
    if seconds_elapsed >= toolbar_cache['refresh_interval']:
        # Start a background thread to update the toolbar
        threading.Thread(
            target=update_toolbar_in_background,
            daemon=True
        ).start()
    
    # Always return the cached version immediately
    return get_bottom_toolbar()


# Initialize the toolbar on module import
threading.Thread(
    target=update_toolbar_in_background,
    daemon=True
).start()
