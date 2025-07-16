import subprocess
from pathlib import Path
import glob
import re

SENSOR_OUTPUT_DIR = Path('/mnt/tank_1/docker/data/coolercontrol/sensors')

def get_devices():
    return [Path(p).name for p in glob.glob('/dev/sd?')]

def is_spindown(dev):
    try:
        result = subprocess.run(['smartctl', '-i', f'/dev/{dev}'], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if 'Power mode' in line:
                if 'standby' in line.lower():
                    return True
        return False
    except subprocess.CalledProcessError:
        print(f"Error checking spindown status for {dev}")
        return False

def read_temperature(dev):
    try:
        result = subprocess.run(['smartctl', '-A', f'/dev/{dev}'], capture_output=True, text=True, check=True)
        temps = []
        print(f"Reading temperatures for {dev}:")
        for line in result.stdout.splitlines():
            if 'Temperature_Celsius' in line or 'Airflow_Temperature_Cel' in line:
                print(f"  Found line: {line}")
                # Suche die letzte Zahl vor Klammer oder Zeilenende
                match = re.search(r'(\d+)(?=\s*(?:\(|$))', line)
                if match:
                    temp_val = int(match.group(1))
                    temps.append(temp_val)
                    print(f"  Parsed temperature: {temp_val}")
        if temps:
            temp_value = min(temps)
            print(f"  Temperatures found: {temps}, using {temp_value}")
            return temp_value
        else:
            print(f"  No temperature found for {dev}")
            return None
    except subprocess.CalledProcessError:
        print(f"Error reading temperature for {dev}")
        return None


def write_temperature(dev, temp_celsius):
    path = SENSOR_OUTPUT_DIR / dev
    if temp_celsius is None or temp_celsius < 0 or temp_celsius > 100:
        print(f"{dev}: Temperature {temp_celsius} invalid or not found, writing fallback value 0")
        path.write_text('0')  # 0 millidegree Celsius = unknown
    else:
        print(f"{dev}: Writing temperature {temp_celsius * 1000} millidegree Celsius")
        path.write_text(str(temp_celsius * 1000))

def main():
    devices = get_devices()
    for dev in devices:
        if is_spindown(dev):
            print(f"{dev}: Spindown detected, writing empty file")
            (SENSOR_OUTPUT_DIR / dev).write_text('')
        else:
            temp = read_temperature(dev)
            print(f"{dev}: Temperature read as {temp}")
            write_temperature(dev, temp)
            print(f"{dev}: Wrote temperature file")

if __name__ == '__main__':
    main()
