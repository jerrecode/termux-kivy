"""Termux-Kivy: explicit, minimal native Termux:GUI Python UI runtime.

The default import never imports Kivy or Termux:GUI and installs no import hook.
"""
__version__ = "0.1.2"

from .core import (
    App, BooleanProperty, BoxLayout, Button, CheckBox, Clock,
    EventDispatcher, FloatLayout, GridLayout, Image, Label, ListProperty,
    NumericProperty, ObjectProperty, ProgressBar, Property, ScrollView,
    Spinner, StringProperty, Switch, TextInput, ToggleButton, Widget,
)
from .backend import TermuxBackend, UnsupportedOperation
from .kv import Builder, Factory, KVError

__all__ = [
    "App", "BooleanProperty", "BoxLayout", "Button", "CheckBox", "Clock",
    "EventDispatcher", "FloatLayout", "GridLayout", "Image", "Label", "ListProperty",
    "NumericProperty", "ObjectProperty", "ProgressBar", "Property",
    "ScrollView", "Spinner", "StringProperty", "Switch", "TextInput", "ToggleButton", "Widget",
    "TermuxBackend", "UnsupportedOperation", "Builder", "Factory", "KVError",
]
