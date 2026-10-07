#!/usr/bin/python3
"""Deterministic desktop checks; no real GPU or process termination required."""

import tempfile
import sys
import time
from pathlib import Path
from unittest.mock import patch

# In clean package tests, exercise the installed files rather than source copies.
installed = Path("/usr/share/vram-manager")
if installed.is_dir():
    sys.path.insert(0, str(installed))

from backend import Process, Settings
from ui import Gio, GLib, Gtk, Window


def main():
    application = Gtk.Application(
        application_id="io.github.vrammanager.Checks",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    application.register(None)
    with tempfile.TemporaryDirectory() as folder:
        settings = Settings(Path(folder) / "settings.json")
        window = Window(application, settings, automatic=False, focusable=False)
        try:
            a = Process(
                123,
                "Example AI",
                2048,
                "Example GPU",
                "C",
                started="a",
                target_pid=123,
                target_started="a",
                executable="/example/ai",
                activity=0,
            )
            b = Process(
                124,
                "Desktop",
                256,
                "Example GPU",
                "G",
                started="b",
                target_pid=124,
                target_started="b",
                executable="/example/desktop",
                protected=True,
            )
            a.ram_mib = 512
            a.cpu_percent = 12.5
            data = ([("Example GPU", 3000, 8000)], [a, b], 0)
            window.received(data, None)
            assert len(window.sorted) == 2
            assert window.sorted[0][9] == 512
            assert window.sorted[0][10] == 12.5
            for activity, cpu, expected in (
                (0, 1.2, "Quiet · 0m"),
                (None, 1.2, "Unknown"),
                (0, 5.0, "0% observed"),
                (2, 1.2, "2% observed"),
            ):
                a.activity = activity
                a.cpu_percent = cpu
                window.render()
                assert window.sorted[0][5] == expected
            a.activity = 0
            a.cpu_percent = 12.5
            window.render()
            window.tree.get_selection().select_iter(window.sorted[0].iter)
            assert window.quit_button.get_sensitive()
            reference = Gtk.TreeRowReference.new(window.store, window.store[0].path)
            a.memory = 1800
            window.received(data, None)
            assert reference.valid()
            assert window.selected().pid == 123
            window.ignore_selected()
            assert a.app_key in settings.values["ignored"]
            window.ignore_selected()
            assert a.app_key not in settings.values["ignored"]
            window.snooze_selected()
            assert window.snoozed[a.app_key] > time.monotonic()
            window.restore_alerts()
            assert not window.snoozed
            for row in window.sorted:
                if row[2] == 124:
                    window.tree.get_selection().select_iter(row.iter)
            assert not window.quit_button.get_sensitive()
            window.search.set_text("not-found")
            window.render()
            assert len(window.sorted) == 0
            window.search.set_text("")
            window.render()
            # Capture libnotify's real callback shape without posting desktop notifications.
            with patch("ui.Gio.SettingsSchemaSource.get_default"), patch(
                "ui.Gio.Settings.new_full"
            ) as preferences, patch("ui.Gio.bus_get_sync") as session_bus:
                preferences.return_value.get_boolean.return_value = False
                assert not window.desktop_allows_alerts()
                session_bus.assert_not_called()
                preferences.return_value.get_boolean.return_value = True
                session_bus.return_value.call_sync.return_value = GLib.Variant(
                    "(b)", (True,)
                )
                assert not window.desktop_allows_alerts()
                session_bus.return_value.call_sync.return_value = GLib.Variant(
                    "(b)", (False,)
                )
                assert window.desktop_allows_alerts()
                session_bus.return_value.call_sync.side_effect = GLib.Error(
                    "Unavailable"
                )
                assert not window.desktop_allows_alerts()

            callbacks = {}

            class Notification:
                def set_hint(self, *args):
                    pass

                def set_timeout(self, *args):
                    pass

                def connect(self, *args):
                    pass

                def show(self):
                    return True

                def close(self):
                    pass

                def add_action(self, action, label, callback):
                    callbacks[action] = callback

            with patch("ui.Notify.Notification.new", return_value=Notification()):
                with patch.object(window, "desktop_allows_alerts", return_value=False):
                    assert not window.notify_idle_batch([a] * 7)
                with patch.object(window, "desktop_allows_alerts", return_value=True):
                    with patch.object(
                        window, "notification", return_value=True
                    ) as send:
                        assert window.notify_idle_batch([a] * 7)
                        assert send.call_count == 1
                        assert "7 processes" in send.call_args.args[1]
                        assert not window.notify_idle_batch([a])
                        assert send.call_count == 1
                window.snooze_process(a)
                assert a.app_key in window.snoozed
                window.ignore_process(a)
                assert a.app_key in settings.values["ignored"]
                window.review(a)
                assert window.selected().pid == 123
                window.background()
                assert not window.get_visible()
                window.present()
                assert window.get_visible()
            window.minimum.set_value(512)
            window.idle_minutes.set_value(6)
            window.alert_vram.set_value(2048)
            window.save_settings()
            assert Settings(settings.path).values["minimum"] == 512
            assert Settings(settings.path).values["idle_minutes"] == 6
            assert Settings(settings.path).values["alert_vram"] == 2048
            window.received(None, "Driver unavailable")
            assert not window.quit_button.get_sensitive()
            assert not len(window.store)
            window.received(data, None)
            assert window.latest is not None
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            print(
                "GUI fixtures: stable rows, selection, filters, locks, notification actions, background, settings, error recovery PASS"
            )
        finally:
            window.shutdown()


if __name__ == "__main__":
    main()
