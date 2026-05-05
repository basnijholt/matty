"""Compatibility alias for the packaged TUI module."""

from __future__ import annotations

import sys
from importlib import import_module

_tui = import_module("matty.tui")

sys.modules[__name__] = _tui
