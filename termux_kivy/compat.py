"""Opt-in Kivy *subset* import aliases, deliberately not a global site hook.

Usage: from termux_kivy.compat import activate; activate()
Then: from kivy.uix.button import Button
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys

from . import core
from .kv import Builder, Factory

_PACKAGES = {"kivy", "kivy.uix", "kivy.core"}
_MODULES = {
    "kivy": {"__version__": "termux-kivy-0.1-subset", "require": lambda *_: None},
    "kivy.app": {"App": core.App},
    "kivy.event": {"EventDispatcher": core.EventDispatcher},
    "kivy.clock": {"Clock": core.Clock},
    "kivy.lang": {"Builder": Builder},
    "kivy.factory": {"Factory": Factory},
    "kivy.metrics": {"dp": float, "sp": float},
    "kivy.properties": {
        name: getattr(core, name) for name in (
            "StringProperty", "NumericProperty", "BooleanProperty",
            "ObjectProperty", "ListProperty"
        )
    },
    "kivy.uix": {},
    "kivy.core": {},
}
for _name in (
    "Widget", "BoxLayout", "GridLayout", "FloatLayout", "ScrollView",
    "Label", "Button", "TextInput", "CheckBox", "Switch", "ProgressBar",
    "ToggleButton", "Spinner", "Image"
):
    _MODULES["kivy.uix." + _name.lower()] = {_name: getattr(core, _name)}


class _Loader(importlib.abc.Loader):
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__dict__.update(_MODULES[module.__name__])
        module.__tgk_shim__ = True
        if module.__name__ in _PACKAGES:
            module.__path__ = []


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in _MODULES:
            return None
        return importlib.machinery.ModuleSpec(
            fullname, _Loader(), is_package=fullname in _PACKAGES
        )


_finder = _Finder()


def activate():
    for name, module in sys.modules.items():
        if name == "kivy" or name.startswith("kivy."):
            if not getattr(module, "__tgk_shim__", False):
                raise RuntimeError("Kivy was already imported; explicit compatibility must be enabled first")
    if _finder not in sys.meta_path:
        sys.meta_path.insert(0, _finder)


def deactivate():
    if _finder in sys.meta_path:
        sys.meta_path.remove(_finder)
    for name, module in list(sys.modules.items()):
        if (name == "kivy" or name.startswith("kivy.")) and getattr(module, "__tgk_shim__", False):
            sys.modules.pop(name, None)
