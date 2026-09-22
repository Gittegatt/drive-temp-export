#!/usr/bin/env python3
#
# drive-temp-export.py v1.2.0
#
# Dynamically detects HDDs, SSDs, and NVMe drives and exports their temperatures
# as millidegree Celsius values for monitoring and fan-control software. HDD standby
# is respected with smartctl -n standby,3 so sleeping disks are not intentionally
# woken. The script also creates per-device sensor files, group average/max values,
# and a status file with the current device state and temperature.
#

import argparse
import os
import re
import shutil
import subprocess
import time
from pathlib import Path


# ------------------------------------------------------------
# Arguments
# ------------------------------------------------------------

def positive_int(value):
    value = int(value)
    if value <= 0:
        raise argparse.ArgumentTypeError("interval must be greater than 0")
    return value


parser = argparse.ArgumentParser(
    description=(
        "Export drive temperatures dynamically. HDD standby is respected "
        "with smartctl -n standby so sleeping disks are not intentionally woken."
    ),
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)

parser.add_argument(
    "-i",
    "--interval",
    type=positive_int,
    default=None,
    help="SMART/temperature polling interval in seconds",
)

args = parser.parse_args()


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

UPDATE_INTERVAL = (
    args.interval
    if args.interval is not None
    else int(os.getenv("UPDATE_INTERVAL", "5"))
)

SMARTCTL = os.getenv("SMARTCTL", "/sbin/smartctl")
UDEVADM = os.getenv("UDEVADM", shutil.which("udevadm") or "udevadm")

SENSOR_OUTPUT_DIR = Path(
    os.getenv(
        "SENSOR_OUTPUT_DIR",
        "/run/system-metrics/output/disk-temp",
    )
)

SMARTCTL_TIMEOUT = int(os.getenv("SMARTCTL_TIMEOUT", "15"))
UDEVADM_TIMEOUT = int(os.getenv("UDEVADM_TIMEOUT", "3"))

GROUPS = ("hdd", "ssd", "nvme")
GROUP_PREFIX = {
    "hdd": "HDD",
    "ssd": "SSD",
    "nvme": "NVME",
}


# ------------------------------------------------------------
# General helper functions
# ------------------------------------------------------------

def timestamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_text(path):
    try:
        value = Path(path).read_text(errors="replace").strip()
        return value or None
    except Exception:
        return None


