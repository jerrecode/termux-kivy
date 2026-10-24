import contextlib
from io import StringIO
import json
import tempfile
from pathlib import Path
import unittest

import fake_termuxgui as fake
from termux_kivy import BoxLayout, Image, Spinner, ToggleButton, TermuxBackend
from termux_kivy.__main__ import main
from fake_termuxgui import Activity, Connection, event


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.backend = TermuxBackend(fake, idle_seconds=0)
        self.backend.connection = Connection()
        self.backend.activity = Activity(self.backend.connection)
        self.root = BoxLayout(orientation="vertical")
        self.backend.root = self.root

    def tearDown(self):
        self.backend._close()

    def test_native_spinner_and_toggle(self):
        spinner = self.root.add_widget(Spinner(text="one", values=["one", "two"]))
        toggle = self.root.add_widget(ToggleButton(text="Enable"))
        self.backend.mount(self.root)
        self.backend.flush()
        self.assertEqual(spinner._native.kwargs["parent_id"], self.root._native.id)
        self.backend.handle_event(event("itemselected", spinner._native, selected=1))
        self.backend.handle_event(event("click", toggle._native, set=True))
        self.backend.flush()
        self.assertEqual(spinner.text, "two")
        self.assertEqual(toggle.state, "down")
        self.assertIn(("setchecked", (True,)), toggle._native.calls)

    def test_image_path_limit_and_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "small.png"
            source.write_bytes(b"fake-image-payload")
            image = self.root.add_widget(Image(source=str(source)))
            self.backend.mount(self.root)
            self.backend.flush()
            self.assertIn(("setimage", (b"fake-image-payload",)), image._native.calls)
            bad = Path(tmp) / "bad.txt"
            bad.write_text("text")
            image.source = str(bad)
            with self.assertRaises(ValueError):
                self.backend.flush()


class CLITests(unittest.TestCase):
    def test_cli_doctor_json_and_version(self):
        out = StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["doctor", "--json"]), 0)
        info = json.loads(out.getvalue())
        self.assertEqual(info["project"], "termux-kivy")
        self.assertEqual(info["android_plugin"], "not_checked")
        out = StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["version"]), 0)
        self.assertEqual(out.getvalue().strip(), info["version"])
