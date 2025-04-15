from flask import Flask, render_template
import pandas as pd
import matplotlib
matplotlib.use('Agg')  
import matplotlib.pyplot as plt
import io
import base64
from datetime import datetime
import os
import folium
import requests  

def parse_logs(file_path):
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

                ip_parts = segments[-4:]
                ip_address = '.'.join(ip_parts)

                logs.append([timestamp, size, ip_address, system, username])

            except Exception as e:
                print(f"Error parsing line: {line.strip()} -> {e}")
                continue

    return logs

logs = parse_logs('logs.txt')
if not logs:
    print("No logs were parsed. Please check if the file exists and contains valid log entries.")
    
df = pd.DataFrame(logs, columns=['timestamp', 'size', 'ip_address', 'system', 'username'])
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Obtain lat/lon desde IP
def get_location(ip):
    if ip in ("127.0.0.1", "localhost"):
        return 42.85, -2.67  # Vitoria

    # API 1: ip-api.com
    try:
        print("Trying ip-api.com...")
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        data = response.json()
        if response.status_code == 200 and data.get("status") == "success":
            return data["lat"], data["lon"]
        else:
            print(f"ip-api.com error: {data.get('message', f'Status code {response.status_code}')}")
    except Exception as e:
        print(f"ip-api.com exception: {e}")

    # API 2: ipinfo.io
    try:
        print("Trying ipinfo.io...")
        response = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5)
        data = response.json()
        if response.status_code == 200 and "loc" in data:
            lat, lon = map(float, data["loc"].split(","))
            return lat, lon
        else:
            print(f"ipinfo.io error: 'loc' not found or status code {response.status_code}")
    except Exception as e:
        print(f"ipinfo.io exception: {e}")

    # API 3: ipwho.is
    try:
        print("Trying ipwho.is...")
        response = requests.get(f"https://ipwho.is/{ip}", timeout=5)
        data = response.json()
        if response.status_code == 200 and data.get("success") is True:
            return data["latitude"], data["longitude"]
        else:
            print(f"ipwho.is error: {data.get('message', f'Status code {response.status_code}')}")
    except Exception as e:
        print(f"ipwho.is exception: {e}")

    # Fallback
    print("All APIs failed. Returning default coordinates.")
    return 42.85, -2.67

m = folium.Map(location=[40, -3], zoom_start=4)

for _, row in df.iterrows():
    location = get_location(row['ip_address'])
    folium.Marker(
        location,
        popup=f"{row['username']} ({row['ip_address']})\n{row['timestamp']}",
        tooltip=row['username'],
    ).add_to(m)

m.save("mapa_ips2.html")