"""GTK interface for VRAM Manager."""

import html
import sys
import threading
import time
from collections import deque
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Notify", "0.7")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Notify, Pango

from backend import (
    AlertBudget,
    IdleTracker,
    QuitWatch,
    Settings,
    VERSION,
    snapshot,
    terminate,
)

ASSETS = Path(__file__).parent / "assets"


def memory(value):
    return f"{value / 1024:.1f} GiB" if value >= 1024 else f"{value:,.0f} MiB"


class History(Gtk.Image):
    def __init__(self):
        super().__init__()
        self.points = deque(maxlen=360)
        self.set_size_request(-1, 70)
        self.connect("size-allocate", lambda *_: self.redraw())
        self.set_tooltip_text(
            "Total GPU memory in use over the last 10 minutes. Gaps mean missing readings."
        )
        self.last_drawing = None

    def add(self, used, total):
        now = time.monotonic()
        self.points.append((now, used, total))
        while self.points and now - self.points[0][0] > 600:
            self.points.popleft()
        self.redraw()

    def redraw(self):
        width = max(1, self.get_allocated_width())
        height = 70
        drawing = (width, tuple(self.points))
        if drawing == self.last_drawing:
            return
        self.last_drawing = drawing
        now = time.monotonic()
        path = []
        previous = None
        for stamp, used, total in self.points:
            if used is None or not total:
                previous = None
                continue
            x = width * (1 - (now - stamp) / 600)
            y = height - 4 - min(used / total, 1) * (height - 8)
            command = "M" if previous is None or stamp - previous > 15 else "L"
            path.append(f"{command}{x:.2f},{y:.2f}")
            previous = stamp
        grid = "".join(
            f'<path d="M0,{height * f}H{width}"/>' for f in (0.25, 0.5, 0.75)
        )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<g stroke="#8495ad" stroke-opacity="0.2">{grid}</g>'
            f'<path d="{" ".join(path)}" fill="none" stroke="#38a6ec" stroke-width="2"/>'
            "</svg>"
        )
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
        loader.write(svg.encode())
        loader.close()
        self.set_from_pixbuf(loader.get_pixbuf())


