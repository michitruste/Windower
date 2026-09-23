"""Picks the real Win32 backend on Windows, the simulated one elsewhere / in demo mode."""
from __future__ import annotations

import sys


def load(demo: bool = False):
    if demo or sys.platform != "win32":
        from . import fakewin
        return fakewin
    from . import win32
    return win32
