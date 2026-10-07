#!/usr/bin/python3
"""VRAM Manager entry point."""

import sys
from backend import *  # Preserve the prototype's import API for local scripts.

if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"VRAM Manager {VERSION}")
    else:
        from ui import run_gui

        raise SystemExit(run_gui())