def sanitize_component(value):
    if not value:
        return None

    value = value.strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    value = value.strip("._-")
    return value or None


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")

    try:
        tmp_path.write_text(f"{value}\n")
        os.replace(tmp_path, path)
        return True
    except Exception as exc:
        print(
            f"[{timestamp()}] ERROR writing {path}: {exc}",
            flush=True,
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def format_capacity(size_bytes):
    """Human-readable decimal capacity for stable, readable sensor names."""
    if size_bytes >= 1_000_000_000_000:
        value = size_bytes / 1_000_000_000_000
        if abs(value - round(value)) < 0.05:
            return f"{round(value):d}TB"
        return f"{value:.1f}TB".replace(".0TB", "TB")

    if size_bytes >= 1_000_000_000:
        # Display manufacturer capacities in the GB range as whole GB values.
        # This maps, for example, 240.1 GB -> 240GB and 400.1 GB -> 400GB
        # as well as 500.1 GB -> 500GB.
        value = size_bytes / 1_000_000_000
        return f"{round(value):d}GB"

    if size_bytes >= 1_000_000:
        value = size_bytes / 1_000_000
        return f"{round(value):d}MB"

    return f"{size_bytes}B"


# ------------------------------------------------------------
# Dynamic drive detection - sysfs/udev metadata only
# ------------------------------------------------------------

def list_block_devices():
    """
    Returns only physical sdX devices and NVMe namespaces.

    /sys/block provides kernel metadata and does not intentionally
    access HDD user data.
    """
    result = []
    sys_block = Path("/sys/block")

    try:
        for entry in sys_block.iterdir():
            name = entry.name

            if re.fullmatch(r"sd[a-z]+", name):
                pass
            elif re.fullmatch(r"nvme\d+n\d+", name):
                pass
            else:
                continue

            if Path(f"/dev/{name}").exists():
                result.append(name)

    except Exception as exc:
        print(
            f"[{timestamp()}] ERROR reading /sys/block: {exc}",
            flush=True,
        )

    return sorted(result)


def get_udev_properties(dev):
    """
    Queries only existing udev/sysfs metadata.
    No smartctl call or drive probing command is used.
    """
    try:
        result = subprocess.run(
            [
                UDEVADM,
                "info",
                "--query=property",
                f"--name=/dev/{dev}",
            ],
            capture_output=True,
            text=True,
            timeout=UDEVADM_TIMEOUT,
        )
    except Exception:
        return {}

    if result.returncode != 0:
        return {}

    props = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()

    return props


def by_id_aliases(dev):
    """Reads only /dev/disk/by-id symlinks; no device I/O."""
    root = Path("/dev/disk/by-id")
    aliases = []

    if not root.exists():
        return aliases

    try:
        for entry in root.iterdir():
            if "-part" in entry.name:
                continue

            try:
                target = os.path.realpath(entry)
            except Exception:
                continue

            if target == f"/dev/{dev}":
                aliases.append(entry.name)
    except Exception:
        pass

    return sorted(aliases)


def get_size_bytes(dev):
    sectors = read_text(f"/sys/block/{dev}/size")
    if sectors is None:
        return 0

    try:
        # /sys/block/<dev>/size is expressed in 512-byte sectors.
        return int(sectors) * 512
    except ValueError:
        return 0


def get_rotational(dev):
    value = read_text(f"/sys/block/{dev}/queue/rotational")
    return value == "1"


def nvme_controller_name(dev):
    match = re.fullmatch(r"(nvme\d+)n\d+", dev)
    return match.group(1) if match else None


def get_sysfs_model(dev):
    if dev.startswith("nvme"):
        controller = nvme_controller_name(dev)
        if controller:
            return read_text(f"/sys/class/nvme/{controller}/model")

    return read_text(f"/sys/block/{dev}/device/model")


def get_sysfs_serial(dev):
    if dev.startswith("nvme"):
        controller = nvme_controller_name(dev)
        if controller:
            value = read_text(f"/sys/class/nvme/{controller}/serial")
            if value:
                return value

    return read_text(f"/sys/block/{dev}/device/serial")


def get_sysfs_wwn(dev):
    # Depending on the driver, the file is named wwid or the WWID is only available through udev.
    return read_text(f"/sys/block/{dev}/device/wwid")


def extract_fallback_id(dev, aliases):
    """
    Fallback when neither a serial number nor a WWN is available.
    Prefers a persistent by-id alias.
    """
    for prefix in ("wwn-", "nvme-eui.", "nvme-uuid."):
        for alias in aliases:
            if alias.startswith(prefix):
                return alias

    for prefix in ("ata-", "scsi-", "nvme-"):
        for alias in aliases:
            if alias.startswith(prefix):
                return alias

    return f"UNSTABLE_{dev}"


def build_device_info(dev):
    props = get_udev_properties(dev)
    aliases = by_id_aliases(dev)

    size_bytes = get_size_bytes(dev)
    size_label = format_capacity(size_bytes)

    if dev.startswith("nvme"):
        group = "nvme"
    elif get_rotational(dev):
        group = "hdd"
    else:
        group = "ssd"

    model = (
        props.get("ID_MODEL")
        or props.get("ID_MODEL_FROM_DATABASE")
        or get_sysfs_model(dev)
        or "unknown-model"
    )

    serial = (
        props.get("ID_SCSI_SERIAL")
        or props.get("ID_SERIAL_SHORT")
        or get_sysfs_serial(dev)
    )

    wwn = (
        props.get("ID_WWN_WITH_EXTENSION")
        or props.get("ID_WWN")
        or get_sysfs_wwn(dev)
    )

    serial_clean = sanitize_component(serial)
    wwn_clean = sanitize_component(wwn)

    stable_id = serial_clean or wwn_clean
    if not stable_id:
        stable_id = sanitize_component(extract_fallback_id(dev, aliases))

    prefix = GROUP_PREFIX[group]
    sensor_name = f"{prefix}_{size_label}_{stable_id}"

    return {
        "dev": dev,
        "device": f"/dev/{dev}",
        "group": group,
        "size_bytes": size_bytes,
        "size_label": size_label,
        "model": model.strip(),
        "serial": serial.strip() if serial else None,
        "wwn": wwn.strip() if wwn else None,
        "stable_id": stable_id,
        "sensor_name": sensor_name,
        "sensor_path": SENSOR_OUTPUT_DIR / group / sensor_name,
        "aliases": aliases,
    }


# ------------------------------------------------------------
# Parse temperature from SMART output
# ------------------------------------------------------------

def parse_temperature(output):
    """
    Supports:
      ATA/SATA: Temperature_Celsius, Airflow_Temperature_Cel
      SAS/SCSI: Current Drive Temperature
      NVMe:     Temperature: xx Celsius

    Integer and decimal values are accepted.
    """
    temperatures = []
    nvme_primary = None

    for line in output.splitlines():
        # NVMe primary/composite temperature.
        match = re.search(
            r"^\s*Temperature\s*:\s*(-?\d+(?:\.\d+)?)\s*(?:Celsius|C)?\b",
            line,
            re.IGNORECASE,
        )
        if match:
            temp = float(match.group(1))
            if 0 < temp < 150:
                nvme_primary = temp
            continue

        # SAS / SCSI
        match = re.search(
            r"Current Drive Temperature\s*:\s*(-?\d+(?:\.\d+)?)",
            line,
            re.IGNORECASE,
        )
        if match:
            temp = float(match.group(1))
            if 0 < temp < 100:
                temperatures.append(temp)
            continue

        # ATA / SATA
        if (
            "Temperature_Celsius" in line
            or "Airflow_Temperature_Cel" in line
        ):
            match = re.search(
                r"\s(-?\d+(?:\.\d+)?)\s*(?:\(|$)",
                line,
            )
            if match:
                temp = float(match.group(1))
                if 0 < temp < 100:
                    temperatures.append(temp)

    if nvme_primary is not None:
        return nvme_primary

    if temperatures:
        # Preserve the behavior of the previous version.
        return min(temperatures)

    return None


# ------------------------------------------------------------
# SMART query
# ------------------------------------------------------------

def query_device(info):
    """
    HDD:
      exactly ONE smartctl call per interval using -n standby,3.
      If the HDD is already in STANDBY/SLEEP, the command exits before
      reading SMART data and exports 0 C.

    SSD/NVMe:
      normal SMART temperature query; HDD spindown is not relevant.
    """
    dev = info["dev"]
    device = info["device"]
    group = info["group"]

    command = [SMARTCTL]

    if group == "hdd":
        command += ["-n", "standby,3"]

    command += ["-A", device]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=SMARTCTL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(
            f"[{timestamp()}] {dev}: SMART timeout",
            flush=True,
        )
        return "error", None
    except Exception as exc:
        print(
            f"[{timestamp()}] {dev}: SMART execution error: {exc}",
            flush=True,
        )
        return "error", None

    output = result.stdout + "\n" + result.stderr

    if group == "hdd":
        standby_text = bool(
            re.search(
                r"\b(?:STANDBY|SLEEP)\b",
                output,
                re.IGNORECASE,
            )
        )

        if result.returncode == 3 or standby_text:
            return "standby", None

    temperature = parse_temperature(result.stdout)

    if temperature is not None:
        return "active", temperature

    print(
        f"[{timestamp()}] {dev}: no valid temperature found "
        f"(smartctl exit={result.returncode})",
        flush=True,
    )
    return "error", None


# ------------------------------------------------------------
# Output
# ------------------------------------------------------------

def prepare_output_tree():
    SENSOR_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for group in GROUPS:
        (SENSOR_OUTPUT_DIR / group).mkdir(parents=True, exist_ok=True)


def write_temperature(info, temp):
    # CoolerControl expects millidegrees Celsius.
    value = 0 if temp is None else round(temp * 1000)
    return atomic_write(info["sensor_path"], value)


def write_group_summary(group, inventory, temperatures):
    valid = []

    for dev, info in inventory.items():
        if info["group"] != group:
            continue

        temp = temperatures.get(dev)
        if temp is not None and 0 < temp < 150:
            valid.append(temp)

    if valid:
        average = round(sum(valid) / len(valid) * 1000)
        maximum = round(max(valid) * 1000)
    else:
        average = 0
        maximum = 0

    prefix = GROUP_PREFIX[group]
    atomic_write(SENSOR_OUTPUT_DIR / group / f"{prefix}_average", average)
    atomic_write(SENSOR_OUTPUT_DIR / group / f"{prefix}_max", maximum)


def write_all_summaries(inventory, temperatures):
    for group in GROUPS:
        write_group_summary(group, inventory, temperatures)


def write_status(inventory, temperatures, states):
    lines = [
        "STATE     TYPE  SIZE    SERIAL/ID                     TEMP      DEVICE       MODEL",
        "------------------------------------------------------------------------------------------",
    ]

    order = {"hdd": 0, "ssd": 1, "nvme": 2}

    for dev, info in sorted(
        inventory.items(),
        key=lambda item: (
            order.get(item[1]["group"], 9),
            -item[1]["size_bytes"],
            item[1]["sensor_name"],
        ),
    ):
        state = states.get(dev, "unknown").upper()
        temp = temperatures.get(dev)
        temp_text = "--" if temp is None else f"{temp:.1f} C"
        serial_or_id = info["serial"] or info["wwn"] or info["stable_id"]

        lines.append(
            f"{state:<9} "
            f"{info['group'].upper():<5} "
            f"{info['size_label']:<7} "
            f"{serial_or_id[:29]:<29} "
            f"{temp_text:<9} "
            f"/dev/{dev:<10} "
            f"{info['model']}"
        )

    atomic_write(SENSOR_OUTPUT_DIR / "status", "\n".join(lines))


def remove_sensor_file(info):
    try:
        info["sensor_path"].unlink(missing_ok=True)
    except Exception as exc:
        print(
            f"[{timestamp()}] ERROR removing {info['sensor_path']}: {exc}",
            flush=True,
        )


# ------------------------------------------------------------
# Inventory management
# ------------------------------------------------------------

def add_device(dev, inventory, temperatures, states):
    info = build_device_info(dev)
    inventory[dev] = info
    temperatures[dev] = None
    states[dev] = "unknown"

    # Create the file immediately; the first SMART poll updates the value.
    write_temperature(info, None)

    serial_or_id = info["serial"] or info["wwn"] or info["stable_id"]

    print(
        f"[{timestamp()}] discovered: "
        f"{dev} -> {info['group'].upper()} "
        f"{info['size_label']} "
        f"{serial_or_id} -> "
        f"{info['group']}/{info['sensor_name']} "
        f"({info['model']})",
        flush=True,
    )

    if info["stable_id"].startswith("UNSTABLE_"):
        print(
            f"[{timestamp()}] WARNING: {dev} has no serial/WWN/by-id; "
            "sensor name is not reboot-stable.",
            flush=True,
        )


def refresh_inventory(inventory, temperatures, states):
    current_devices = set(list_block_devices())
    known_devices = set(inventory.keys())

    for dev in sorted(current_devices - known_devices):
        add_device(dev, inventory, temperatures, states)

    for dev in sorted(known_devices - current_devices):
        info = inventory[dev]

        print(
            f"[{timestamp()}] removed: {dev} -> "
            f"{info['group']}/{info['sensor_name']}",
            flush=True,
        )

        remove_sensor_file(info)
        inventory.pop(dev, None)
        temperatures.pop(dev, None)
        states.pop(dev, None)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    prepare_output_tree()

    print(
        f"[{timestamp()}] drive-temp-export started",
        flush=True,
    )
    print(
        f"SMART/temperature interval: {UPDATE_INTERVAL} s",
        flush=True,
    )
    print(
        "Dynamic inventory: /sys/block + udev/sysfs metadata; "
        "no SMART is used for identification.",
        flush=True,
    )
    print(
        "HDD: one smartctl -n standby,3 -A call per interval; "
        "STANDBY -> 0 C.",
        flush=True,
    )
    print(
        "Outputs: hdd/, ssd/, nvme/ with stable TYPE_SIZE_SERIAL/ID names, "
        "plus TYPE_average/TYPE_max and status.",
        flush=True,
    )
    print(flush=True)

    inventory = {}
    temperatures = {}
    states = {}

    while True:
        refresh_inventory(inventory, temperatures, states)

        for dev in sorted(inventory.keys()):
            info = inventory[dev]
            previous_state = states.get(dev)
            previous_temp = temperatures.get(dev)

            state, temp = query_device(info)

            if state == "standby":
                temperatures[dev] = None
                write_temperature(info, None)

                if previous_state != "standby":
                    print(
                        f"[{timestamp()}] {dev} "
                        f"[{info['sensor_name']}]: STANDBY -> 0.0 C",
                        flush=True,
                    )

                states[dev] = "standby"
                continue

            if state == "active" and temp is not None:
                temperatures[dev] = temp
                write_temperature(info, temp)

                if previous_state != "active" or previous_temp != temp:
                    print(
                        f"[{timestamp()}] {dev} "
                        f"[{info['sensor_name']}]: {temp:.1f} C",
                        flush=True,
                    )

                states[dev] = "active"
                continue

            # On error, intentionally preserve the previous valid value.
            states[dev] = "error"

        write_all_summaries(inventory, temperatures)
        write_status(inventory, temperatures, states)

        time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped by user.", flush=True)