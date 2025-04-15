"""
This script is used to create a web-based log analysis dashboard.
It allows you to visualize the logs in different ways and see the PyPI download statistics.

Usage:
    python tools/web_logs.py --enable-map <(tail -n 10 ./logs.txt)
"""

from flask import Flask, render_template
import pandas as pd
import matplotlib.pyplot as plt
#import matplotlib
#matplotlib.use('Agg')
#import matplotlib.pyplot as plt

import io
import base64
from datetime import datetime
import os
import folium
import requests
import argparse
from typing import Dict, Optional
import sys
import json
import numpy as np
from matplotlib.gridspec import GridSpec
from matplotlib.dates import DateFormatter, MonthLocator, WeekdayLocator, DayLocator

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
        
        # Add vertical red line on 2025-04-09
        if '2025-04-09' in daily_counts.index:
            red_line_index = daily_counts.index.get_loc('2025-04-09')
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

def get_overall_stats():
    """Fetch overall download statistics for cai-framework"""
    url = "https://pypistats.org/api/packages/cai-framework/overall"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching overall stats: {response.status_code}")
        return None

def get_system_stats():
    """Fetch system-specific download statistics for cai-framework"""
    url = "https://pypistats.org/api/packages/cai-framework/system"
    response = requests.get(url) 
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching system stats: {response.status_code}")
        return None

def create_pypi_plot():
    # Get the data
    overall_stats = get_overall_stats()
    system_stats = get_system_stats()
    
    if not overall_stats or not system_stats:
        print("Error: Could not fetch PyPI statistics")
        return None, None
    
    # Create a figure with custom layout
    plt.figure(figsize=(15, 8))
    
    # Convert data to DataFrames
    df_overall = pd.DataFrame(overall_stats['data'])
    df_system = pd.DataFrame(system_stats['data'])
    
    # Filter for downloads without mirrors (matches website reporting)
    df_overall_no_mirrors = df_overall[df_overall['category'] == 'without_mirrors']
    without_mirrors_total = df_overall_no_mirrors['downloads'].sum()
    
    # Process the data
    daily_downloads = df_overall_no_mirrors.groupby('date')['downloads'].sum().reset_index()
    daily_downloads['date'] = pd.to_datetime(daily_downloads['date'])
    # Add cumulative downloads
    daily_downloads['cumulative_downloads'] = daily_downloads['downloads'].cumsum()
    
    # Get release date (first date in the dataset)
    release_date = daily_downloads['date'].min()
    
    # Calculate system percentages for each day
    system_pivot = df_system.pivot(index='date', columns='category', values='downloads')
    system_pivot.index = pd.to_datetime(system_pivot.index)
    system_pivot = system_pivot.fillna(0)
    
    # Keep track of the total downloads per system for the legend
    system_totals = system_pivot.sum()
    
    # Create main plot with two y-axes
    ax1 = plt.subplot(111)
    ax2 = ax1.twinx()  # Create a second y-axis sharing the same x-axis
    
    # Plot total cumulative downloads on the left axis
    ax1.plot(daily_downloads['date'], daily_downloads['cumulative_downloads'], 
               linewidth=3, color='black', label='Total Downloads (without mirrors)')
    
    # Define color mapping for systems
    color_map = {
        'Darwin': '#1E88E5',  # Blue
        'Linux': '#FB8C00',   # Orange
        'Windows': '#43A047',  # Green
        'null': '#E53935'     # Red
    }
    
    # Plot system distribution on the right axis
    bottom = np.zeros(len(system_pivot))
    
    # Ensure specific order of systems
    desired_order = ['Darwin', 'Linux', 'Windows', 'null']
    for col in desired_order:
        if col in system_pivot.columns:
            ax2.bar(system_pivot.index, system_pivot[col], 
                      bottom=bottom, label=col, color=color_map[col], 
                      alpha=0.5, width=0.8)
            bottom += system_pivot[col]
    
    # Add release date annotation
    ax1.axvline(x=release_date, color='#E53935', linestyle='--', alpha=0.7)
    ax1.annotate('Release Date', 
                xy=(release_date, ax1.get_ylim()[1]),
                xytext=(10, 10), textcoords='offset points',
                color='#E53935', fontsize=10,
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec='#E53935', alpha=0.8))
    
    # Set the x-ticks to be at each date in the dataset
    ax1.set_xticks(system_pivot.index)
    ax1.set_xticklabels([date.strftime('%Y-%m-%d') for date in system_pivot.index], 
                       rotation=45, fontsize=10, ha='right')
    
    # Add padding between x-axis and the date labels
    ax1.tick_params(axis='x', which='major', pad=10)
    
    ax1.set_title('CAI Framework Download Statistics', fontsize=14, pad=20)
    ax1.set_ylabel('Total Cumulative Downloads', fontsize=14, color='black')
    ax2.set_ylabel('Daily Downloads by System', fontsize=14, color='black')
    ax1.set_xlabel('Date', fontsize=14)
    
    # Set grid and tick parameters
    ax1.grid(True, linestyle='--', alpha=0.7)
    ax1.tick_params(axis='y', colors='black')
    ax2.tick_params(axis='y', colors='black')
    
    # Add legend with combined information
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = [], []
    
    # Add bars to legend in the desired order with correct colors
    for col in desired_order:
        if col in system_pivot.columns:
            # Create a proxy artist with the correct color
            proxy = plt.Rectangle((0, 0), 1, 1, fc=color_map[col], alpha=0.5)
            handles2.append(proxy)
            # Calculate percentage of both system total and overall total
            system_percentage = (system_totals[col] / system_totals.sum()) * 100
            website_percentage = (system_totals[col] / without_mirrors_total) * 100
            labels2.append(f'{col} ({int(system_totals[col]):,} total, {system_percentage:.1f}%)')
    
    # Create legend with updated colors
    ax1.legend(handles1 + handles2, labels1 + labels2, 
              title='Operating Systems',
              bbox_to_anchor=(1.05, 1), loc='upper left',
              fontsize=12, title_fontsize=14)
    
    plt.tight_layout()
    
    # Create a BytesIO buffer for the image
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=300)
    plt.close()
    
    # Encode the image to base64 string
    buf.seek(0)
    image_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    
    # Prepare statistics for the template
    stats = {
        'total_downloads': without_mirrors_total,
        'latest_downloads': daily_downloads.iloc[-1]['downloads'] if not daily_downloads.empty else 0,
        'first_date': daily_downloads['date'].min().strftime('%Y-%m-%d') if not daily_downloads.empty else 'N/A',
        'last_date': daily_downloads['date'].max().strftime('%Y-%m-%d') if not daily_downloads.empty else 'N/A',
        'system_totals': {col: int(system_totals[col]) for col in system_totals.index if col in system_pivot.columns},
        'system_percentages': {col: (system_totals[col] / system_totals.sum()) * 100 
                              for col in system_totals.index if col in system_pivot.columns}
    }
    
    return f'data:image/png;base64,{image_base64}', stats

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
    
    # Generate PyPI plot
    pypi_plot, pypi_stats = create_pypi_plot()
    visualizations['pypi_plot'] = pypi_plot
    visualizations['pypi_stats'] = pypi_stats
    
    return render_template('logs.html', **visualizations)

@app.route('/pypi-stats')
def pypi_stats():
    # Generate PyPI plot
    pypi_plot, stats = create_pypi_plot()
    
    return render_template('pypi_stats.html',
                          pypi_plot=pypi_plot,
                          stats=stats)

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
