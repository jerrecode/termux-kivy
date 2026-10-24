"""Offline verification of Android diagnostics, focus and screenshot parsers."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import io
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


AUTOMATION = Path(__file__).resolve().parent / "automation"
sys.path.insert(0, str(AUTOMATION))
import android_diagnostics as d


def sample_png(w=360, h=720):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13)
            + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
            + b"\x00\x00\x00\x00")


class NativeDiagnosticTests(unittest.TestCase):
    def test_identifies_termux_gui_foreground(self):
        lines = ("mFocusedApp=ActivityRecord{ab u0 com.termux.gui/.MainActivity}\n"
                 "mCurrentFocus=Window{abcdef u0 com.termux.gui/com.termux.gui.MainActivity}\n")
        self.assertEqual(d.focus_package(lines), "com.termux.gui")

    def test_rejects_termux_when_it_replaces_gui(self):
        lines = "mCurrentFocus=Window{3cf1 u0 com.termux/com.termux.app.TermuxActivity}"
        self.assertEqual(d.focus_package(lines), "com.termux")
        def adb_run(*args, **kwargs):
            return lines
        with patch.object(d.time, "sleep", return_value=None):
            with self.assertRaises(AssertionError):
                d.require_foreground(adb_run, "adb", None, timeout=.05)

    def test_foreground_wait_can_recover(self):
        responses = iter((
            "mCurrentFocus=Window{a u0 com.termux/com.termux.app.TermuxActivity}",
            "mCurrentFocus=Window{b u0 com.termux.gui/com.termux.gui.MainActivity}",
        ))
        with patch.object(d.time, "sleep", return_value=None):
            d.require_foreground(lambda *args, **kwargs: next(responses),
                                 "adb", None, timeout=3)

    def test_unknown_focus_reports_unknown(self):
        self.assertIsNone(d.focus_package("mCurrentFocus=null"))

    def test_png_dimensions_and_invalid_capture(self):
        self.assertEqual(d.png_dimensions(sample_png()), (360, 720))
        with self.assertRaises(ValueError):
            d.png_dimensions(b"not-a-png")
        with self.assertRaises(ValueError):
            d.png_dimensions(sample_png(0, 720))

    def test_binary_capture_and_digest(self):
        with patch.object(d.subprocess, "run", return_value=types.SimpleNamespace(
            stdout=sample_png(720, 360), stderr=b"", returncode=0
        )):
            with tempfile.TemporaryDirectory() as tmp:
                captured = d.capture("adb", None, "landscape", output_dir=tmp)
                self.assertEqual(captured["dimensions"], (720, 360))
                self.assertTrue((Path(tmp) / "landscape.png").is_file())
                self.assertEqual(len(captured["sha256"]), 64)

    def test_pillow_pixel_crop_detects_redraw(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed; no pixel decoder available")
        before = Image.new("RGB", (100, 100), "white")
        after = before.copy()
        for x in range(30, 40):
            for y in range(20, 30):
                after.putpixel((x, y), (0, 0, 0))
        def pack(image):
            payload = io.BytesIO()
            image.save(payload, format="PNG")
            return {"png": payload.getvalue()}
        fraction = d.pixels_changed(pack(before), pack(after),
                                    region=(25, 15, 45, 35))
        self.assertIsNotNone(fraction)
        self.assertGreater(fraction, 0)
        self.assertLess(fraction, 1)
        outside = d.pixels_changed(pack(before), pack(after),
                                   region=(0, 0, 20, 20))
        self.assertEqual(outside, 0)

    def test_display_size_override_parsing(self):
        self.assertEqual(
            d.screen_size_settings("Physical size: 1080x2392\nOverride size: 720x1280"),
            ((1080, 2392), (720, 1280))
        )
        self.assertEqual(
            d.screen_size_settings("Physical size: 1080x2392"),
            ((1080, 2392), None)
        )
        with self.assertRaises(ValueError):
            d.screen_size_settings("No size available")

    def test_android_settings_restoration(self):
        calls = []
        def fake(*args, **kwargs):
            calls.append(args)
            return ""
        d.restore_android_setting(fake, "adb", None, "system", "user_rotation", "1")
        d.restore_android_setting(fake, "adb", None, "system", "unused", "null")
        self.assertIn(("adb", None, "shell", "settings", "put", "system",
                       "user_rotation", "1"), calls)
        self.assertIn(("adb", None, "shell", "settings", "delete", "system",
                       "unused"), calls)

    def test_package_from_ui_hierarchy(self):
        xml = ("<hierarchy><node package='com.termux.gui' />"
               "<node package='com.termux.gui' /><node package='com.termux' />"
               "</hierarchy>")
        self.assertEqual(d.package_from_ui_xml(xml), "com.termux.gui")


if __name__ == "__main__":
    unittest.main()
