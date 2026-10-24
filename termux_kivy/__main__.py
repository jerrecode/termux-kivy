"""Small diagnostics and example launcher; no implicit Android connection."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import sys

from . import __version__


def doctor(*, connect=False):
    binding = importlib.util.find_spec("termuxgui") is not None
    report = {
        "project": "termux-kivy",
        "version": __version__,
        "python": platform.python_version(),
        "platform": sys.platform,
        "termux_prefix_detected": os.environ.get("PREFIX", "").startswith(
            "/data/data/com.termux/files/usr"
        ),
        "termuxgui_python_binding": "installed" if binding else "missing",
        "android_plugin": "not_checked",
        "connected": False,
    }
    if connect:
        if not binding:
            report["android_plugin"] = "cannot_test_without_binding"
        else:
            try:
                import termuxgui as tg
                with tg.Connection():
                    report["connected"] = True
                    report["android_plugin"] = "connection_successful"
            except Exception as exc:
                report["android_plugin"] = "connection_failed"
                report["connection_error"] = f"{type(exc).__name__}: {exc}"
    return report


def demo():
    from . import App, BoxLayout, Button, Label
    class Demo(App):
        def build(self):
            self.value = 0
            root = BoxLayout(orientation="vertical")
            self.label = root.add_widget(Label(text="Count: 0", font_size=24))
            button = root.add_widget(Button(text="Increment"))
            button.bind(on_press=self.clicked)
            return root

        def clicked(self, _widget):
            self.value += 1
            self.label.text = f"Count: {self.value}"
    Demo().run()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="termux-kivy")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("doctor", help="print environment capability diagnostics")
    check.add_argument("--connect", action="store_true", help="attempt a real plugin connection")
    check.add_argument("--json", action="store_true")
    sub.add_parser("demo", help="launch a native counter demo")
    sub.add_parser("version", help="print installed runtime version")
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "demo":
        demo()
        return 0
    status = doctor(connect=args.connect)
    if args.json:
        print(json.dumps(status, sort_keys=True))
    else:
        for name, value in status.items():
            print(f"{name}: {value}")
    return 2 if args.connect and not status["connected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
