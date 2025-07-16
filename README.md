# drive-temp-export

This Python script reads disk temperatures using `smartctl` and exports them as millidegree Celsius values to individual files. It handles disks in spindown mode and writes fallback values when temperature is not available.

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

## Usage

Run the script with Python:

```bash
python drive-temp-export.py
```

## Contact

Feedback or suggestions?  
Visit: [https://github.com/Gittegatt/EtherShell](https://github.com/Gittegatt/EtherShell)

---

## Disclaimer

**Use at your own risk. No warranty provided.**

---

## License

Apache License  
Version 2.0
