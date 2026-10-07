#!/usr/bin/python3
"""Remove the per-user installation; retain the user's settings."""

import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import autostart


def main():
    prefix = Path.home() / ".local"
    for relative in (
        "bin/vram-manager",
        "share/applications/vram-manager.desktop",
        "share/applications/io.github.Elhelali.VramManager.desktop",
        "share/icons/hicolor/scalable/apps/vram-manager.svg",
    ):
        (prefix / relative).unlink(missing_ok=True)
    autostart.path().unlink(missing_ok=True)
    shutil.rmtree(prefix / "share/vram-manager", ignore_errors=True)
    print("Per-user installation and login entry removed. Settings retained.")


if __name__ == "__main__":
    main()
