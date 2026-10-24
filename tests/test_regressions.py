"""Regression coverage for real Termux:GUI protocol behavior and failure paths."""
import threading
import unittest
from types import SimpleNamespace

import fake_termuxgui as fake
from fake_termuxgui import Activity, Connection, event
from termux_kivy import (
    BoxLayout, Button, GridLayout, Label, ListProperty, ProgressBar,
    Spinner, TermuxBackend, ToggleButton, Widget, UnsupportedOperation,
)
from termux_kivy.core import EventDispatcher


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.backend = TermuxBackend(fake, idle_seconds=0)
        self.backend.connection = Connection()
        self.backend.activity = Activity(self.backend.connection)
        self.root = BoxLayout(orientation="vertical")
        self.backend.root = self.root

    def tearDown(self):
        self.backend._close()

    def test_string_selection_not_index_and_no_native_echo(self):
        spinner = self.root.add_widget(
            Spinner(values=["1", "2", "0"], text="1")
        )
        self.backend.mount(self.root)
        self.backend.flush()
        native = spinner._native
        self.backend.handle_event(event("itemselected", native, selected="2"))
        self.backend.flush()
        self.assertEqual(spinner.text, "2")
        self.assertEqual(self.backend._state[spinner]["selected"], 1)
        # A native selection event should not trigger another selection IPC.
        selection_calls = [x for x in native.calls if x[0] == "selectitem"]
        self.assertEqual(selection_calls, [("selectitem", (0,))])

    def test_observable_spinner_values_reconcile(self):
        spinner = self.root.add_widget(Spinner(values=["a"], text="a"))
        self.backend.mount(self.root)
        self.backend.flush()
        seen = []
        spinner.bind(values=lambda _w, value: seen.append(list(value)))
        spinner.values.append("b")
        spinner.values.append("c")
        self.backend.flush()
        self.assertEqual(seen, [["a", "b"], ["a", "b", "c"]])
        self.assertIn(("setlist", (["a", "b", "c"],)), spinner._native.calls)
        # Selects index zero again after setlist.
        self.backend.flush()
        self.assertGreaterEqual(
            [x for x in spinner._native.calls if x[0] == "selectitem"].count(
                ("selectitem", (0,))
            ), 2
        )

    def test_observable_list_nonwidget_owner(self):
        class State(EventDispatcher):
            values = ListProperty()
        state = State()
        seen = []
        state.bind(values=lambda _obj, v: seen.append(list(v)))
        state.values.extend([1, 2])
        state.values[0] = 3
        state.values.pop()
        self.assertEqual(seen, [[1, 2], [3, 2], [3]])

    def test_reassignment_detaches_obsolete_list(self):
        class State(EventDispatcher):
            values = ListProperty()
        item = State()
        old = item.values
        item.values = ["new"]
        events = []
        item.bind(values=lambda _obj, v: events.append(list(v)))
        old.append("stale")
        self.assertEqual(events, [])

    def test_native_grid_positions(self):
        grid = self.root.add_widget(GridLayout(cols=2))
        widgets = [grid.add_widget(Label(text=str(i))) for i in range(3)]
        self.backend.mount(self.root)
        self.backend.flush()
        self.assertEqual(
            [
                [args for name, args in node._native.calls
                 if name == "setgridlayoutparams"]
                for node in widgets
            ],
            [[(0, 0)], [(0, 1)], [(1, 0)]]
        )

    def test_failed_setter_retains_dirty_for_retry(self):
        label = self.root.add_widget(Label(text="before"))
        self.backend.mount(self.root)
        self.backend.flush()
        native = label._native
        failures = [True]
        original = native.settext
        def flaky(value):
            if failures.pop(0):
                raise OSError("temporary connection failure")
            return original(value)
        native.settext = flaky
        label.text = "after"
        with self.assertRaises(OSError):
            self.backend.flush()
        self.assertIn(label, self.backend._dirty)
        self.backend.flush()
        self.assertEqual(label.text, "after")
        self.assertIn(("settext", ("after",)), native.calls)

    def test_mount_failure_only_deletes_native_subtree_once(self):
        class Unsupported(Widget):
            pass
        self.root.add_widget(Label(text="mounted before failure"))
        self.root.add_widget(Unsupported())
        with self.assertRaises(UnsupportedOperation):
            self.backend.mount(self.root)
        self.assertEqual(self.backend.stats["deleted"], 1)
        self.assertFalse(self.backend._index)
        self.assertFalse(self.backend._state)
        self.assertTrue(all(n._backend is None for n in self.root.walk()))

    def test_invalid_live_properties_are_atomic(self):
        toggle = self.root.add_widget(ToggleButton())
        progress = self.root.add_widget(ProgressBar())
        self.backend.mount(self.root)
        with self.assertRaises(ValueError):
            toggle.state = "invalid"
        self.assertEqual(toggle.state, "normal")
        with self.assertRaises(UnsupportedOperation):
            toggle.text = "native control has no custom caption"
        self.assertEqual(toggle.text, "")
        with self.assertRaises(ValueError):
            progress.max = 0
        self.assertEqual(progress.max, 100)

    def test_worker_stop_enqueued_on_ui_thread(self):
        self.backend._owner = threading.get_ident()
        self.backend.mount(self.root)
        worker = threading.Thread(target=self.backend.stop)
        worker.start()
        worker.join()
        self.assertFalse(self.backend._stopping)
        self.assertFalse(self.backend.activity.finished)
        self.backend._drain_tasks()
        self.assertTrue(self.backend._stopping)
        self.assertTrue(self.backend.activity.finished)

    def test_failed_activity_constructor_cleans_state(self):
        def missing_permission(_conn, **_kwargs):
            raise PermissionError("overlay denied")
        plugin = SimpleNamespace(Connection=Connection, Activity=missing_permission)
        backend = TermuxBackend(plugin, window_mode="overlay")
        root = Label(text="hello")
        with self.assertRaises(PermissionError):
            backend.run(root)
        self.assertIsNone(backend.root)
        self.assertIsNone(backend.activity)
        self.assertIsNone(backend._owner)

    def test_normal_exit_finishes_before_connection_closes(self):
        calls = []
        class TrackingActivity(Activity):
            def finish(self):
                calls.append(("finish", self.connection.closed))
                super().finish()
        plugin = SimpleNamespace(Connection=Connection, Activity=TrackingActivity)
        backend = TermuxBackend(plugin, idle_seconds=0)
        root = Label(text="hello")
        backend.run(root, on_start=backend.stop)
        self.assertEqual(calls, [("finish", False)])
        self.assertEqual(backend.stats["deleted"], 0)


if __name__ == "__main__":
    unittest.main()