class Window(Gtk.ApplicationWindow):
    def __init__(
        self,
        application,
        settings=None,
        provider=snapshot,
        automatic=True,
        focusable=True,
    ):
        super().__init__(application=application, title="VRAM Manager")
        self.set_accept_focus(focusable)
        self.settings = settings or Settings()
        self.provider = provider
        self.processes = {}
        self.latest = None
        self.busy = False
        self.closed = False
        self.dialog_open = False
        self.rendering = False
        self.idle_tracker = IdleTracker()
        self.alert_budget = AlertBudget(self.settings)
        self.snoozed = {}
        self.alerts_paused_until = 0
        self.tray = None
        self.notifications = {}
        self.watches = []
        self.last_success = None
        self.save_timer = None
        self.timer = None
        self.notice_text = self.settings.error
        self.set_default_size(
            self.settings.values["width"], self.settings.values["height"]
        )
        self.set_position(Gtk.WindowPosition.CENTER)
        icon = ASSETS / "vram-manager.svg"
        if icon.exists():
            self.set_icon_from_file(str(icon))
        self.connect("delete-event", self.on_close)
        self.connect("configure-event", self.on_resize)
        Notify.init("VRAM Manager")
        self.icon_cache = {}
        self.desktop_apps = Gio.AppInfo.get_all()
        self.build()
        self.show_all()
        self.minimum.set_text(str(self.settings.values["minimum"]))
        self.idle_minutes.set_text(str(self.settings.values["idle_minutes"]))
        self.alert_vram.set_text(str(self.settings.values["alert_vram"]))
        self.search.grab_focus()
        self.render_notice()
        self.selection_changed()
        if automatic:
            from indicator import Tray

            self.tray = Tray(self)
            self.refresh()
            self.timer = GLib.timeout_add_seconds(2, self.refresh)

    def build(self):
        header = Gtk.HeaderBar(
            title="VRAM Manager", subtitle=f"NVIDIA GPU memory · {VERSION}"
        )
        header.set_show_close_button(True)
        self.set_titlebar(header)
        logo = Gtk.Image.new_from_pixbuf(
            GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(ASSETS / "vram-manager.svg"), 30, 30, True
            )
        )
        logo.set_tooltip_text("VRAM Manager")
        header.pack_start(logo)
        background = Gtk.Button(label="Keep monitoring")
        background.set_tooltip_text(
            "Hide this window and keep alerts running. Open VRAM Manager again to return."
        )
        background.connect("clicked", self.background)
        header.pack_end(background)
        menu_button = Gtk.MenuButton()
        menu_button.add(
            Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
        )
        menu = Gtk.Menu()
        for label, callback in (
            ("Test notification", self.test_notification),
            ("Restore all ignored alerts", self.restore_alerts),
            ("About & limitations", self.about),
            ("Quit VRAM Manager", self.shutdown),
        ):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", callback)
            menu.append(item)
        menu.show_all()
        menu_button.set_popup(menu)
        header.pack_end(menu_button)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=20)
        self.add(box)
        self.summary = Gtk.Label(label="Connecting to NVIDIA GPU…", xalign=0)
        self.summary.get_style_context().add_class("title")
        box.pack_start(self.summary, False, False, 0)
        self.bar = Gtk.ProgressBar(show_text=True)
        box.pack_start(self.bar, False, False, 0)
        self.history = History()
        box.pack_start(self.history, False, False, 0)
        history_label = Gtk.Label(label="Memory history · last 10 minutes", xalign=0)
        history_label.get_style_context().add_class("dim-label")
        box.pack_start(history_label, False, False, 0)
        controls = Gtk.Box(spacing=10)
        controls.pack_start(Gtk.Label(label="Show ≥"), False, False, 0)
        self.minimum = self.spin(0, 1000000, 10, "minimum", 7)
        controls.pack_start(self.minimum, False, False, 0)
        controls.pack_start(Gtk.Label(label="MiB"), False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text="Find an app, script, or PID")
        self.search.connect("search-changed", lambda *_: self.render())
        controls.pack_start(self.search, True, True, 0)
        box.pack_start(controls, False, False, 0)
        alerts = Gtk.Box(spacing=10)
        self.alerts_enabled = Gtk.CheckButton(label="Advisory idle alerts after")
        self.alerts_enabled.set_active(self.settings.values["alerts"])
        self.alerts_enabled.connect("toggled", self.preferences_changed)
        alerts.pack_start(self.alerts_enabled, False, False, 0)
        self.idle_minutes = self.spin(1, 120, 1, "idle_minutes", 3)
        alerts.pack_start(self.idle_minutes, False, False, 0)
        alerts.pack_start(Gtk.Label(label="minutes · holding ≥"), False, False, 0)
        self.alert_vram = self.spin(100, 1000000, 256, "alert_vram", 6)
        alerts.pack_start(self.alert_vram, False, False, 0)
        alerts.pack_start(Gtk.Label(label="MiB"), False, False, 0)
        self.alert_note = Gtk.Label(xalign=0)
        self.alert_note.get_style_context().add_class("dim-label")
        alerts.pack_end(self.alert_note, False, False, 0)
        box.pack_start(alerts, False, False, 0)
        # Stable model rows are updated in place; filters never recreate them.
        self.store = Gtk.ListStore(
            str, float, int, str, str, str, str, GdkPixbuf.Pixbuf, str, float, float
        )
        self.filtered = self.store.filter_new()
        self.filtered.set_visible_func(self.row_visible)
        self.sorted = Gtk.TreeModelSort(model=self.filtered)
        direction = (
            Gtk.SortType.DESCENDING
            if self.settings.values["sort_descending"]
            else Gtk.SortType.ASCENDING
        )
        self.sorted.set_sort_column_id(self.settings.values["sort_column"], direction)
        self.sorted.connect("sort-column-changed", self.sort_changed)
        self.tree = Gtk.TreeView(model=self.sorted)
        self.tree.set_tooltip_column(6)
        for index, label in [
            (0, "Application / process"),
            (1, "VRAM"),
            (10, "CPU"),
            (9, "RAM"),
            (2, "PID"),
            (3, "GPU"),
            (4, "Type"),
            (5, "GPU activity"),
        ]:
            renderer = Gtk.CellRendererText(ypad=10)
            column = Gtk.TreeViewColumn(label)
            if index == 10:
                renderer.set_property("xpad", 12)
                heading = Gtk.Label(label=label, xalign=0)
                heading.set_margin_start(10)
                heading.show()
                column.set_widget(heading)
            if index == 0:
                pix = Gtk.CellRendererPixbuf()
                pix.set_property("stock-size", Gtk.IconSize.LARGE_TOOLBAR)
                column.pack_start(pix, False)
                column.add_attribute(pix, "pixbuf", 7)
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
                column.set_min_width(220)
                column.set_expand(True)
            column.pack_start(renderer, True)
            column.add_attribute(renderer, "text", index)
            if index in (1, 9, 10):
                column.set_cell_data_func(
                    renderer,
                    lambda col, cell, model, row, field: cell.set_property(
                        "text",
                        (
                            "—"
                            if model[row][field] < 0
                            else (
                                f"{model[row][field]:.1f}%"
                                if field == 10
                                else memory(model[row][field])
                            )
                        ),
                    ),
                    index,
                )
            column.set_sort_column_id(index)
            column.set_resizable(True)
            self.tree.append_column(column)
        self.tree.get_selection().connect("changed", self.selection_changed)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_min_content_height(160)
        self.scroll.add(self.tree)
        overlay = Gtk.Overlay()
        overlay.add(self.scroll)
        self.vram_divider = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.vram_divider.set_halign(Gtk.Align.START)
        self.vram_divider.set_valign(Gtk.Align.FILL)
        self.vram_divider.set_size_request(1, -1)
        style = Gtk.CssProvider()
        style.load_from_data(
            b"separator { background-color: rgba(128, 128, 128, 0.28); background-image: none; border: none; min-width: 1px; }"
        )
        self.vram_divider.get_style_context().add_provider(
            style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        overlay.add_overlay(self.vram_divider)
        overlay.set_overlay_pass_through(self.vram_divider, True)
        self.tree.connect("size-allocate", self.position_divider)
        self.scroll.get_hadjustment().connect("value-changed", self.position_divider)
        for column in self.tree.get_columns():
            column.connect("notify::width", self.position_divider)
        box.pack_start(overlay, True, True, 0)
        self.empty = Gtk.Label(label="Reading processes…", xalign=0)
        self.empty.set_no_show_all(True)
        box.pack_start(self.empty, False, False, 0)
        self.details = Gtk.Expander(label="Process details")
        self.detail = Gtk.Label(xalign=0, selectable=True)
        self.detail.set_line_wrap(True)
        self.detail.set_line_wrap_mode(Pango.WrapMode.CHAR)
        self.details.add(self.detail)
        box.pack_start(self.details, False, False, 0)
        actions = Gtk.Box(spacing=8)
        self.ignore = Gtk.Button(label="Ignore idle alerts")
        self.ignore.connect("clicked", self.ignore_selected)
        actions.pack_start(self.ignore, False, False, 0)
        self.snooze = Gtk.Button(label="Snooze 1 hour")
        self.snooze.connect("clicked", self.snooze_selected)
        actions.pack_start(self.snooze, False, False, 0)
        self.force_button = Gtk.Button(label="Force quit…")
        self.force_button.get_style_context().add_class("destructive-action")
        self.force_button.connect("clicked", lambda *_: self.quit_selected(True))
        actions.pack_end(self.force_button, False, False, 0)
        self.quit_button = Gtk.Button(label="Quit app…")
        self.quit_button.connect("clicked", lambda *_: self.quit_selected(False))
        actions.pack_end(self.quit_button, False, False, 0)
        box.pack_start(actions, False, False, 0)
        self.notice = Gtk.Label(xalign=0)
        self.notice.set_line_wrap(True)
        self.notice.set_no_show_all(True)
        box.pack_start(self.notice, False, False, 0)
        self.status = Gtk.Label(label="Reading GPU…", xalign=0)
        self.status.get_style_context().add_class("dim-label")
        self.status.set_line_wrap(True)
        box.pack_start(self.status, False, False, 0)

    def position_divider(self, *_):
        if not hasattr(self, "vram_divider"):
            return
        boundary = sum(column.get_width() for column in self.tree.get_columns()[:2])
        x = int(boundary - self.scroll.get_hadjustment().get_value())
        visible = 0 < x < self.scroll.get_allocated_width()
        self.vram_divider.set_visible(visible)
        if visible:
            self.vram_divider.set_margin_start(x)

    def spin(self, low, high, step, key, width):
        widget = Gtk.SpinButton.new_with_range(low, high, step)
        widget.set_digits(0)
        widget.set_width_chars(width)
        widget.set_value(self.settings.values[key])
        widget.connect("value-changed", self.preferences_changed)
        return widget

    def preferences_changed(self, *_):
        if not hasattr(self, "idle_minutes") or not hasattr(self, "store"):
            return
        self.settings.values.update(
            minimum=self.minimum.get_value_as_int(),
            idle_minutes=self.idle_minutes.get_value_as_int(),
            alerts=self.alerts_enabled.get_active(),
            alert_vram=self.alert_vram.get_value_as_int(),
        )
        self.schedule_save()
        self.render()
        if self.tray:
            self.tray.update()

    def sort_changed(self, *_):
        column, direction = self.sorted.get_sort_column_id()
        if column is not None and column >= 0:
            self.settings.values.update(
                sort_column=column, sort_descending=direction == Gtk.SortType.DESCENDING
            )
            self.schedule_save()

    def on_resize(self, *_):
        if not self.is_maximized():
            width, height = self.get_size()
            self.settings.values.update(width=width, height=height)
            self.schedule_save()
        return False

    def schedule_save(self):
        if self.save_timer:
            GLib.source_remove(self.save_timer)
        self.save_timer = GLib.timeout_add(400, self.save_settings)

    def save_settings(self):
        self.save_timer = None
        if not self.settings.save():
            self.message(self.settings.error)
        return False

    def message(self, text):
        self.notice_text = text
        self.render_notice()

    def render_notice(self):
        self.notice.set_text(self.notice_text)
        self.notice.set_visible(bool(self.notice_text))

    def row_visible(self, model, row, *_):
        query = self.search.get_text().casefold()
        return (
            model[row][1] >= self.minimum.get_value()
            and query in f"{model[row][0]} {model[row][2]} {model[row][6]}".casefold()
        )

    def selected(self):
        model, row = self.tree.get_selection().get_selected()
        return self.processes.get(model[row][8]) if row is not None else None

    def selection_changed(self, *_):
        if self.rendering:
            return
        p = self.selected()
        enabled = bool(
            p
            and p.target_started
            and not p.protected
            and not self.dialog_open
            and self.latest
            and self.last_success is not None
            and time.monotonic() - self.last_success < 8
        )
        self.quit_button.set_sensitive(enabled)
        self.force_button.set_sensitive(enabled)
        self.ignore.set_sensitive(bool(p and not p.protected))
        self.snooze.set_sensitive(bool(p and not p.protected))
        self.ignore.set_label(
            "Enable idle alerts"
            if p and p.app_key in self.settings.values["ignored"]
            else "Ignore idle alerts"
        )
        if p:
            protection = (
                "\nProtected desktop process — quitting is disabled."
                if p.protected
                else ""
            )
            note = (
                "\nUnknown means the driver supplied no reliable activity reading."
                if p.activity is None
                else "\nActivity is sampled; brief work between samples may be missed."
            )
            self.detail.set_text(
                f"{p.name}\nExecutable: {p.executable or 'Unavailable'}\nGPU process: {p.pid} · App quit target: {p.target_pid or 'Unavailable'}{protection}{note}\nRAM is resident system memory (RSS); shared pages may be counted in multiple processes. CPU is measured between readings; 100% is one core and can exceed 100%. Both describe this GPU PID, not its whole app family."
            )
        else:
            self.detail.set_text(
                "Select a process to see its executable and quit target."
            )

    def refresh(self):
        if self.closed:
            return False
        if self.last_success and time.monotonic() - self.last_success > 8:
            self.status.set_text(
                "Readings delayed — waiting for NVIDIA. Quit controls are disabled until fresh data arrives."
            )
            self.quit_button.set_sensitive(False)
            self.force_button.set_sensitive(False)
        if not self.busy:
            self.busy = True
            threading.Thread(target=self.collect, daemon=True).start()
        return True

    def collect(self):
        try:
            data, error = self.provider(), None
        except FileNotFoundError:
            data, error = (
                None,
                "nvidia-smi was not found. Install the NVIDIA driver supplied for your distribution.",
            )
        except Exception as exc:
            data, error = (
                None,
                f"NVIDIA readings unavailable: {exc}. Check that nvidia-smi works in a terminal.",
            )
        GLib.idle_add(self.received, data, error)

    def received(self, data, error):
        if self.closed:
            return False
        self.busy = False
        if error:
            self.latest = None
            self.idle_tracker.states.clear()
            self.idle_tracker.last_sample = None
            self.processes.clear()
            self.store.clear()
            self.history.add(None, None)
            self.summary.set_text("GPU readings unavailable")
            self.bar.set_fraction(0)
            self.bar.set_text("No current data")
            self.status.set_text(error)
            self.empty.set_text("Waiting for GPU readings. Retrying automatically…")
            self.empty.show()
        else:
            self.latest = data
            now = time.monotonic()
            self.last_success = now
            gpus, processes, _ = data
            used, total = self.totals(gpus)
            self.history.add(used, total)
            alerts = self.idle_tracker.update(
                processes,
                now,
                self.idle_minutes.get_value(),
                self.alerts_enabled.get_active()
                and now >= self.alerts_paused_until
                and self.alert_budget.ready(time.time()),
                self.settings.values["ignored"],
                self.snoozed,
                minimum=self.alert_vram.get_value(),
            )
            if alerts:
                self.notify_idle_batch(alerts)
            for watch in self.watches[:]:
                result, done = watch.check(processes, used, now)
                self.message(result)
                if done:
                    self.watches.remove(watch)
            self.render()
        self.selection_changed()
        if self.tray:
            self.tray.update()
        return False

    @staticmethod
    def totals(gpus):
        if not gpus or any(g[1] is None or g[2] is None for g in gpus):
            return None, None
        return sum(g[1] for g in gpus), sum(g[2] for g in gpus)

    def icon_for(self, p):
        key = (p.executable, p.icon)
        if key in self.icon_cache:
            return self.icon_cache[key]
        candidates = []
        executable = Path(p.executable).name.casefold()
        if executable.startswith("python"):
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(ASSETS / "process-python.svg"), 28, 28, True
            )
            self.icon_cache[key] = pixbuf
            return pixbuf
        aliases = {"brave": "brave", "chatgpt": "chatgpt", "code": "visual studio code"}
        for app in self.desktop_apps:
            app_exe = Path(app.get_executable() or "").name.casefold()
            app_name = app.get_display_name().casefold()
            match = app_exe == executable or app_name == p.name.casefold()
            if executable in aliases:
                match = match or aliases[executable] in app_name
            if match and app.get_icon():
                candidates.append(app.get_icon())
        candidates.append(Gio.ThemedIcon.new(p.icon))
        theme = Gtk.IconTheme.get_default()
        for icon in candidates:
            try:
                found = theme.lookup_by_gicon(icon, 28, Gtk.IconLookupFlags.FORCE_SIZE)
                if found:
                    pixbuf = found.load_icon()
                    self.icon_cache[key] = pixbuf
                    return pixbuf
            except GLib.Error:
                continue
        fallback = (
            "process-system"
            if p.protected
            else "process-python" if executable.startswith("python") else "process-app"
        )
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            str(ASSETS / f"{fallback}.svg"), 28, 28, True
        )
        self.icon_cache[key] = pixbuf
        return pixbuf

    def render(self):
        if not self.latest:
            return
        self.rendering = True
        selected = self.selected()
        selected_key = f"{selected.pid}:{selected.started}" if selected else None
        scroll = self.scroll.get_vadjustment().get_value()
        gpus, processes, unknown = self.latest
        self.processes = {f"{p.pid}:{p.started}": p for p in processes}
        row = self.store.get_iter_first()
        while row is not None:
            if self.store[row][8] not in self.processes:
                if not self.store.remove(row):
                    break
            else:
                row = self.store.iter_next(row)
        rows = {r[8]: r.iter for r in self.store}
        for key, p in self.processes.items():
            activity = "Unknown"
            if p.activity is not None:
                activity = (
                    f"{p.activity:.0f}% observed"
                    if p.activity
                    else (
                        f"Quiet · {int(p.idle_seconds // 60)}m"
                        if p.cpu_percent == 0
                        else "0% observed"
                    )
                )
            if p.app_key in self.settings.values["ignored"]:
                activity += " · muted"
            elif self.snoozed.get(p.app_key, 0) > time.monotonic():
                activity += " · snoozed"
            kind = (
                "Protected"
                if p.protected
                else {"G": "Graphics", "C": "Compute", "C+G": "Both"}.get(
                    p.kind, p.kind
                )
            )
            values = [
                p.name,
                p.memory,
                p.pid,
                p.gpu,
                kind,
                activity,
                p.executable,
                self.icon_for(p),
                key,
                p.ram_mib if p.ram_mib is not None else -1,
                p.cpu_percent if p.cpu_percent is not None else -1,
            ]
            if key in rows:
                for index, value in enumerate(values):
                    if self.store[rows[key]][index] != value:
                        self.store.set_value(rows[key], index, value)
            else:
                self.store.append(values)
        self.filtered.refilter()
        if selected_key:
            for r in self.sorted:
                if r[8] == selected_key:
                    self.tree.get_selection().select_iter(r.iter)
                    break
        self.scroll.get_vadjustment().set_value(scroll)
        used, total = self.totals(gpus)
        self.summary.set_text(
            " • ".join(g[0] for g in gpus) or "No NVIDIA GPUs detected"
        )
        self.bar.set_fraction(min(used / total, 1) if total and used is not None else 0)
        self.bar.set_text(
            f"{memory(used)} used of {memory(total)} · {memory(max(total - used, 0))} free"
            if total and used is not None
            else "Total memory reading unavailable"
        )
        count = len(self.sorted)
        self.empty.set_text(
            "No processes match your filter."
            if gpus
            else "No NVIDIA GPU detected. This beta supports Linux with NVIDIA GPUs."
        )
        self.empty.set_visible(count == 0)
        unavailable = sum(p.activity is None for p in processes if p.memory >= 100)
        self.alert_note.set_text(
            f"{unavailable} activity readings unknown"
            if unavailable
            else "Unknown readings never trigger alerts"
        )
        self.alert_note.set_tooltip_text(
            "Idle alerts are advisory, not proof that an app has no useful work. Desktop processes are excluded."
        )
        self.status.set_text(
            f"{count} processes · Live, every 2 seconds · Updated {time.strftime('%H:%M:%S')}"
            + (f" · {unknown} allocations unavailable" if unknown else "")
        )
        self.rendering = False
        self.selection_changed()

    def notification(self, title, body, key, actions=()):
        notification = Notify.Notification.new(title, html.escape(body), "vram-manager")
        notification.set_hint("desktop-entry", GLib.Variant("s", "vram-manager"))
        notification.set_hint("transient", GLib.Variant("b", True))
        notification.set_timeout(Notify.EXPIRES_DEFAULT)
        for action, label, callback in actions:
            notification.add_action(
                action, label, lambda n, a, data=None, cb=callback: cb()
            )
        notification.connect("closed", lambda *_: self.notifications.pop(key, None))
        self.notifications[key] = notification
        try:
            notification.show()
            return True
        except GLib.Error as exc:
            self.notifications.pop(key, None)
            self.message(f"Desktop notification could not be delivered: {exc.message}")
            return False

    def desktop_allows_alerts(self):
        """No automatic banners while locked, in DND, or state is unknown."""
        try:
            source = Gio.SettingsSchemaSource.get_default()
            schema = (
                source.lookup("org.gnome.desktop.notifications", True)
                if source
                else None
            )
            if schema is None:
                return False
            preferences = Gio.Settings.new_full(schema, None, None)
            if not preferences.get_boolean("show-banners"):
                return False
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            result = bus.call_sync(
                "org.gnome.ScreenSaver",
                "/org/gnome/ScreenSaver",
                "org.gnome.ScreenSaver",
                "GetActive",
                None,
                GLib.VariantType.new("(b)"),
                Gio.DBusCallFlags.NONE,
                250,
                None,
            )
            return result.unpack()[0] is False
        except GLib.Error:
            return False

    def notify_idle_batch(self, processes):
        if not self.alert_budget.claim(time.time(), self.desktop_allows_alerts()):
            return False
        ordered = sorted(processes, key=lambda p: p.memory, reverse=True)
        lead = ordered[0]
        if len(ordered) == 1:
            body = (
                f"{lead.name} holds {memory(lead.memory)} with no CPU or GPU "
                f"activity observed for {lead.idle_seconds / 60:.0f} minutes."
            )
        else:
            body = (
                f"{len(ordered)} processes hold {memory(sum(p.memory for p in ordered))} "
                f"with no CPU or GPU activity observed for at least "
                f"{min(p.idle_seconds for p in ordered) / 60:.0f} minutes. "
                f"Largest: {lead.name}."
            )
        return self.notification(
            "VRAM may be sitting idle",
            body
            + " They may be waiting or keeping models loaded. Nothing was stopped.",
            "idle-summary",
            [("default", "Review", self.present)],
        )

    def review(self, p):
        self.show_all()
        self.render_notice()
        self.minimum.set_value(0)
        self.search.set_text(str(p.pid))
        self.render()
        for row in self.sorted:
            if row[8] == f"{p.pid}:{p.started}":
                self.tree.get_selection().select_iter(row.iter)
                self.tree.scroll_to_cell(row.path, None, False, 0, 0)
                break
        else:
            self.message(
                "That process has exited or changed. Clear the search to see current processes."
            )
        self.present()

    def snooze_process(self, p):
        self.snoozed[p.app_key] = time.monotonic() + 3600
        self.idle_tracker.states.pop(p.key, None)
        self.message(f"Idle alerts snoozed for {p.name} for one hour.")
        self.render()

    def ignore_process(self, p):
        ignored = self.settings.values["ignored"]
        if p.app_key not in ignored:
            ignored.append(p.app_key)
        self.schedule_save()
        self.message(
            f"Idle alerts ignored for {p.name}. You can restore them from the menu."
        )
        self.render()

    def ignore_selected(self, *_):
        p = self.selected()
        if not p:
            return
        if p.app_key in self.settings.values["ignored"]:
            self.settings.values["ignored"].remove(p.app_key)
            self.idle_tracker.states.pop(p.key, None)
            self.schedule_save()
            self.message(f"Idle alerts enabled for {p.name}.")
            self.render()
        else:
            self.ignore_process(p)

    def snooze_selected(self, *_):
        p = self.selected()
        if p:
            self.snooze_process(p)

    def restore_alerts(self, *_):
        self.settings.values["ignored"] = []
        self.snoozed.clear()
        self.idle_tracker.states.clear()
        self.schedule_save()
        self.message("All ignored and snoozed alerts restored.")
        self.render()

    def test_notification(self, *_):
        delivered = self.notification(
            "VRAM Manager notifications work",
            "This is a test. Review returns to the app.",
            "test",
            [("default", "Review", self.present)],
        )
        if delivered:
            self.message(
                "Test notification sent. Desktop Do Not Disturb settings may hide it."
            )

    def background(self, *_):
        self.save_settings()
        if self.tray and self.tray.connected:
            self.hide()
            return
        self.notification(
            "VRAM Manager is monitoring",
            "Idle alerts remain active. Open VRAM Manager from Applications to return.",
            "background",
            [("default", "Open", self.present)],
        )
        self.hide()

    def on_close(self, *_):
        if self.tray and self.tray.connected:
            self.hide()
        else:
            self.shutdown()
        return True

    def shutdown(self, *_):
        if self.closed:
            return
        self.closed = True
        if self.tray:
            self.tray.close()
        if self.timer:
            GLib.source_remove(self.timer)
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = None
        self.save_settings()
        for notification in list(self.notifications.values()):
            try:
                notification.close()
            except GLib.Error:
                pass
        self.destroy()
        self.get_application().quit() if self.get_application() else None

    def about(self, *_):
        dialog = Gtk.AboutDialog(
            transient_for=self,
            modal=True,
            program_name="VRAM Manager",
            version=VERSION,
            comments="See what holds your GPU memory. Quit apps deliberately.\n\nLinux / NVIDIA beta. Activity is sampled; unknown readings never count as idle. Desktop processes are protected.\n\nClose returns to the top bar when available. Use Quit VRAM Manager to stop monitoring. No telemetry or automatic process killing.",
        )
        dialog.run()
        dialog.destroy()

    def quit_selected(self, force):
        p = self.selected()
        if not p or p.protected or self.dialog_open:
            return
        self.dialog_open = True
        self.selection_changed()
        verb = "Force quit" if force else "Quit"
        body = f"{p.name} holds {memory(p.memory)}. This {'forcibly stops' if force else 'requests termination of'} PID {p.target_pid}. Unsaved work may be lost."
        if p.target_pid != p.pid:
            body += "\n\nThis closes the whole app, including its windows, rather than only restarting its GPU helper."
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"{verb} {p.name}?",
        )
        dialog.format_secondary_text(body)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button(verb, Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            try:
                used = self.totals(self.latest[0])[0] if self.latest else None
                known_keys = {p.key for p in self.processes.values()}
                terminate(p, force)
                self.watches.append(QuitWatch(p, used, time.monotonic(), known_keys))
                self.message(f"{verb} requested for {p.name}. Watching for exit…")
            except (OSError, RuntimeError) as exc:
                self.message(f"Could not quit {p.name}: {exc}")
        self.dialog_open = False
        self.selection_changed()


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.vrammanager.VramManager",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = Window(self)
        else:
            if self.window.tray:
                self.window.tray.hide_on_connect = False
            self.window.present()


def run_gui():
    GLib.set_application_name("VRAM Manager")
    GLib.set_prgname("vram-manager")
    Gdk.set_program_class("VRAM Manager")
    return Application().run(sys.argv)
