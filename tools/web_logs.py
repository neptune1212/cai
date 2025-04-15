from flask import Flask, render_template
import pandas as pd
import matplotlib.pyplot as plt
import io
import base64
from datetime import datetime
import os
import folium
import requests
import argparse
from typing import Dict, Optional

app = Flask(__name__)

# Configuration for enabled visualizations
class Config:
    def __init__(self):
        self.enable_map = False  # Default to disabled
        self.enable_daily_logs = True
        self.enable_system_dist = True
        self.enable_user_activity = True
        
    @classmethod
    def from_args(cls, args):
        config = cls()
        # Handle map options - disable takes precedence
        if hasattr(args, 'disable_map') and args.disable_map:
            config.enable_map = False
        elif hasattr(args, 'enable_map') and args.enable_map:
            config.enable_map = True
            
        if hasattr(args, 'disable_daily'):
            config.enable_daily_logs = not args.disable_daily
        if hasattr(args, 'disable_system'):
            config.enable_system_dist = not args.disable_system
        if hasattr(args, 'disable_users'):
            config.enable_user_activity = not args.disable_users
        return config

# Visualization components
class Visualizations:
    def __init__(self, df: pd.DataFrame, config: Config):
        self.df = df
        self.config = config
        
    def create_daily_logs(self) -> Optional[str]:
        if not self.config.enable_daily_logs:
            return None
            
        plt.figure(figsize=(12, 6))
        daily_counts = self.df.set_index('timestamp').resample('D').size()
        daily_counts.index = daily_counts.index.strftime('%Y-%m-%d')  # Format the index to 'yyyy-mm-dd'
        
        # Plot bar chart for daily counts
        ax = daily_counts.plot(kind='bar', color='skyblue', label='Daily Count')
        
        # Plot line chart for cumulative counts
        cumulative_counts = daily_counts.cumsum()
        cumulative_counts.plot(kind='line', color='orange', secondary_y=True, ax=ax, label='Cumulative Count')
        
        # Add vertical red line on 2025-04-08
        if '2025-04-08' in daily_counts.index:
            red_line_index = daily_counts.index.get_loc('2025-04-08')
            ax.axvline(x=red_line_index, color='red', linestyle='--', label='Public Release v0.3.11')
            
            # Add grey-ish background to all elements prior to the red line
            ax.axvspan(0, red_line_index, color='grey', alpha=0.3)
        
        # Add vertical yellow line on 2025-04-01
        if '2025-04-01' in daily_counts.index:
            yellow_line_index = daily_counts.index.get_loc('2025-04-01')
            ax.axvline(x=yellow_line_index, color='yellow', linestyle='--', label='Professional Bug Bounty Test')
        
        # Set titles and labels
        ax.set_title('Number of Logs by Day')
        ax.set_xlabel('Date')
        ax.set_ylabel('Number of Logs')
        ax.right_ax.set_ylabel('Cumulative Count')
        ax.set_xticklabels(daily_counts.index, rotation=45)
        
        # Add legends
        ax.legend(loc='upper left')
        ax.right_ax.legend(loc='upper right')
        
        plt.tight_layout()
        return self._get_plot_base64()

    def create_system_distribution(self) -> Optional[str]:
        if not self.config.enable_system_dist:
            return None
            
        plt.figure(figsize=(10, 6))
        system_map = {
            'linux': 'Linux', 
            'darwin': 'Darwin', 
            'windows': 'Windows',
            'microsoft': 'Windows',
            'wsl': 'Windows'
        }
        self.df['system_grouped'] = self.df['system'].map(system_map).fillna('Other')
        system_counts = self.df['system_grouped'].value_counts()
        system_counts.plot(kind='bar')
        plt.title('Total Number of Logs per System')
        plt.xlabel('System')
        plt.ylabel('Number of Logs')
        plt.tight_layout()
        return self._get_plot_base64()

    def create_user_activity(self) -> Optional[str]:
        if not self.config.enable_user_activity:
            return None
            
        plt.figure(figsize=(12, 6))
        user_counts = self.df['username'].value_counts().head(10)
        user_counts.plot(kind='bar')
        plt.title('Top 10 Most Active Users')
        plt.xlabel('Username')
        plt.ylabel('Number of Logs')
        plt.xticks(rotation=45)
        plt.tight_layout()
        return self._get_plot_base64()

    def create_map(self) -> Optional[str]:
        if not self.config.enable_map:
            return None
            
        m = folium.Map(location=[40, -3], zoom_start=4)
        for _, row in self.df.iterrows():
            location = get_location(row['ip_address'])
            folium.Marker(
                location,
                popup=f"{row['username']} ({row['ip_address']})<br>{row['timestamp']}",
                tooltip=row['username'],
            ).add_to(m)
        return m._repr_html_()

    def _get_plot_base64(self) -> str:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        plot_data = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return plot_data

