"""Native Ubuntu/KDE status indicator, with an ordinary-window fallback."""

import time
from pathlib import Path

import gi
from gi.repository import Gio, GLib, Gtk
import autostart


class Tray:
    def __init__(self, window):
        self.window = window
        self.connected = False
        self.hide_on_connect = True
        self.indicator = None
        self.api = None
        try:
            # Optional per-user bindings; Debian installations use system typelibs.
            local = Path.home() / ".local/lib/girepository-1.0"
            if local.is_dir():
                gi.require_version("GIRepository", "2.0")
                from gi.repository import GIRepository

                GIRepository.Repository.prepend_search_path(str(local))
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3

            self.api = AyatanaAppIndicator3
            watcher = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.DO_NOT_AUTO_START,
                None,
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                None,
            )
            host = watcher.get_cached_property("IsStatusNotifierHostRegistered")
            if host is None or not host.unpack():
                raise RuntimeError("No top-bar indicator host is available")
            self.indicator = self.api.Indicator.new_with_path(
                "vram-manager",
                "vram-manager",
                self.api.IndicatorCategory.HARDWARE,
                str(Path(__file__).parent / "assets"),
            )
            self.indicator.set_title("VRAM Manager")
            menu = Gtk.Menu()
            self.summary = Gtk.MenuItem(label="Reading GPU memory…")
            self.summary.set_sensitive(False)
            menu.append(self.summary)
            self.add(menu, "Open VRAM Manager", self.open)
            menu.append(Gtk.SeparatorMenuItem())
            self.alerts = Gtk.CheckMenuItem(label="Enable advisory idle alerts")
            self.alerts.set_active(window.alerts_enabled.get_active())
            self.alerts.connect(
                "toggled",
                lambda item: window.alerts_enabled.set_active(item.get_active()),
            )
            menu.append(self.alerts)
            self.add(menu, "Pause all alerts for 1 hour", self.pause)
            self.add(menu, "Resume alerts", self.resume)
            startup = Gtk.CheckMenuItem(label="Start at login")
            startup.set_active(autostart.enabled())
            startup.connect("toggled", self.startup_changed)
            menu.append(startup)
            menu.append(Gtk.SeparatorMenuItem())
            self.add(menu, "Quit VRAM Manager", window.shutdown)
            menu.show_all()
            self.indicator.set_menu(menu)
            self.indicator.connect("connection-changed", self.connection_changed)
            self.indicator.set_status(self.api.IndicatorStatus.ACTIVE)
            window.hide()
            GLib.timeout_add_seconds(3, self.check_connection)
        except (ValueError, ImportError, GLib.Error, RuntimeError) as exc:
            window.message(
                f"Top-bar indicator unavailable: {exc}. The window remains available."
            )
            window.present()

    @staticmethod
    def add(menu, title, callback):
        item = Gtk.MenuItem(label=title)
        item.connect("activate", lambda *_: callback())
        menu.append(item)

    def connection_changed(self, indicator, connected):
        self.connected = connected
        if connected and self.hide_on_connect:
            self.window.hide()
            self.hide_on_connect = False
        elif not connected and not self.window.closed:
            self.window.present()
        self.update()

    def check_connection(self):
        if not self.connected and not self.window.closed:
            self.window.present()
            self.window.message(
                "Top-bar connection unavailable. Monitoring continues in this window."
            )
        return False

    def open(self):
        self.hide_on_connect = False
        self.window.present()

    def pause(self):
        self.window.alerts_paused_until = time.monotonic() + 3600
        self.window.message("All idle alerts paused for one hour.")
        self.update()

    def resume(self):
        self.window.alerts_paused_until = 0
        self.window.message(
            "Alert pause cleared; your enabled/disabled preference still applies."
        )
        self.update()

    def update(self):
        if self.indicator is None:
            return
        self.alerts.set_active(self.window.alerts_enabled.get_active())
        latest = self.window.latest
        used, total = self.window.totals(latest[0]) if latest else (None, None)
        if used is None or total is None:
            self.indicator.set_label("VRAM —", "VRAM 99.9G")
            self.summary.set_label("GPU readings unavailable")
        else:
            self.indicator.set_label(f"VRAM {used / 1024:.1f}G", "VRAM 99.9G")
            suffix = (
                " · alerts paused"
                if time.monotonic() < self.window.alerts_paused_until
                else ""
            )
            self.summary.set_label(
                f"{used / 1024:.1f} / {total / 1024:.1f} GiB used{suffix}"
            )

    def startup_changed(self, item):
        try:
            autostart.set_enabled(item.get_active())
        except OSError as exc:
            self.window.message(f"Could not change login startup: {exc}")
            self.window.present()

    def close(self):
        if self.indicator:
            self.indicator.set_status(self.api.IndicatorStatus.PASSIVE)
