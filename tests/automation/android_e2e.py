#!/usr/bin/env python3
"""Optional real Android end-to-end driver (requires adb authorized to device).

Runs a real Termux:GUI Activity fixture, extracts actual native view bounds
using Android UIAutomator, injects actual touch and keyboard events using ADB,
and verifies both geometry and Python callbacks. Mock tests are separate.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from android_diagnostics import (
    capture, collect_failure, pixels_changed, require_foreground,
    restore_android_setting, screen_size_settings, snapshot_android_setting,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("android_fixture.py")
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def log(message):
    print(f"[{datetime.now().astimezone().isoformat(timespec='milliseconds')}] "
          f"[REAL-ANDROID] {message}", flush=True)


def check(condition, name, expected=None, actual=None):
    log(f"ASSERT {name}: {'PASS' if condition else 'FAIL'}; "
        f"expected={expected!r} actual={actual!r}")
    if not condition:
        raise AssertionError(f"{name}; expected={expected!r}, actual={actual!r}")


def adb_run(adb, serial, *args, timeout=25):
    command = [adb]
    if serial:
        command.extend(("-s", serial))
    command.extend(args)
    log(f"ADB EXEC: {command!r}")
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            errors="replace", timeout=timeout, check=False
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"ADB command did not run: {command!r}: {exc}") from exc
    log(f"ADB EXIT: code={result.returncode} "
        f"stdout={result.stdout[:10000]!r} stderr={result.stderr[:10000]!r}")
    if result.returncode:
        raise RuntimeError(f"ADB failed with exit {result.returncode}: {command!r}")
    return result.stdout


def read_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def await_condition(name, function, *, timeout=12, interval=0.15):
    started = time.monotonic()
    count = 0
    while time.monotonic() - started < timeout:
        count += 1
        result = function()
        if result:
            log(f"WAIT {name}: succeeded after {count} polls and "
                f"{time.monotonic() - started:.3f}s")
            return result
        time.sleep(interval)
    raise AssertionError(f"Timed out waiting for {name} after {timeout}s")


def read_ui(adb, serial, remote, *, expected_package=None):
    adb_run(adb, serial, "shell", "uiautomator", "dump", remote, timeout=30)
    xml = adb_run(adb, serial, "shell", "cat", remote, timeout=15)
    if not xml.lstrip().startswith("<?xml") and not xml.lstrip().startswith("<hierarchy"):
        raise ValueError(f"ADB UI hierarchy is not valid XML: {xml[:400]!r}")
    root = ET.fromstring(xml)
    if expected_package is not None:
        packages = [
            item.attrib.get("package", "")
            for item in root.iter("node")
            if item.attrib.get("text", "").startswith("TK-E2E-")
            or item.attrib.get("class", "").endswith("EditText")
        ]
        check(bool(packages) and all(p == expected_package for p in packages),
              "test fixture owns visible target controls (not a different foreground app)",
              expected=expected_package, actual=packages)
    nodes = []
    for item in root.iter("node"):
        value = item.attrib
        match = BOUNDS.fullmatch(value.get("bounds", ""))
        if not match:
            continue
        left, top, right, bottom = map(int, match.groups())
        nodes.append({
            "text": value.get("text", ""),
            "package": value.get("package", ""),
            "class": value.get("class", ""),
            "desc": value.get("content-desc", ""),
            "bounds": (left, top, right, bottom),
            "clickable": value.get("clickable"),
            "enabled": value.get("enabled"),
            "checked": value.get("checked"),
        })
    log(f"ANDROID UI DUMP: parsed {len(nodes)} nodes from actual device")
    for node in nodes:
        if node["text"] or "EditText" in node["class"]:
            log(f"UI NODE: {node!r}")
    return nodes


def by_text(nodes, text):
    matches = [node for node in nodes if node["text"] == text]
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one Android view with text={text!r}; "
                             f"found {len(matches)}")
    return matches[0]


def by_class(nodes, suffix):
    matches = [node for node in nodes if node["class"].endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one Android {suffix}, "
                             f"found {len(matches)}")
    return matches[0]


def midpoint(node):
    left, top, right, bottom = node["bounds"]
    check(left < right and top < bottom, "positive native bounds", actual=node)
    return ((left + right) // 2, (top + bottom) // 2)


def tap(adb, serial, node):
    x, y = midpoint(node)
    log(f"REAL TOUCH: tapping x={x}, y={y}, node={node!r}")
    adb_run(adb, serial, "shell", "input", "tap", str(x), str(y))


def verify_geometry(nodes, adb, serial, *, count=0):
    display = adb_run(adb, serial, "shell", "wm", "size")
    size = re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", display)
    if not size:
        raise AssertionError(f"Cannot determine Android screen dimensions: {display!r}")
    w, h = map(int, size.groups())
    ready = by_text(nodes, "TK-E2E-READY")
    status = by_text(nodes, f"TK-E2E-COUNT:{count}")
    button = by_text(nodes, "TK-E2E-TAP")
    field = by_class(nodes, "EditText")
    checkbox = by_text(nodes, "TK-E2E-CHECK")
    sequence = [ready, status, button, field, checkbox]
    log(f"SCREEN GEOMETRY: reported={w}x{h}; "
        f"ordered widget bounds={[node['bounds'] for node in sequence]!r}")
    # Android reports wm dimensions in device orientation, while UIAutomator
    # uses display coordinates. Accept a consistent transposition only when
    # all controls fit it; never allow the unrelated max(w,h) for both axes.
    candidates = [(w, h), (h, w)]
    valid = [
        (width, height)
        for width, height in candidates
        if all(
            0 <= node["bounds"][0] < node["bounds"][2] <= width
            and 0 <= node["bounds"][1] < node["bounds"][3] <= height
            for node in sequence
        )
    ]
    check(bool(valid), "all controls inside one actual display orientation",
          expected=candidates,
          actual=[node["bounds"] for node in sequence])
    selected = valid[0]
    log(f"SCREEN ORIENTATION: validated logical display extent {selected!r}")
    for node in sequence:
        l, t, r, b = node["bounds"]
        check(0 <= l < r <= selected[0] and 0 <= t < b <= selected[1],
              f"view {node['text']!r} inside physical screen extent",
              expected=f"within 0..{selected[0]} and 0..{selected[1]}",
              actual=node["bounds"])
    for upper, lower in zip(sequence, sequence[1:]):
        # Consecutive visible rows of the explicitly vertical layout should
        # not overlap or appear in reverse order.
        check(upper["bounds"][3] <= lower["bounds"][1],
              f"vertical non-overlap: {upper['text']!r} before {lower['text']!r}",
              expected="upper.bottom <= lower.top",
              actual=(upper["bounds"][3], lower["bounds"][1]))
    return button, field, checkbox


def stop_fixture(process):
    if process.poll() is not None:
        return
    log(f"STOP FIXTURE: terminating child process group pid={process.pid}")
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def ensure_foreground(adb, serial, timeout):
    require_foreground(adb_run, adb, serial, timeout=timeout)


def check_orientation(adb, serial, remote, timeout):
    """Test landscape once and restore Android user rotation even on errors."""
    old_auto = snapshot_android_setting(adb_run, adb, serial, "system",
                                        "accelerometer_rotation")
    old_rotation = snapshot_android_setting(adb_run, adb, serial, "system",
                                            "user_rotation")
    log(f"ORIENTATION original auto={old_auto!r} rotation={old_rotation!r}")
    try:
        adb_run(adb, serial, "shell", "settings", "put", "system",
                "accelerometer_rotation", "0")
        adb_run(adb, serial, "shell", "settings", "put", "system",
                "user_rotation", "1")
        time.sleep(2)
        ensure_foreground(adb, serial, timeout)
        nodes = read_ui(adb, serial, remote, expected_package="com.termux.gui")
        verify_geometry(nodes, adb, serial, count=1)
        log("ORIENTATION PASS: landscape viewport has valid native control geometry")
    finally:
        restore_android_setting(adb_run, adb, serial, "system",
                                "user_rotation", old_rotation)
        restore_android_setting(adb_run, adb, serial, "system",
                                "accelerometer_rotation", old_auto)
        log("ORIENTATION restored original Android rotation settings")


def check_display_matrix(adb, serial, remote, timeout):
    """Test a smaller viewport once and restore the original override."""
    physical, override = screen_size_settings(
        adb_run(adb, serial, "shell", "wm", "size"))
    original = override or physical
    target = (max(360, int(original[0] * .8)),
              max(640, int(original[1] * .8)))
    log(f"DISPLAY MATRIX original={original!r}, original_override={override!r}, "
        f"temporary={target!r}")
    try:
        adb_run(adb, serial, "shell", "wm", "size",
                f"{target[0]}x{target[1]}")
        time.sleep(2)
        ensure_foreground(adb, serial, timeout)
        nodes = read_ui(adb, serial, remote, expected_package="com.termux.gui")
        verify_geometry(nodes, adb, serial, count=1)
        log("DISPLAY MATRIX PASS: valid geometry at reduced viewport")
    finally:
        if override is not None:
            adb_run(adb, serial, "shell", "wm", "size",
                    f"{override[0]}x{override[1]}")
        else:
            adb_run(adb, serial, "shell", "wm", "size", "reset")
        log("DISPLAY MATRIX restored original Android display resolution")


def run(adb, serial, *, foreground_timeout=4, save_screenshots=False,
        orientation_check=False, display_matrix=False):
    state = adb_run(adb, serial, "get-state").strip()
    check(state == "device", "authorized ADB device available",
          expected="device", actual=state)
    adb_run(adb, serial, "devices", "-l")
    try:
        import termuxgui
    except ImportError as exc:
        raise RuntimeError(
            "Real Android mode requires Termux:GUI Python bindings in the "
            "same Termux interpreter running this script"
        ) from exc

    with tempfile.TemporaryDirectory(prefix="termux-kivy-native-e2e-") as workspace:
        trace = Path(workspace) / "state.json"
        remote = f"/sdcard/termux_kivy_ui_{os.getpid()}.xml"
        savedir = (ROOT / "logs" / ("android-screenshots-"
                   + datetime.now().strftime("%Y%m%d-%H%M%S")
                   + "-" + str(os.getpid()))) if save_screenshots else None
        log("SCREENSHOT MODE: in-memory captures"
            + (f", saving additional PNG files to {savedir}" if savedir else ""))
        command = [
            sys.executable, "-u", str(FIXTURE), "--trace", str(trace)
        ]
        log(f"START REAL APP: {command!r}")
        process = subprocess.Popen(
            command, cwd=str(ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, start_new_session=(os.name == "posix")
        )

        def read_child():
            if process.stdout is not None:
                for line in process.stdout:
                    log(f"FIXTURE pid={process.pid}: {line.rstrip()}")
        reader = threading.Thread(target=read_child, daemon=True)
        reader.start()
        try:
            await_condition("Termux:GUI fixture Activity ready", lambda:
                (read_state(trace) or {}).get("ready") is True, timeout=15)
            ensure_foreground(adb, serial, foreground_timeout)
            nodes = read_ui(adb, serial, remote, expected_package="com.termux.gui")
            button, field, checkbox = verify_geometry(nodes, adb, serial)
            before = capture(adb, serial, "before-tap", output_dir=savedir)

            ensure_foreground(adb, serial, foreground_timeout)
            tap(adb, serial, button)
            clicked = await_condition(
                "click callback", lambda: (read_state(trace) or {}).get("clicks") == 1
            )
            check(clicked, "actual physical tap triggered Python callback",
                  expected=True, actual=clicked)
            ensure_foreground(adb, serial, foreground_timeout)
            updated_nodes = read_ui(adb, serial, remote,
                                    expected_package="com.termux.gui")
            status = by_text(updated_nodes, "TK-E2E-COUNT:1")
            log("ASSERT real label redraw PASS: TK-E2E-COUNT:1 is in native hierarchy")
            after_tap = capture(adb, serial, "after-tap", output_dir=savedir)
            if before["dimensions"] == after_tap["dimensions"]:
                changed = pixels_changed(before, after_tap, region=status["bounds"])
                if changed is not None:
                    check(changed > 0, "screenshot changed inside counter label after tap",
                          expected="nonzero changed-pixel fraction", actual=changed)
            else:
                log("SCREENSHOT DIMENSIONS CHANGED after button; "
                    "native UI label was successfully verified")

            ensure_foreground(adb, serial, foreground_timeout)
            tap(adb, serial, checkbox)
            checked = await_condition(
                "checkbox callback", lambda:
                (read_state(trace) or {}).get("checked") is True
            )
            check(checked, "physical checkbox tap updates model", expected=True, actual=checked)

            # Fetch fresh bounds before keyboard interaction. Typing may resize
            # Android's viewport once the soft keyboard opens.
            ensure_foreground(adb, serial, foreground_timeout)
            nodes = read_ui(adb, serial, remote, expected_package="com.termux.gui")
            entry = by_class(nodes, "EditText")
            tap(adb, serial, entry)
            log("REAL KEYBOARD: typing ASCII sample Termux42 through adb input")
            adb_run(adb, serial, "shell", "input", "text", "Termux42")
            typed = await_condition(
                "text callback", lambda:
                "Termux42" in (read_state(trace) or {}).get("typed", "")
            )
            check(typed, "physical keyboard input reached TextInput", expected=True, actual=typed)

            final = read_state(trace)
            log(f"FINAL REAL DEVICE CALLBACK TRACE: {json.dumps(final, ensure_ascii=False)}")
            adb_run(adb, serial, "shell", "input", "keyevent", "4")
            try:
                await_condition("fixture termination after Android back", lambda:
                                process.poll() is not None, timeout=2)
            except AssertionError:
                # Android IMEs usually consume the first Back press to close
                # the soft keyboard. Only issue another if the fixture lives.
                log("BACK: first press probably dismissed the IME; sending a second Back")
                adb_run(adb, serial, "shell", "input", "keyevent", "4")
                await_condition("fixture termination after second Android back", lambda:
                                process.poll() is not None, timeout=7)
            check(process.returncode == 0, "fixture exited cleanly",
                  expected=0, actual=process.returncode)
            log("REAL ANDROID E2E PASS: physical tap, input, viewport and callbacks verified")
            return 0
        finally:
            try:
                adb_run(adb, serial, "shell", "rm", "-f", remote, timeout=8)
            except Exception as exc:
                log(f"Cleanup warning for on-device UI dump: {exc}")
            stop_fixture(process)
            reader.join(timeout=3)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial")
    parser.add_argument("--foreground-timeout", type=float, default=4)
    parser.add_argument("--save-screenshots", action="store_true")
    parser.add_argument("--orientation-check", action="store_true")
    parser.add_argument("--display-matrix", action="store_true")
    args = parser.parse_args(argv)
    try:
        return run(args.adb, args.serial,
                   foreground_timeout=args.foreground_timeout,
                   save_screenshots=args.save_screenshots,
                   orientation_check=args.orientation_check,
                   display_matrix=args.display_matrix)
    except BaseException as exc:
        import traceback
        log(f"REAL ANDROID FAILURE: {type(exc).__name__}: {exc}")
        log(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