def parse_logs(file_path, parse_ips=False):
    logs = []
    with open(file_path, 'r') as file:
        for line in file:
            try:
                parts = line.strip().split(None, 2)
                if len(parts) != 3:
                    continue
                
                timestamp = parts[0] + ' ' + parts[1]
                size = parts[2].split()[0]
                filename = parts[2].split()[1] if len(parts[2].split()) > 1 else parts[2]

                if 'cai_' not in filename:
                    continue

                metadata = filename.split('cai_')[1].replace('.jsonl', '')
                segments = metadata.split('_')

                if len(segments) < 7:
                    continue

                username = segments[2]
                system = segments[3].lower()
                version = segments[4]

                if 'microsoft' in system or 'wsl' in version.lower():
                    system = 'windows'

                # Only process IP if mapping is enabled
                if parse_ips:
                    ip_parts = segments[-4:]
                    ip_address = '.'.join(ip_parts)
                else:
                    ip_address = 'disabled'  # Use placeholder when IP parsing is disabled

                logs.append([timestamp, size, ip_address, system, username])

            except Exception as e:
                print(f"Error parsing line: {line.strip()} -> {e}")
                continue

    return logs

def get_location(ip):
    if ip in ("127.0.0.1", "localhost"):
        return 42.85, -2.67  # Vitoria

    # API 1: ip-api.com
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        data = response.json()
        if response.status_code == 200 and data.get("status") == "success":
            return data["lat"], data["lon"]
    except Exception:
        pass

    # API 2: ipinfo.io
    try:
        response = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5)
        data = response.json()
        if response.status_code == 200 and "loc" in data:
            lat, lon = map(float, data["loc"].split(","))
            return lat, lon
    except Exception:
        pass

    # API 3: ipwho.is
    try:
        response = requests.get(f"https://ipwho.is/{ip}", timeout=5)
        data = response.json()
        if response.status_code == 200 and data.get("success") is True:
            return data["latitude"], data["longitude"]
    except Exception:
        pass

    # Fallback
    return 42.85, -2.67

@app.route('/')
def index():
    # Get log file path from app config
    log_file = app.config['LOG_FILE']
    
    # Parse logs
    logs = parse_logs(log_file)
    if not logs:
        return f"No logs were parsed. Please check if the file {log_file} exists and contains valid log entries."
    
    df = pd.DataFrame(logs, columns=['timestamp', 'size', 'ip_address', 'system', 'username'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Create visualizations
    viz = Visualizations(df, app.config['VIZ_CONFIG'])
    
    # Only create enabled visualizations
    visualizations = {
        'logs_by_day': viz.create_daily_logs(),
        'logs_by_system': viz.create_system_distribution(),
        'active_users': viz.create_user_activity(),
        'config': app.config['VIZ_CONFIG']
    }
    
    # Only create map if enabled
    if app.config['VIZ_CONFIG'].enable_map:
        visualizations['map_html'] = viz.create_map()
    
    return render_template('logs.html', **visualizations)

def parse_args():
    parser = argparse.ArgumentParser(description='Web-based log analysis dashboard')
    parser.add_argument('log_file', nargs='?', default='/tmp/logs.txt',
                      help='Path to the log file (default: /tmp/logs.txt)')
    
    # Map control group
    map_group = parser.add_mutually_exclusive_group()
    map_group.add_argument('--enable-map', action='store_true',
                      help='Enable the geographic distribution map (default: disabled)')
    map_group.add_argument('--disable-map', action='store_true',
                      help='Disable the geographic distribution map (takes precedence)')
    
    parser.add_argument('--disable-daily', action='store_true',
                      help='Disable the daily logs chart')
    parser.add_argument('--disable-system', action='store_true',
                      help='Disable the system distribution chart')
    parser.add_argument('--disable-users', action='store_true',
                      help='Disable the user activity chart')
    parser.add_argument('--port', type=int, default=5001,
                      help='Port to run the server on (default: 5001)')
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_args()
    
    # Ensure the log file exists
    if not os.path.exists(args.log_file):
        print(f"Error: {args.log_file} not found!")
        exit(1)
    
    # Configure the application
    app.config['LOG_FILE'] = args.log_file
    app.config['VIZ_CONFIG'] = Config.from_args(args)
    
    print(f"Starting web server on http://localhost:{args.port}")
    print(f"Using log file: {args.log_file}")
    app.run(host='0.0.0.0', port=args.port, debug=True) 