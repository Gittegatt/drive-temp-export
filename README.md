# drive-temp-export

`drive-temp-export` is a small Linux temperature exporter for HDDs, SATA/SAS SSDs, and NVMe drives.

It discovers physical drives dynamically, reads temperatures with `smartctl`, and exports CoolerControl-compatible millidegree Celsius values to individual files. For rotational HDDs, the SMART query is standby-aware so a drive that is already sleeping is not intentionally woken just to obtain a temperature.

The current version is designed as a long-running process. It continuously refreshes the device inventory and temperature files at a configurable interval.

## Background

The project was developed for TrueNAS SCALE systems running [CoolerControl](https://gitlab.com/coolercontrol/coolercontrol) in Docker.

The exported files can be mounted read-only into the CoolerControl container and added as custom sensors. This allows disk temperatures, group averages, or the hottest disk in a group to be used for fan-control profiles without requiring CoolerControl itself to query SMART data.

The exporter is also useful independently of CoolerControl whenever simple file-based temperature values are convenient.

## Why this exporter exists

Native Linux `drivetemp` / hwmon sensors can work well, but behavior depends on the drive, controller, kernel, and monitoring software.

This exporter provides a controlled alternative:

- HDD temperature and standby detection use the same `smartctl -n standby,3 -A` call.
- A sleeping HDD is represented as `0` millidegree Celsius instead of being deliberately woken for a SMART temperature read.
- Drive identification is obtained from sysfs, udev, and `/dev/disk/by-id` metadata, not by performing an extra SMART probe.
- Sensor filenames are based on stable drive identifiers whenever possible instead of volatile `/dev/sdX` names.
- HDD, SSD, and NVMe sensors are separated into groups.
- Per-group average and maximum temperature files are generated automatically.
- A human-readable `status` file shows the current inventory and state.

## Features

- Dynamic discovery of physical `sdX` devices and NVMe namespaces
- HDD / SSD / NVMe classification
- Standby-aware HDD temperature polling
- SATA, SAS/SCSI, and NVMe temperature parsing
- Stable sensor names based on serial number, WWN, or persistent by-id aliases
- Automatic fallback to an explicitly marked unstable device-name ID when no stable identifier exists
- Millidegree Celsius output for CoolerControl custom sensors
- Separate `hdd/`, `ssd/`, and `nvme/` output directories
- Per-group `average` and `max` sensors
- Human-readable status output
- Atomic file replacement to avoid partially written sensor values
- Dynamic addition and removal of drives while the exporter is running
- Configurable polling interval
- Configurable output path and command paths through environment variables
- SMART and udev command timeouts

## How it works

### 1. Dynamic device discovery

The exporter scans `/sys/block` and includes:

```text
sd[a-z]+
nvme<number>n<number>
```

Only devices that also exist under `/dev` are added.

Identification data is collected from udev, sysfs, and `/dev/disk/by-id`. SMART is not used for device identification.

### 2. HDD / SSD / NVMe classification

NVMe namespaces are placed in the `nvme` group.

For `sdX` devices, the exporter reads:

```text
/sys/block/<device>/queue/rotational
```

A value of `1` is treated as HDD. Other `sdX` devices are treated as SSD.

### 3. Stable sensor names

The exporter prefers a stable serial number. If no serial is available, it falls back to WWN and then to a persistent `/dev/disk/by-id` alias.

Sensor names use this format:

```text
TYPE_SIZE_SERIAL_OR_ID
```

Examples:

```text
HDD_10TB_SERIAL123
SSD_400GB_SERIAL456
NVME_500GB_SERIAL789
```

If no stable identifier can be found, the exporter falls back to:

```text
UNSTABLE_sdX
```

and prints a warning because that filename can change after a reboot.

### 4. HDD standby-safe SMART polling

For every rotational HDD, the exporter performs exactly one SMART command per polling interval:

```bash
smartctl -n standby,3 -A /dev/sdX
```

The same call is used for both standby detection and temperature retrieval.

If the HDD is already in standby or sleep, the exporter records the drive as `standby` and writes:

```text
0
```

to the corresponding sensor file.

The exporter does not run a second SMART status command before reading the temperature.

### 5. SSD and NVMe polling

For SSD and NVMe devices, normal SMART attribute data is requested with:

```bash
smartctl -A /dev/<device>
```

HDD standby behavior is not relevant to these non-rotational devices.

### 6. Temperature parsing

The current parser supports the following common temperature formats:

- ATA/SATA: `Temperature_Celsius`
- ATA/SATA: `Airflow_Temperature_Cel`
- SAS/SCSI: `Current Drive Temperature`
- NVMe: primary `Temperature:` value

Valid temperatures are exported as millidegree Celsius values.

Example:

```text
35.0 C -> 35000
27.0 C -> 27000
```

### 7. Error behavior

The value `0` is reserved for a drive that is currently treated as sleeping or for a sensor that has not yet obtained a valid temperature.

If a later SMART query fails or returns no valid temperature, the exporter marks the drive state as `error` but intentionally retains the previous valid temperature value instead of overwriting it with a false `0`.

This also means a previously valid value can continue to contribute to the group summary while the drive is in an error state. Check the `status` file when troubleshooting.

## Output layout

The default output directory is:

```text
/run/system-metrics/output/disk-temp
```

The exporter creates the required directories automatically.

Example layout:

```text
/run/system-metrics/output/disk-temp/
|-- hdd/
|   |-- HDD_10TB_SERIAL123
|   |-- HDD_8TB_SERIAL456
|   |-- HDD_average
|   `-- HDD_max
|-- ssd/
|   |-- SSD_400GB_SERIAL789
|   |-- SSD_average
|   `-- SSD_max
|-- nvme/
|   |-- NVME_500GB_SERIALABC
|   |-- NVME_average
|   `-- NVME_max
`-- status
```

Sleeping HDDs are excluded from the HDD average and maximum because their internal temperature value is represented as unavailable and their exported individual sensor file contains `0`.

If all drives in a group are unavailable or sleeping, that group's `average` and `max` files contain `0`.

## Status file

The exporter also writes:

```text
/run/system-metrics/output/disk-temp/status
```

It contains a human-readable overview similar to:

```text
STATE     TYPE  SIZE    SERIAL/ID                     TEMP      DEVICE       MODEL
------------------------------------------------------------------------------------------
ACTIVE    HDD   10TB    SERIAL123                     31.0 C    /dev/sda     Example HDD
STANDBY   HDD   8TB     SERIAL456                     --        /dev/sdb     Example HDD
ACTIVE    SSD   400GB   SERIAL789                     35.0 C    /dev/sdc     Example SSD
```

The `status` file is intended for diagnostics and does not need to be added as a CoolerControl sensor.

## Compatibility and tested environment

The current version has been used and tested on:

| Component | Tested version |
| --- | --- |
| TrueNAS SCALE | `25.10.7` |
| Kernel | `6.12.105-production+truenas` |
| smartmontools / smartctl | `7.4` |
| CoolerControlD | `2.2.2` |

The exporter itself is Linux-specific because it relies on Linux sysfs paths such as `/sys/block`.

## Verified spindown behavior

During TrueNAS 25.10.7 testing, multiple SATA and SAS HDDs were allowed to enter standby while the exporter continued running at a 5 second polling interval.

For the tested HDDs, the exporter reported:

```text
STANDBY -> 0.0 C
```

without waking the sleeping drives. The exporter used one `smartctl -n standby,3 -A` call per HDD per interval.

This behavior is the reason the HDD query intentionally combines standby detection and temperature retrieval in one command.

As always, drive firmware and controller behavior can differ. Verify standby behavior on your own hardware before relying on it.

## Native `drivetemp` / hwmon findings

Recent testing also compared this exporter with native Linux `drivetemp` / hwmon temperature sensors.

On the tested TrueNAS SCALE 25.10.7 system:

- The `drivetemp` kernel module was loaded and native hwmon temperature sensors were available for the attached drives.
- CoolerControl 2.2.2 displayed correct native drive temperatures.
- When native drive sensors were enabled, CoolerControl repeatedly logged:

```text
Error getting drive power state: Not a Block Device File
```

- The warning affected CoolerControl's additional drive power-state handling; temperature values themselves were still available.
- A sleeping SAS HDD was verified as `STANDBY BY COMMAND`, its native `temp1_input` file was read 10 times at one second intervals, and the drive remained in `STANDBY BY COMMAND` afterwards.
- Those 10 native reads all returned a stable `27000`, corresponding to 27 C.
- In an earlier test, loading/probing the `drivetemp` module with `modprobe drivetemp` caused some already sleeping HDDs to spin up. This is different from reading an already initialized hwmon sensor.

These findings show that native hwmon polling can be standby-safe on at least some drive/controller combinations, but they are not a guarantee for every drive model or system.

If native CoolerControl sensors are proven safe on your hardware, this exporter is not strictly required just to obtain temperatures. It can still be useful for predictable SMART standby handling, stable sensor filenames, group `average`/`max` sensors, a status file, and decoupling CoolerControl from direct drive monitoring.

Avoid repeatedly unloading and reloading `drivetemp` merely to test temperatures if your goal is to keep sleeping drives asleep.

## Requirements

- Linux
- Python 3
- `smartctl` from smartmontools
- Access to the required `/dev/sdX` and `/dev/nvmeXnY` devices
- Read access to `/sys/block`, `/sys/class/nvme`, and `/dev/disk/by-id` where available
- Write access to the configured sensor output directory
- `udevadm` is recommended for richer metadata, but the exporter also has sysfs and by-id fallbacks

Running the exporter with sufficient privileges is required for SMART access. On TrueNAS SCALE, running it from a root-context Post Init task is the simplest setup.

## Configuration

The script can be configured through command-line arguments and environment variables.

### Polling interval

Default:

```text
5 seconds
```

Command-line override:

```bash
python3 drive-temp-export.py -i 10
```

or:

```bash
python3 drive-temp-export.py --interval 10
```

Environment override:

```bash
UPDATE_INTERVAL=10 python3 drive-temp-export.py
```

The command-line `-i/--interval` value takes precedence over `UPDATE_INTERVAL`.

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `UPDATE_INTERVAL` | `5` | Polling interval in seconds when `-i` is not supplied |
| `SMARTCTL` | `/sbin/smartctl` | Path to `smartctl` |
| `UDEVADM` | auto-detected `udevadm` | Path or command used for udev metadata |
| `SENSOR_OUTPUT_DIR` | `/run/system-metrics/output/disk-temp` | Root directory for exported sensor files |
| `SMARTCTL_TIMEOUT` | `15` | SMART subprocess timeout in seconds |
| `UDEVADM_TIMEOUT` | `3` | udevadm subprocess timeout in seconds |

Example with a custom output directory:

```bash
SENSOR_OUTPUT_DIR=/mnt/pool/system-metrics/disk-temp python3 drive-temp-export.py -i 5
```

## Usage

Start the exporter in the foreground:

```bash
python3 drive-temp-export.py
```

Run with an explicit 5 second interval:

```bash
python3 drive-temp-export.py -i 5
```

The process stays running until it is terminated, for example with `Ctrl+C`.

### Important: do not use the old one-minute Cron setup

Older versions of this project's README suggested starting the script from TrueNAS Cron every minute.

That is no longer correct for the current script.

The current exporter contains its own continuous loop and polling interval. Starting it repeatedly from Cron would create multiple long-running exporter processes.

Use a single long-running process instead, for example a TrueNAS Post Init command, a service, or a detached `tmux` session.

## TrueNAS SCALE Post Init example

A tested approach is to launch the exporter in a detached `tmux` session during Post Init.

First verify the Python path on your system:

```bash
command -v python3
```

Then adapt the following command to your persistent script location:

```bash
tmux has-session -t drive-temp-export 2>/dev/null || tmux new-session -d -s drive-temp-export "/usr/bin/python3 -u /mnt/<pool>/scripts/system-metrics/drive-temp-export.py -i 5"
```

If `command -v python3` returns a different path, use that path instead of `/usr/bin/python3`.

In TrueNAS SCALE, configure it under:

```text
System > Advanced Settings > Init/Shutdown Scripts
```

Recommended settings:

| Setting | Value |
| --- | --- |
| Type | `Command` |
| When | `Post Init` |
| Enabled | Yes |

The default output directory is under `/run`, which is temporary and recreated after a reboot. This is expected. The exporter recreates its output tree automatically when it starts.

## Docker and CoolerControl setup

The exporter normally runs on the TrueNAS host. Mount its output directory read-only into the CoolerControl container.

Example Docker bind mount:

```yaml
volumes:
  - /run/system-metrics/output/disk-temp:/sensors:ro
```

Then add CoolerControl custom file sensors using paths such as:

```text
/sensors/hdd/HDD_max
/sensors/hdd/HDD_average
/sensors/hdd/HDD_10TB_SERIAL123
/sensors/ssd/SSD_max
/sensors/nvme/NVME_max
```

The individual sensor names are based on stable drive IDs, so they are not tied to a particular `/dev/sdX` assignment after reboot.

For a disk-fan profile, `HDD_max` is often the most useful aggregate sensor because it follows the hottest currently active HDD. Sleeping HDDs do not contribute a false temperature to the calculation.

## Interpreting sensor values

| File value | Meaning |
| ---: | --- |
| `35000` | 35 C |
| `27500` | 27.5 C |
| `0` | Sleeping/unavailable drive or no valid initial value |

For the exact drive state, use the `status` file rather than interpreting `0` alone.

## Troubleshooting

### A sleeping HDD wakes during monitoring

First verify the exact command being used. Rotational HDDs should be queried with:

```bash
smartctl -n standby,3 -A /dev/sdX
```

Do not replace this with a normal unconditional SMART read if preserving standby is important.

Also check other services that can access the disks. A drive can be woken by filesystem access, media-library scans, SMART tasks, scrubs, replication, applications, or other monitoring software even when this exporter itself is standby-safe.

### Native CoolerControl drive sensors show power-state warnings

With CoolerControlD 2.2.2, the tested system showed repeated:

```text
Error getting drive power state: Not a Block Device File
```

while native hwmon temperatures still displayed correctly.

This warning is separate from the file sensors exported by this project. Using exported custom sensors keeps CoolerControl from needing those native drive sensors for fan control.

### Sensor name contains `UNSTABLE_`

The exporter could not obtain a serial number, WWN, or suitable persistent by-id alias for that device.

The sensor will still work, but its filename may change if the Linux device name changes after reboot.

### A SMART query fails

The exporter marks the device as `error` in the status file and retains the last valid temperature instead of immediately replacing it with `0`.

Check the status output and run `smartctl` manually for the affected drive when diagnosing the problem.

## Related project

For SATA/SAS HDD spindown timing on TrueNAS SCALE, see:

- [Gittegatt/truenas-sata-sas-spindown-timer](https://github.com/Gittegatt/truenas-sata-sas-spindown-timer)

The projects solve different parts of the same problem:

- `drive-temp-export` provides standby-aware temperature sensors.
- `truenas-sata-sas-spindown-timer` decides when idle rotational disks should be sent to standby.

Neither project can prevent another process from waking a disk that it accesses.

## Disclaimer

**Use at your own risk. No warranty provided.**

Drive standby behavior varies by hardware, firmware, controller, kernel, and workload. Test the behavior on your own system before relying on it for unattended operation.

## License

MIT License

Copyright (c) 2026 Gittegatt

## AI Notice

AI-assisted coding tools were used during the development of this project.

AI or machine-learning training, fine-tuning, dataset creation, and model
improvement are subject to the same PolyForm Noncommercial terms as other
uses of this source code. Commercial purposes outside the license's permitted
purposes require separate authorization. This notice adds no restrictions to
third-party material and does not override statutory exceptions.

## ☕ Support the project

If you enjoy the project and would like to support its development, a small contribution is always appreciated.

[Support me on Ko-fi](https://ko-fi.com/gittegatt)

[Support me on buymeacoffee](https://buymeacoffee.com/gittegatt)

## Contact

Feedback or suggestions?

Visit: [https://github.com/Gittegatt/drive-temp-export](https://github.com/Gittegatt/drive-temp-export)
