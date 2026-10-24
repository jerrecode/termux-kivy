"""Deterministic performance invariants and native-construction failure tests."""
import unittest
from types import SimpleNamespace

import fake_termuxgui as fake
from fake_termuxgui import Activity, Connection
from termux_kivy import (
    BoxLayout, Button, Clock, Label, TermuxBackend,
    ToggleButton, UnsupportedOperation,
)


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        self.backend = TermuxBackend(fake, idle_seconds=0)
        self.backend.connection = Connection()
        self.backend.activity = Activity(self.backend.connection)
        self.root = BoxLayout(orientation="vertical")
        self.backend.root = self.root

    def tearDown(self):
        self.backend._close()
        Clock.reset()

    def test_native_defaults_skip_redundant_calls(self):
        buttons = [self.root.add_widget(Button(text=str(i))) for i in range(60)]
        self.backend.mount(self.root)
        self.backend.flush()
        for button in buttons:
            calls = [name for name, _args in button._native.calls]
            self.assertNotIn("setvisibility", calls)
            self.assertNotIn("setclickable", calls)
            self.assertNotIn("settext", calls)

    def test_250_updates_coalesce_to_one_setter_call(self):
        label = self.root.add_widget(Label(text="initial"))
        self.backend.mount(self.root)
        self.backend.flush()
        native = label._native
        for index in range(250):
            label.text = f"value {index}"
        self.backend.flush()
        texts = [args for name, args in native.calls if name == "settext"]
        self.assertEqual(texts, [("value 249",)])

    def test_cancelled_long_timers_compact(self):
        handles = [Clock.schedule_once(lambda _dt: None, 86400) for _ in range(500)]
        for handle in handles:
            handle.cancel()
        self.assertLessEqual(len(Clock._queue), 128)

    def test_invalid_toggle_rejected_before_native_allocation(self):
        toggle = self.root.add_widget(ToggleButton(text="caption not supported"))
        with self.assertRaises(UnsupportedOperation):
            self.backend.mount(self.root)
        self.assertEqual(self.backend.stats["created"], 1)
        self.assertIsNone(toggle._native)

    def test_failed_native_constructor_releases_orphan_view(self):
        button = self.root.add_widget(Button(text="broken plugin"))
        class FaultyButton(fake.Button):
            def sendclickevent(self, enabled):
                raise OSError("simulated protocol failure")
        self.backend.tg = SimpleNamespace(
            LinearLayout=fake.LinearLayout,
            Button=FaultyButton,
            Connection=Connection,
            Activity=Activity,
        )
        with self.assertRaises(OSError):
            self.backend.mount(self.root)
        created = list(self.backend.activity.views.values())
        self.assertEqual(len(created), 2)
        self.assertTrue(all(native.deleted for native in created))
        self.assertIsNone(button._native)


if __name__ == "__main__":
    unittest.main()
