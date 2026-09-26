"""
Live previews of the assigned windows inside the zones of the preview canvas.

The backend's Thumbnail is drawn by the Windows compositor (DWM) on top of our
panel, so it is always live and costs Windower nothing. It sits *above* the Tk
canvas, which is why the app leaves a header strip and a margin around each
preview for the zone number, outlines and divider grips.
"""
from __future__ import annotations

import tkinter as tk

from .model import Rect, fit_aspect


class LiveThumbnails:
    def __init__(self, root: tk.Misc, backend):
        self.root = root
        self.be = backend
        self.supported = bool(getattr(backend, "HAS_THUMBNAILS", False))
        self._thumbs: dict[int, object] = {}
        self._sizes: dict[int, tuple[int, int]] = {}
        self._failed: set[int] = set()   # windows DWM refused (don't retry on every redraw)

    def sync(self, boxes: dict[int, tuple[Rect, int]]) -> set[int]:
        """Show a thumbnail of each window hwnd -> (box in screen coords, opacity),
        remove every other one. Returns the hwnds that are really showing."""
        for hwnd in list(self._thumbs):
            if hwnd not in boxes:
                self._drop(hwnd)
        self._failed &= set(boxes)
        shown: set[int] = set()
        if not self.supported:
            return shown
        dest = self.root.winfo_id()
        for hwnd, (box, opacity) in boxes.items():
            t = self._thumbs.get(hwnd)
            if t is None:
                if hwnd in self._failed:
                    continue
                try:
                    t = self._thumbs[hwnd] = self.be.Thumbnail(dest, hwnd)
                except OSError:
                    self._failed.add(hwnd)
                    continue
            size = t.source_size()
            if not size:
                t.hide()
                continue
            self._sizes[hwnd] = size
            t.show(fit_aspect(box, *size), opacity)
            shown.add(hwnd)
        return shown

    def resized(self) -> bool:
        """True if a source window changed shape since the last sync (previews need refitting)."""
        return any(t.source_size() != self._sizes.get(h) for h, t in self._thumbs.items())

    def clear(self) -> None:
        for hwnd in list(self._thumbs):
            self._drop(hwnd)

    def _drop(self, hwnd: int) -> None:
        t = self._thumbs.pop(hwnd)
        self._sizes.pop(hwnd, None)
        try:
            t.close()
        except OSError:
            pass
