#!/usr/bin/python3
"""Create the public screenshot using labeled illustrative data, never host processes."""

import math
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import Process, Settings
from ui import Gdk, Gio, GLib, Gtk, Window

app = Gtk.Application(
    application_id="io.github.vrammanager.Screenshot",
    flags=Gio.ApplicationFlags.NON_UNIQUE,
)
app.register(None)
with tempfile.TemporaryDirectory() as folder:
    settings = Settings(Path(folder) / "settings.json")
    settings.values.update(width=1140, height=750, alerts=False)
    window = Window(app, settings, automatic=False, focusable=False)
    window.get_titlebar().set_subtitle("Illustrative demo data · 0.1.0-beta.1")
    gpu = "GeForce RTX 5070"
    processes = [
        Process(
            3101,
            "Python · image-generation / server.py",
            4608,
            gpu,
            "C",
            executable="/usr/bin/python3",
            icon="applications-science",
            started="a",
            activity=72,
        ),
        Process(
            3102,
            "Blender",
            1536,
            gpu,
            "G",
            executable="/usr/bin/blender",
            icon="blender",
            started="b",
            activity=0,
        ),
        Process(
            3103,
            "Brave Browser",
            480,
            gpu,
            "G",
            executable="/usr/bin/brave",
            icon="brave-browser",
            started="c",
            activity=3,
        ),
        Process(
            3104,
            "GNOME Desktop",
            220,
            gpu,
            "G",
            executable="/usr/bin/gnome-shell",
            icon="video-display",
            started="d",
            activity=1,
            protected=True,
        ),
    ]
    for index, process in enumerate(processes):
        process.ram_mib = [6100, 2200, 380, 420][index]
        process.cpu_percent = [142.5, 0, 2.4, 1.1][index]
    window.received(([(f"NVIDIA {gpu}", 7200, 12227)], processes, 0), None)
    window.history.points.clear()
    now = time.monotonic()
    for i in range(301):
        usage = 3200 if i < 80 else 7100 if i < 220 else 6800
        window.history.points.append(
            (now - 600 + i * 2, usage + 150 * math.sin(i / 12), 12227)
        )
    window.history.redraw()
    window.status.set_text(
        "4 processes · Live updates every 2 seconds · Illustrative demo data"
    )
    window.show()

    def capture():
        pix = Gdk.pixbuf_get_from_window(
            window.get_window(),
            0,
            0,
            window.get_allocated_width(),
            window.get_allocated_height(),
        )
        pix.savev(str(ROOT / "docs/screenshot.png"), "png", [], [])
        window.shutdown()
        Gtk.main_quit()
        return False

    GLib.timeout_add(700, capture)
    Gtk.main()
