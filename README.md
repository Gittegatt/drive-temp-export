![Linux](https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black)
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
[![Ko-Fi](https://img.shields.io/badge/Ko--fi-F16061?style=for-the-badge&logo=ko-fi&logoColor=white)](https://ko-fi.com/gittegatt)

# drive-temp-export

This Python script reads disk temperatures using `smartctl` and exports them as millidegree Celsius values to individual files on Linux based systems. It handles disks in spindown mode, let them sleep and writes fallback values when temperature is not available.

## Background

This project is developed to work alongside the [coolercontrol](https://gitlab.com/coolercontrol/coolercontrol) Docker container running on TrueNAS Scale.  
It is designed to read disk temperatures and export them as files, which are then used to control devices such as the NZXT RGB & Fan Controller - AC-CRFR0-B1-6 for automated fan speed adjustments based on disk temps.

## Features

- Detects all `/dev/sd?` devices
- Checks if disk is in spindown (standby) mode
- Reads temperature attributes from `smartctl`
- Writes temperature values (in millidegree Celsius) to output directory
- Writes `0` if temperature is not found or invalid
- Writes empty file if disk is in spindown mode

## Prerequisites

- Python 3.x
- `smartctl` installed and accessible in PATH (part of smartmontools)
- Proper permissions to access `/dev/sd?` devices and write to output directory

## Configuration

Set the `SENSOR_OUTPUT_DIR` path in the script to the directory where temperature files will be written:

```python
SENSOR_OUTPUT_DIR = Path('/path/to/sensor/output/path/directory')
```

Make sure the directory exists and the script has write permissions.

## Usage of the script

Run the script with Python:

```bash
python drive-temp-export.py
```

## Usage in docker and CoolerControl WebUI
- mount the /path/to/sensor/output/path/directory and bind it as volume into you docker container
    e.g. /mnt/tank_1/docker/data/coolercontrol/sensors:/sensors:ro
- create a new custom sensor and use file like /sensors/sda for sda temperature

## Usage in Truenas Scale as Cron Job
- navigate to Advanced Settings  > Cron Jobs and create a new one with custom schedule * * * * *  (Every minute)

## Contact

Feedback or suggestions?  
Visit: [https://github.com/Gittegatt/drive-temp-export](https://github.com/Gittegatt/drive-temp-export)

---

## Disclaimer

**Use at your own risk. No warranty provided.**

---

## License

Apache License  
Version 2.0
