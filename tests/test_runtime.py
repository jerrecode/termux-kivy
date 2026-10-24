import importlib
import threading
import unittest

from termux_kivy import (
    App, BoxLayout, Button, CheckBox, Clock, GridLayout, Label,
    ProgressBar, ScrollView, TextInput, TermuxBackend, Widget,
    UnsupportedOperation, ListProperty, StringProperty, Builder, KVError,
)
from termux_kivy.compat import activate, deactivate
from fake_termuxgui import Activity, Connection, Event, event
import fake_termuxgui as fake


class Mounted(unittest.TestCase):
    def setUp(self):
        self.backend = TermuxBackend(fake, idle_seconds=0)
        self.backend.connection = Connection()
        self.backend.activity = Activity(self.backend.connection)
        self.root = BoxLayout(orientation="vertical")
        self.backend.root = self.root

    def tearDown(self):
        self.backend._close()
        Clock.reset()


class ModelTests(unittest.TestCase):
    def test_property_events_and_mutable_defaults(self):
        class Model(Widget):
            note = StringProperty("ready")
            values = ListProperty()
        left, right = Model(), Model()
        log = []
        left.bind(note=lambda instance, value: log.append(value))
        left.note = "changed"
        left.note = "changed"
        left.values.append(1)
        self.assertEqual(log, ["changed"])
        self.assertEqual(right.values, [])

    def test_prevent_cycles_and_invalid_children(self):
        a, b = Widget(), Widget()
        a.add_widget(b)
        with self.assertRaises(ValueError):
            b.add_widget(a)
        with self.assertRaises(ValueError):
            a.add_widget(b)
        with self.assertRaises(TypeError):
            a.add_widget("not a widget")

    def test_clock_cancellation_and_budget(self):
        seen = []
        Clock.schedule_once(lambda dt: seen.append("first"))
        handle = Clock.schedule_once(lambda dt: seen.append("second"))
        handle.cancel()
        Clock.tick(1)
        Clock.tick(8)
        self.assertEqual(seen, ["first"])
        Clock.reset()


class BackendTests(Mounted):
    def test_create_and_propagate(self):
        label = self.root.add_widget(Label(text="original"))
        self.backend.mount(self.root)
        self.backend.flush()
        native = label._native
        label.text = "intermediate"
        label.text = "final"
        self.backend.flush()
        self.assertEqual(
            [args for name, args in native.calls if name == "settext"],
            [("final",)],
        )
        self.assertEqual(self.backend.stats["created"], 2)

    def test_dynamic_insertion_removal_and_stale_event(self):
        button = Button(text="submit")
        presses = []
        button.bind(on_press=lambda obj: presses.append("pressed"))
        self.backend.mount(self.root)
        self.root.add_widget(button)
        self.backend.handle_event(event("click", button._native))
        self.assertEqual(presses, ["pressed"])
        native = button._native
        self.root.remove_widget(button)
        self.assertTrue(native.deleted)
        self.backend.handle_event(event("click", native))
        self.assertEqual(presses, ["pressed"])

    def test_edittext_no_keyboard_echo(self):
        field = self.root.add_widget(TextInput(text=""))
        self.backend.mount(self.root)
        self.backend.flush()
        native = field._native
        self.backend.handle_event(event("text", native, text="héllo"))
        self.backend.flush()
        self.assertEqual(field.text, "héllo")
        self.assertFalse([x for x in native.calls if x[0] == "settext"])
        field.text = "reset"
        self.backend.flush()
        self.assertIn(("settext", ("reset",)), native.calls)

    def test_checkbox_and_progress(self):
        checkbox = self.root.add_widget(CheckBox())
        progress = self.root.add_widget(ProgressBar(value=25, max=200))
        self.backend.mount(self.root)
        self.backend.flush()
        self.backend.handle_event(event("click", checkbox._native, set=True))
        self.backend.flush()
        self.assertTrue(checkbox.active)
        self.assertIn(("setprogress", (12,)), progress._native.calls)

    def test_grid_live_structure_explains_limitation(self):
        grid = self.root.add_widget(GridLayout(cols=2))
        grid.add_widget(Label(text="a"))
        self.backend.mount(self.root)
        with self.assertRaises(UnsupportedOperation):
            grid.add_widget(Label(text="b"))

    def test_worker_post_and_thread_affinity(self):
        label = self.root.add_widget(Label(text="old"))
        self.backend.mount(self.root)
        errors = []
        def worker():
            try:
                label.text = "unsafe"
            except RuntimeError as exc:
                errors.append(str(exc))
            self.backend.post(setattr, label, "text", "safe")
        # owner set only on run; manually establish Activity's UI owner.
        self.backend._owner = threading.get_ident()
        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertTrue(errors)
        self.backend._drain_tasks()
        self.backend.flush()
        self.assertEqual(label.text, "safe")


class KVTests(unittest.TestCase):
    def test_tree_ids_and_safety(self):
        root = Builder.load_string("""
BoxLayout:
    orientation: 'vertical'
    Label:
        id: headline
        text: 'Hello'
    Button:
        text: 'Go'
""")
        self.assertIs(root.ids["headline"], root.children[0])
        self.assertEqual(root.children[0].text, "Hello")
        with self.assertRaises(KVError):
            Builder.load_string("Button:\n    text: __import__('os').system('id')")
        with self.assertRaises(KVError):
            Builder.load_string("BoxLayout:\n    BadWidget:")

    def test_opt_in_imports_are_reversible(self):
        try:
            activate()
            mod = importlib.import_module("kivy.uix.button")
            self.assertIs(mod.Button, Button)
        finally:
            deactivate()
        self.assertNotIn("kivy", __import__("sys").modules)


class LifecycleTests(unittest.TestCase):
    def test_on_start_stop_and_fake_activity(self):
        class Demo(App):
            def __init__(self):
                super().__init__()
                self.transitions = []
            def build(self):
                self.transitions.append("build")
                return Label(text="Hello")
            def on_start(self):
                self.transitions.append("start")
                self.stop()
            def on_stop(self):
                self.transitions.append("stop")
        demo = Demo()
        backend = TermuxBackend(fake, idle_seconds=0)
        demo.run(backend=backend)
        self.assertEqual(demo.transitions, ["build", "start", "stop"])
        self.assertIsNone(App.get_running_app())


if __name__ == "__main__":
    unittest.main()
