"""JSON persistence for custom layouts, workspaces and settings."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .model import Layout


def config_dir() -> Path:
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / "Windower"
    else:
        base = Path.home() / ".config" / "windower"
    override = os.environ.get("WINDOWER_CONFIG_DIR")
    if override:
        base = Path(override)
    base.mkdir(parents=True, exist_ok=True)
    return base


class Store:
    """
    config.json = {
      "layouts":    [ {name, zones:[{x,y,w,h}]} ],
      "workspaces": { name: {screens, layout, monitor, slots:[signature|null]} },
      "settings":   { ... }
    }
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "config.json")
        self.layouts: list[Layout] = []
        self.workspaces: dict[str, dict] = {}
        self.settings: dict = {}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.layouts = []
        for d in data.get("layouts", []):
            try:
                self.layouts.append(Layout.from_dict(d))
            except (KeyError, TypeError):
                pass
        self.workspaces = dict(data.get("workspaces", {}))
        self.settings = dict(data.get("settings", {}))

    def save(self) -> None:
        data = {
            "layouts": [lay.to_dict() for lay in self.layouts],
            "workspaces": self.workspaces,
            "settings": self.settings,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    # layouts -------------------------------------------------------------
    def put_layout(self, layout: Layout) -> None:
        self.layouts = [lay for lay in self.layouts if lay.name != layout.name] + [layout]
        self.save()

    def delete_layout(self, name: str) -> None:
        self.layouts = [lay for lay in self.layouts if lay.name != name]
        self.save()

    # workspaces ----------------------------------------------------------
    def put_workspace(self, name: str, data: dict) -> None:
        self.workspaces[name] = data
        self.save()

    def delete_workspace(self, name: str) -> None:
        self.workspaces.pop(name, None)
        self.save()
