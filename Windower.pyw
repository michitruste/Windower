# Double-click this file to start Windower without a console window.
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "main.py"), run_name="__main__")
