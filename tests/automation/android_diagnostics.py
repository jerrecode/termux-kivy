"""Android test diagnostics, focus verification, screenshots and device-state guards.

All device modifications are opt-in and restored even if a check fails.
Screenshot pixel comparison uses Pillow when present; screenshot dimensions and
PNG validity are checked with the standard library on every supported device.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import struct
import subprocess
import time
from datetime import datetime


GUI_PACKAGE = "com.termux.gui"
FOCUS_RE = re.compile(r"(?:mCurrentFocus|mFocusedApp|topResumedActivity)[^\n]*", re.I)
SIZE_RE = re.compile(r"(?:Physical|Override) size:\s*(\d+)x(\d+)")


def log(message):
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    print(f"[{timestamp}] [ANDROID-DIAGNOSTICS] {message}", flush=True)


def focus_package(dumpsys):
    """Return the top focused package, or None if Android hides the field."""
    lines = FOCUS_RE.findall(dumpsys)
    if not lines:
        return None
    # Prefer mCurrentFocus (window currently receiving touch), then
    # mFocusedApp, then activity manager's resumed Activity.
    lines.sort(key=lambda line: (
        0 if "mCurrentFocus" in line else
        1 if "mFocusedApp" in line else 2
    ))
    for line in lines:
        if "null" in line.lower() and "=" in line and line.split("=", 1)[-1].strip() == "null":
            continue
        matches = re.findall(r"([A-Za-z][\w]*(?:\.[A-Za-z][\w]*)+)/[\w.$]+", line)
        if matches:
            return matches[0]
    return None


def require_foreground(adb_run, adb, serial, *, package=GUI_PACKAGE, timeout=4):
    began = time.monotonic()
    last = None
    while time.monotonic() - began <= timeout:
        output = adb_run(adb, serial, "shell", "dumpsys", "window", timeout=12)
        last = focus_package(output)
        if last == package:
            log(f"FOREGROUND PASS package={last} elapsed={time.monotonic()-began:.3f}s")
            return
        log(f"FOREGROUND WAIT expected={package} observed={last!r}")
        time.sleep(0.25)
    raise AssertionError(f"Expected foreground {package!r}, observed {last!r}; "
                         f"elapsed={time.monotonic()-began:.3f}s")


def package_from_ui_xml(xml):
    import xml.etree.ElementTree as ET
    tree = ET.fromstring(xml)
    matches = {}
    for node in tree.iter("node"):
        package = node.attrib.get("package", "")
        matches[package] = matches.get(package, 0) + 1
    return max(matches, key=matches.get) if matches else None


def png_dimensions(data):
    if (len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n")
            or data[12:16] != b"IHDR"):
        raise ValueError("screencap output is not a valid PNG header")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0 or width > 16384 or height > 16384:
        raise ValueError(f"invalid screenshot dimensions {width}x{height}")
    return width, height


def capture(adb, serial, label, *, output_dir=None):
    command = [adb] + (["-s", serial] if serial else []) + [
        "exec-out", "screencap", "-p"
    ]
    started = time.monotonic()
    process = subprocess.run(command, capture_output=True, timeout=30, check=False)
    if process.returncode:
        raise RuntimeError(f"Android screenshot failed with code={process.returncode}: "
                           f"{process.stderr[:500]!r}")
    data = process.stdout
    size = png_dimensions(data)
    digest = hashlib.sha256(data).hexdigest()
    path = None
    if output_dir is not None:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (label + ".png")
        path.write_bytes(data)
    log(f"SCREENSHOT label={label} dimensions={size} bytes={len(data)} "
        f"sha256={digest} elapsed={time.monotonic()-started:.3f}s "
        f"saved={str(path) if path else 'temporary-memory-only'}")
    return {"label": label, "dimensions": size, "sha256": digest,
            "png": data, "path": path}


def pixels_changed(before, after, region=None):
    """Return measured changed-pixel fraction, or None if Pillow unavailable."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        log("SCREENSHOT PIXELS: Pillow unavailable; only PNG dimensions and "
            "native Android UI geometry/text are asserted. For pixel analysis "
            "install Pillow in the Termux environment.")
        return None
    with Image.open(io.BytesIO(before["png"])) as a, Image.open(io.BytesIO(after["png"])) as b:
        if a.size != b.size:
            raise AssertionError(f"Screenshot sizes changed unexpectedly: {a.size} != {b.size}")
        if region:
            a = a.crop(region)
            b = b.crop(region)
        a = a.convert("RGB")
        b = b.convert("RGB")
        if a.size[0] * a.size[1] == 0:
            raise AssertionError("Empty screenshot comparison region")
        difference = ImageChops.difference(a, b)
        # Approximate changed-pixel count efficiently via a grayscale
        # threshold mask, avoiding Python loops over millions of pixels.
        mask = difference.convert("L").point(lambda intensity: 255 if intensity >= 16 else 0)
        histogram = mask.histogram()
        fraction = histogram[255] / (a.size[0] * a.size[1])
        log(f"SCREENSHOT PIXEL DIFF fraction={fraction:.6%} region={region!r}")
        return fraction


def collect_failure(adb_run, adb, serial, trace, *, process=None):
    """Best-effort evidence collection to terminal and the combined TXT log."""
    log("FAILURE EVIDENCE BEGIN")
    try:
        if process is not None:
            log(f"FIXTURE EXIT STATUS pid={process.pid} code={process.poll()!r}")
        if trace.is_file():
            log("FIXTURE TRACE: " + trace.read_text(encoding="utf-8")[-25000:])
        for name, argv in [
            ("WINDOW", ("shell", "dumpsys", "window")),
            ("ACTIVITY", ("shell", "dumpsys", "activity", "activities")),
            ("PROCESS", ("shell", "pidof", GUI_PACKAGE)),
            ("LOGCAT", ("shell", "logcat", "-d", "-t", "180", "-v", "threadtime")),
        ]:
            try:
                output = adb_run(adb, serial, *argv, timeout=15)
                if name == "WINDOW":
                    lines = [l for l in output.splitlines() if
                             "Focus" in l or "focused" in l or GUI_PACKAGE in l]
                    output = "\n".join(lines[:100])
                elif name == "ACTIVITY":
                    lines = [l for l in output.splitlines() if
                             "Resumed" in l or "mFocused" in l or GUI_PACKAGE in l]
                    output = "\n".join(lines[:100])
                log(f"EVIDENCE {name}: {output[-24000:]}")
            except Exception as exc:
                log(f"EVIDENCE {name} ERROR: {exc!r}")
    finally:
        log("FAILURE EVIDENCE END")


def snapshot_android_setting(adb_run, adb, serial, namespace, key):
    return adb_run(adb, serial, "shell", "settings", "get", namespace, key).strip()


def restore_android_setting(adb_run, adb, serial, namespace, key, old):
    if old and old != "null":
        adb_run(adb, serial, "shell", "settings", "put", namespace, key, old)
    else:
        adb_run(adb, serial, "shell", "settings", "delete", namespace, key)


def screen_size_settings(wm_output):
    physical = re.search(r"Physical size:\s*(\d+)x(\d+)", wm_output)
    override = re.search(r"Override size:\s*(\d+)x(\d+)", wm_output)
    if not physical:
        raise ValueError(f"Android wm size unknown: {wm_output!r}")
    return tuple(map(int, physical.groups())), (
        tuple(map(int, override.groups())) if override else None
    )
