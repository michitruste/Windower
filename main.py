"""
Windower - arrange the windows of different programs side by side, like
split-screen on a phone, while every app keeps running live.

    python main.py          # normal mode (Windows)
    python main.py --demo   # simulated windows, to try the UI anywhere
    pythonw main.py         # no console window (or double-click Windower.pyw)
"""
from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from windower_app import backend  # noqa: E402
from windower_app.app import WindowerApp  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Windower - split-screen window organizer")
    ap.add_argument("--demo", action="store_true", help="use simulated windows (no real windows are moved)")
    args = ap.parse_args()

    be = backend.load(demo=args.demo)
    be.enable_dpi_awareness()  # must happen before Tk creates any window

    root = tk.Tk()
    WindowerApp(root, be)
    root.mainloop()


if __name__ == "__main__":
    main()
