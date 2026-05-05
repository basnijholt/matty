"""Compatibility interface for the historical single-module Matty API."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

from . import cli as _cli


class _MattyModule(ModuleType):
    def __getattr__(self, name: str) -> Any:
        return getattr(_cli, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if hasattr(_cli, name):
            setattr(_cli, name, value)
        super().__setattr__(name, value)


for _name in dir(_cli):
    if not (_name.startswith("__") and _name.endswith("__")):
        globals()[_name] = getattr(_cli, _name)

__all__ = [
    _name
    for _name in dir(_cli)
    if not (_name.startswith("__") and _name.endswith("__"))
]

sys.modules[__name__].__class__ = _MattyModule
