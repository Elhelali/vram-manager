#!/usr/bin/python3
"""Create the public screenshot using labeled illustrative data, never host processes."""

import math
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

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
    settings.values.update(width=1180, height=790, alerts=True)
    window = Window(app, settings, automatic=False, focusable=False)
    window.get_titlebar().set_subtitle("Demo data · example notification preview")
    gpu = "GeForce RTX 5070"
    processes = [
        Process(
            3101,
            "Ollama",
            8396.8,
            gpu,
            "C",
            executable="/usr/bin/ollama",
            icon="applications-science",
            started="a",
            activity=0,
        ),
        Process(
            3102,
            "ComfyUI",
            1024,
            gpu,
            "C",
            executable="/usr/bin/python3",
            icon="applications-science",
            started="b",
            activity=63,
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
        process.target_pid = process.pid
        process.target_started = process.started
        process.ram_mib = [1300, 2200, 380, 420][index]
        process.cpu_percent = [0, 142.5, 2.4, 1.1][index]

    def preview_notification(title, body, key, actions=()):
        # Render the actual alert text locally, without sending desktop notifications.
        frame = Gtk.Frame(label="Example desktop notification")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        heading = Gtk.Label(label=title, xalign=0)
        heading.get_style_context().add_class("title")
        text = Gtk.Label(label=body, xalign=0)
        text.set_line_wrap(True)
        content.pack_start(heading, False, False, 0)
        content.pack_start(text, False, False, 0)
        frame.add(content)
        box = window.get_child()
        box.pack_start(frame, False, False, 0)
        box.reorder_child(frame, 0)
        frame.show_all()
        return True

    now = time.monotonic()
    window.idle_tracker.states[processes[0].key] = (now - 42 * 60, False)
    with patch.object(
        window, "notification", side_effect=preview_notification
    ), patch.object(window, "desktop_allows_alerts", return_value=True):
        window.received(([(f"NVIDIA {gpu}", 10500, 12227)], processes, 0), None)
    window.tree.get_selection().select_path(Gtk.TreePath.new_first())
    window.minimum.select_region(0, 0)
    window.idle_minutes.select_region(0, 0)
    window.alert_vram.select_region(0, 0)
    window.set_focus(None)
    window.history.points.clear()
    now = time.monotonic()
    for i in range(301):
        usage = 10350
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
