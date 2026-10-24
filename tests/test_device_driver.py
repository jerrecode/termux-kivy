"""Offline tests of the real-device driver's bounds and UI-hierarchy checks.

These tests verify the ADB controller's parsing and fail-closed assertions.
They do not falsely claim a physical Android run.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


DRIVER_PATH = Path(__file__).resolve().parent / "automation" / "android_e2e.py"
SPEC = importlib.util.spec_from_file_location("termux_kivy_android_e2e_driver", DRIVER_PATH)
assert SPEC is not None and SPEC.loader is not None
driver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = driver
SPEC.loader.exec_module(driver)


def node(text, bounds, cls="android.widget.TextView"):
    return {"text": text, "bounds": bounds, "class": cls,
            "desc": "", "enabled": "true", "checked": "false",
            "clickable": "true"}


def screen():
    return [
        node("TK-E2E-READY", (0, 0, 360, 50)),
        node("TK-E2E-COUNT:0", (0, 50, 360, 100)),
        node("TK-E2E-TAP", (0, 100, 360, 160), "android.widget.Button"),
        node("", (0, 160, 360, 220), "android.widget.EditText"),
        node("TK-E2E-CHECK", (0, 220, 360, 280), "android.widget.CheckBox"),
    ]


class ADBGeometryTests(unittest.TestCase):
    def test_correct_vertical_screen(self):
        with patch.object(driver, "adb_run", return_value="Physical size: 360x720"):
            button, entry, checkbox = driver.verify_geometry(screen(), "adb", None)
        self.assertEqual(button["bounds"], (0, 100, 360, 160))
        self.assertEqual(entry["class"], "android.widget.EditText")
        self.assertEqual(checkbox["text"], "TK-E2E-CHECK")

    def test_offscreen_widget_is_rejected(self):
        nodes = screen()
        nodes[-1] = node("TK-E2E-CHECK", (0, 710, 370, 800))
        with patch.object(driver, "adb_run", return_value="Physical size: 360x720"):
            with self.assertRaises(AssertionError):
                driver.verify_geometry(nodes, "adb", None)

    def test_overlapping_native_rows_are_rejected(self):
        nodes = screen()
        nodes[2] = node("TK-E2E-TAP", (0, 80, 360, 160), "android.widget.Button")
        with patch.object(driver, "adb_run", return_value="Physical size: 360x720"):
            with self.assertRaises(AssertionError):
                driver.verify_geometry(nodes, "adb", None)

    def test_missing_target_does_not_silently_pass(self):
        nodes = [n for n in screen() if n["text"] != "TK-E2E-TAP"]
        with patch.object(driver, "adb_run", return_value="Physical size: 360x720"):
            with self.assertRaises(AssertionError):
                driver.verify_geometry(nodes, "adb", None)

    def test_parse_real_uiautomator_xml(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node text="TK-E2E-READY" class="android.widget.TextView"
        bounds="[0,0][360,50]" clickable="false" enabled="true" />
  <node text="TK-E2E-TAP" class="android.widget.Button"
        bounds="[0,100][360,160]" clickable="true" enabled="true" />
</hierarchy>"""
        with patch.object(driver, "adb_run",
                          side_effect=["UI hierarchy dumped to file", xml]):
            nodes = driver.read_ui("adb", None, "/sdcard/test-hierarchy.xml")
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[1]["bounds"], (0, 100, 360, 160))
        self.assertEqual(nodes[1]["text"], "TK-E2E-TAP")

    def test_reject_foreign_foreground_ui(self):
        xml = """<?xml version="1.0"?>
<hierarchy><node text="TK-E2E-READY" class="android.widget.TextView"
package="com.termux" bounds="[0,0][360,50]"/></hierarchy>"""
        with patch.object(driver, "adb_run", side_effect=["dump complete", xml]):
            with self.assertRaises(AssertionError):
                driver.read_ui("adb", None, "/sdcard/ui.xml",
                               expected_package="com.termux.gui")

    def test_display_override_used_for_geometry_not_physical_size(self):
        with patch.object(driver, "adb_run",
                          return_value="Physical size: 1080x2392\nOverride size: 360x720"):
            driver.verify_geometry(screen(), "adb", None)
        overwide = screen()
        overwide[0] = node("TK-E2E-READY", (0, 0, 480, 50))
        with patch.object(driver, "adb_run",
                          return_value="Physical size: 1080x2392\nOverride size: 360x720"):
            with self.assertRaises(AssertionError):
                driver.verify_geometry(overwide, "adb", None)

    def test_orientation_failure_always_restores_settings(self):
        restored = []
        def restore(*args):
            restored.append(args[-2:])
        with patch.object(driver, "snapshot_android_setting",
                          side_effect=["1", "0"]), \
             patch.object(driver, "capture",
                          return_value={"dimensions": (1080, 2392)}), \
             patch.object(driver, "adb_run", return_value=""), \
             patch.object(driver, "ensure_foreground"), \
             patch.object(driver.time, "sleep"), \
             patch.object(driver, "read_ui", side_effect=RuntimeError("UI lost")), \
             patch.object(driver, "restore_android_setting", side_effect=restore):
            with self.assertRaises(RuntimeError):
                driver.check_orientation("adb", None, "/sdcard/test.xml", 4)
        self.assertEqual(restored, [
            ("user_rotation", "0"), ("accelerometer_rotation", "1")
        ])

    def test_display_failure_resets_override(self):
        calls = []
        def fake(*args, **kwargs):
            calls.append(args)
            return "Physical size: 1080x2392"
        with patch.object(driver, "adb_run", side_effect=fake), \
             patch.object(driver.time, "sleep"), \
             patch.object(driver, "ensure_foreground"), \
             patch.object(driver, "read_ui", side_effect=RuntimeError("lost GUI")):
            with self.assertRaises(RuntimeError):
                driver.check_display_matrix("adb", None, "/sdcard/test.xml", 4)
        self.assertIn(("adb", None, "shell", "wm", "size", "reset"), calls)

    def test_reject_invalid_hierarchy(self):
        with patch.object(driver, "adb_run", side_effect=["done", "NO_XML"]):
            with self.assertRaises(ValueError):
                driver.read_ui("adb", None, "/sdcard/test.xml")


if __name__ == "__main__":
    unittest.main()
