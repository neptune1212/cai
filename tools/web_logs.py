from flask import Flask, render_template
import pandas as pd
import matplotlib.pyplot as plt
import io
import base64
from datetime import datetime
import os

app = Flask(__name__)

def parse_logs(file_path):
    logs = []
    with open(file_path, 'r') as file:
        for line in file:
            try:
                # Split the line into timestamp, size, and filename
                parts = line.strip().split(None, 3)
                if len(parts) != 4:
                    print(f"Skipping line due to incorrect parts: {line.strip()}")
                    continue
                
                timestamp = parts[0] + ' ' + parts[1]
                size = parts[2]
                filename = parts[3]
                
                # Extract UUID and the rest
                filename_parts = filename.split('cai_')
                if len(filename_parts) != 2:
                    print(f"Skipping line due to incorrect filename format: {filename}")
                    continue
                
                # Parse the components after cai_
                components = filename_parts[1].split('_')
                if len(components) < 7:
                    print(f"Skipping line due to insufficient components: {components}")
                    continue
                
                # Components: [date, time, username, system, version, ip]
                username = components[2]  # root
                system = components[3].lower()  # linux
                version = '_'.join(components[4:-1])  # Join all version components
                
                # Process system and version to correctly identify Windows systems
                if 'microsoft' in system or 'microsoft' in version.lower() or 'wsl' in version.lower():
                    system = 'windows'
                
                # Get IP from the last component (remove .jsonl)
                ip = components[-1].replace('.jsonl', '')
                
                logs.append([timestamp, size, ip, system, username])
                print(f"Successfully parsed: {[timestamp, size, ip, system, username]}")
            
            except Exception as e:
                print(f"Error parsing line: {line.strip()}")
                print(f"Error details: {str(e)}")
                continue
    
    if not logs:
        print("No logs were successfully parsed!")
    else:
        print(f"Successfully parsed {len(logs)} log entries")
    
    return logs

def get_ip_location(ip):
    try:
        response = DbIpCity.get(ip, api_key='free')
        return response.latitude, response.longitude
    except:
        return None, None

def create_plots(logs):
    if not logs:
        return None, None, None, None
        
    df = pd.DataFrame(logs, columns=['timestamp', 'size', 'ip_address', 'system', 'username'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    plots = {}
    
    # Time series plot
    plt.figure(figsize=(12, 6))
    df.set_index('timestamp').resample('D').size().plot(kind='bar')
    plt.title('Number of Logs by Day')
    plt.xlabel('Date')
    plt.ylabel('Number of Logs')
    plt.xticks(rotation=45)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plots['time_series'] = base64.b64encode(buf.getvalue()).decode()
    plt.close()

    # System distribution
    plt.figure(figsize=(10, 6))
    system_map = {
        'linux': 'Linux', 
        'darwin': 'Darwin', 
        'windows': 'Windows',
        'microsoft': 'Windows',  # Handle legacy naming
        'wsl': 'Windows'        # Handle WSL explicitly
    }
    df['system_grouped'] = df['system'].map(system_map).fillna('Other')
    system_counts = df['system_grouped'].value_counts()
    system_counts.plot(kind='bar')
    plt.title('Total Number of Logs per System')
    plt.xlabel('System')
    plt.ylabel('Number of Logs')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plots['systems'] = base64.b64encode(buf.getvalue()).decode()
    plt.close()

    # User activity
    plt.figure(figsize=(12, 6))
    user_counts = df['username'].value_counts().head(10)
    user_counts.plot(kind='bar')
    plt.title('Top 10 Most Active Users')
    plt.xlabel('Username')
    plt.ylabel('Number of Logs')
    plt.xticks(rotation=45)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plots['users'] = base64.b64encode(buf.getvalue()).decode()
    plt.close()

    # Create map
    m = folium.Map(location=[0, 0], zoom_start=2)
    
    # Add markers for each unique IP
    for ip in df['ip_address'].unique():
        lat, lon = get_ip_location(ip)
        if lat and lon:
            folium.Marker(
                [lat, lon],
                popup=f'IP: {ip}<br>Count: {len(df[df["ip_address"] == ip])}',
            ).add_to(m)
    
    plots['map'] = m._repr_html_()
    
    return plots

def create_plot_base64(plt_func):
    plt.figure(figsize=(12, 6))
    plt_func()
    plt.tight_layout()
    
    # Create a BytesIO buffer for the image
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close()
    
    # Encode the image to base64 string
    buf.seek(0)
    image_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return f'data:image/png;base64,{image_base64}'

def plot_logs_by_day(df):
    daily_counts = df.set_index('timestamp').resample('D').size()
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

def plot_logs_by_system(df):
    system_map = {'linux': 'Linux', 'darwin': 'Darwin', 'microsoft': 'Windows'}
    df['system_grouped'] = df['system'].map(system_map)
    system_counts = df['system_grouped'].value_counts()
    system_counts.plot(kind='bar')
    plt.title('Total Number of Logs per System')
    plt.xlabel('System')
    plt.ylabel('Number of Logs')

def plot_active_users(df):
    user_counts = df['username'].value_counts().head(20)
    user_counts.plot(kind='bar')
    plt.title('Top 10 Most Active Users')
    plt.xlabel('Username')
    plt.ylabel('Number of Logs')
    plt.xticks(rotation=45)

@app.route('/')
def index():
    # Parse logs
    logs = parse_logs('/tmp/logs.txt')
    if not logs:
        return "No logs were parsed. Please check if the file exists and contains valid log entries."
    
    df = pd.DataFrame(logs, columns=['timestamp', 'size', 'ip_address', 'system', 'username'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Generate plots
    plt.style.use('default')  # Use default style instead of seaborn
    logs_by_day = create_plot_base64(lambda: plot_logs_by_day(df))
    logs_by_system = create_plot_base64(lambda: plot_logs_by_system(df))
    active_users = create_plot_base64(lambda: plot_active_users(df))
    
    return render_template('logs.html',
                         logs_by_day=logs_by_day,
                         logs_by_system=logs_by_system,
                         active_users=active_users)

if __name__ == '__main__':
    # Ensure the log file exists
    if not os.path.exists('/tmp/logs.txt'):
        print("Error: /tmp/logs.txt not found!")
        exit(1)
    
    print("Starting web server on http://localhost:5001")
    app.run(host='0.0.0.0', port=5001, debug=True) 