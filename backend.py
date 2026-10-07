#!/usr/bin/python3
"""Native NVIDIA VRAM process manager. No third-party Python packages required."""

import os
import json
import math
import tempfile
import signal
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Process:
    pid: int
    name: str
    memory: float
    gpu: str
    kind: str
    started: str = ""
    target_pid: int = 0
    target_started: str = ""
    executable: str = ""
    activity: float | None = None
    idle_seconds: float = 0
    icon: str = "application-x-executable"
    protected: bool = False
    gpu_indices: tuple = ()
    ram_mib: float | None = None
    cpu_percent: float | None = None

    @property
    def key(self):
        return (self.pid, self.started)

    @property
    def app_key(self):
        return f"{self.executable}|{self.name}"


def identity(pid):
    """Read start time to distinguish reused PIDs."""
    stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return stat[19], int(stat[1])


def metadata(pid):
    args = (
        Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0")
    )
    executable = os.readlink(f"/proc/{pid}/exe").removesuffix(" (deleted)")
    return [arg for arg in args if arg], executable


def decorate(process):
    try:
        process.started, parent = identity(process.pid)
        args, executable = metadata(process.pid)
        process.executable = executable
        name = Path(executable).name
        names = {
            "brave": "Brave Browser",
            "code": "Visual Studio Code",
            "ChatGPT": "Codex / ChatGPT",
            "gnome-shell": "GNOME Desktop",
            "Xorg": "Xorg Display Server",
            "chrome": "Chromium",
            "signal-desktop": "Signal",
            "claude-desktop": "Claude",
        }
        names.update(
            {
                "firefox": "Firefox",
                "nautilus": "Files",
                "tonet": "Tonet",
                "gnome-software": "Software",
                "obsidian": "Obsidian",
            }
        )
        process.name = names.get(name, name)
        process.icon = {
            "brave": "brave-browser",
            "code": "visual-studio-code",
            "firefox": "firefox",
            "nautilus": "org.gnome.Nautilus",
            "gnome-shell": "preferences-desktop",
            "Xorg": "video-display",
            "chrome": "chromium",
            "obsidian": "obsidian",
            "signal-desktop": "signal-desktop",
            "ChatGPT": "chatgpt",
        }.get(name, name)
        process.protected = name.lower() in PROTECTED
        if name.startswith("python"):
            process.icon = "applications-science"
        if name.startswith("python"):
            if "-m" in args and args.index("-m") + 1 < len(args):
                process.name = f"Python · {args[args.index('-m') + 1]}"
            else:
                script = next((Path(a).name for a in args[1:] if a.endswith(".py")), "")
                project = ""
                try:
                    project = Path(os.readlink(f"/proc/{process.pid}/cwd")).name
                except OSError:
                    pass
                label = " / ".join(part for part in (project, script) if part)
                process.name = f"Python · {label}" if label else "Python"
        process.target_pid = process.pid
        process.target_started = process.started
        # Quitting a browser's GPU helper alone causes it to respawn. Resolve
        # the same-executable app parent, never unrelated shells or launchers.
        if "--type=gpu-process" in args:
            for _ in range(16):
                if parent <= 1:
                    break
                parent_args, parent_exe = metadata(parent)
                if parent_exe != executable:
                    break
                started, grandparent = identity(parent)
                process.target_pid = parent
                process.target_started = started
                if not any(a.startswith("--type=") for a in parent_args):
                    break
                parent = grandparent
    except (OSError, ValueError, IndexError):
        pass
    # Desktop components stay visible, but cannot be terminated by this app.
    process.protected = (
        process.protected or Path(process.executable).name.lower() in PROTECTED
    )
    return process


def amount(value):
    try:
        number = float(value.split()[0])
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, AttributeError, IndexError):
        return None


def parse_snapshot(xml):
    root = ET.fromstring(xml)
    gpus, processes = [], {}
    unknown = 0
    for index, gpu in enumerate(root.findall("gpu")):
        label = gpu.findtext("product_name", "NVIDIA GPU").removeprefix("NVIDIA ")
        if len(root.findall("gpu")) > 1:
            label += f" ({gpu.get('id', str(index))})"
        gpus.append(
            (
                gpu.findtext("product_name", "NVIDIA GPU"),
                amount(gpu.findtext("fb_memory_usage/used")),
                amount(gpu.findtext("fb_memory_usage/total")),
            )
        )
        for item in gpu.findall("processes/process_info"):
            memory = amount(item.findtext("used_memory"))
            if memory is None:
                unknown += 1
                continue
            try:
                pid = int(item.findtext("pid"))
            except (TypeError, ValueError):
                continue
            if pid in processes:
                processes[pid].memory += memory
                processes[pid].gpu_indices += (index,)
                if item.findtext("type", "?") != processes[pid].kind:
                    processes[pid].kind = "C+G"
                if label not in processes[pid].gpu.split(", "):
                    processes[pid].gpu += f", {label}"
            else:
                processes[pid] = Process(
                    pid,
                    item.findtext("process_name", "Unknown"),
                    memory,
                    label,
                    item.findtext("type", "?"),
                    gpu_indices=(index,),
                )
    return gpus, list(processes.values()), unknown


def parse_activity(output):
    """Return per-device readings; missing samples are not proof of idleness."""
    readings = {}
    columns = ["gpu", "pid", "type", "sm", "mem", "enc", "dec", "jpg", "ofa", "command"]
    for line in output.splitlines():
        parts = line.split()
        if parts[:2] == ["#", "gpu"]:
            columns = parts[1:]
            continue
        if not parts or not parts[0].isdigit() or len(parts) < 7:
            continue
        try:
            key = (int(parts[0]), int(parts[1]))
            fields = dict(zip(columns, parts))
            values = [
                int(fields[c])
                for c in ("sm", "mem", "enc", "dec", "jpg", "ofa")
                if fields.get(c, "-").isdigit()
            ]
            if any(values):
                value = max(values)
            elif fields.get("sm", "-").isdigit() and fields.get("mem", "-").isdigit():
                value = 0
            else:
                value = None
            readings[key] = value
        except ValueError:
            continue
    return readings


def process_activity(process, readings):
    values = [readings.get((gpu, process.pid)) for gpu in process.gpu_indices]
    if any(value is not None and value > 0 for value in values):
        return max(value or 0 for value in values)
    return 0 if values and all(value == 0 for value in values) else None


def read_resources(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    started = fields[19]
    ticks = int(fields[11]) + int(fields[12])
    resident = max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    return started, ticks, resident


class ResourceTracker:
    """Interval CPU time (100% = one core) and resident RAM for each GPU PID."""

    def __init__(self, reader=read_resources, ticks_per_second=None):
        self.reader = reader
        self.ticks_per_second = ticks_per_second or os.sysconf("SC_CLK_TCK")
        self.previous = {}

    def update(self, processes, now=None):
        now = time.monotonic() if now is None else now
        current = {}
        for p in processes:
            p.cpu_percent = None
            p.ram_mib = None
            try:
                started, ticks, resident = self.reader(p.pid)
                if not p.started or started != p.started:
                    continue
                p.ram_mib = resident
                prior = self.previous.get(p.key)
                if prior:
                    elapsed, delta = now - prior[0], ticks - prior[1]
                    if 0 < elapsed <= 15 and delta >= 0:
                        p.cpu_percent = delta / self.ticks_per_second / elapsed * 100
                current[p.key] = (now, ticks)
            except (OSError, ValueError, IndexError):
                continue
        self.previous = current


RESOURCE_TRACKER = ResourceTracker()


class IdleTracker:
    def __init__(self):
        self.states = {}
        self.last_sample = None
        self.last_alert = {}

    def update(
        self,
        processes,
        now,
        minutes=10,
        enabled=True,
        ignored=(),
        snoozed=None,
        minimum=100,
    ):
        if self.last_sample is not None and now - self.last_sample > 15:
            self.states.clear()
        self.last_sample = now
        present = set()
        alerts = []
        for p in processes:
            key = (p.pid, p.started)
            present.add(key)
            if (
                not p.started
                or p.memory < minimum
                or p.activity is None
                or p.activity > 0
                or p.cpu_percent is None
                or p.cpu_percent > 0
            ):
                self.states.pop(key, None)
                p.idle_seconds = 0
                continue
            since, notified = self.states.get(key, (now, False))
            p.idle_seconds = now - since
            allowed = (
                enabled
                and not p.protected
                and p.app_key not in ignored
                and (snoozed or {}).get(p.app_key, 0) <= now
                and now - self.last_alert.get(p.app_key, -math.inf) >= 3600
            )
            if allowed and not notified and p.idle_seconds >= minutes * 60:
                alerts.append(p)
                self.last_alert[p.app_key] = now
                notified = True
            self.states[key] = (since, notified)
        self.states = {k: v for k, v in self.states.items() if k in present}
        return alerts


def snapshot():
    result = subprocess.run(
        ["nvidia-smi", "-q", "-x"],
        capture_output=True,
        text=True,
        timeout=8,
        check=True,
    )
    gpus, processes, unknown = parse_snapshot(result.stdout)
    processes = [decorate(p) for p in processes]
    try:
        sample = subprocess.run(
            ["nvidia-smi", "pmon", "-c", "1", "-s", "u"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        activity = parse_activity(sample.stdout)
    except (OSError, subprocess.SubprocessError):
        activity = {}
    for p in processes:
        p.activity = process_activity(p, activity)
    RESOURCE_TRACKER.update(processes)
    return gpus, processes, unknown


def terminate(process, force=False):
    if process.protected or Path(process.executable).name.lower() in PROTECTED:
        raise RuntimeError("Desktop system processes are protected in VRAM Manager.")
    pid = process.target_pid
    if pid <= 1 or pid == os.getpid() or not process.target_started:
        raise RuntimeError(
            "Cannot safely identify this process. Refresh and try again."
        )
    # pidfd binds the signal to this exact process even if the PID gets reused.
    fd = os.pidfd_open(pid)
    try:
        if identity(process.pid)[0] != process.started:
            raise RuntimeError("The GPU process changed. Select it again.")
        if identity(pid)[0] != process.target_started:
            raise RuntimeError("This process changed. Refresh and select it again.")
        signal.pidfd_send_signal(fd, signal.SIGKILL if force else signal.SIGTERM)
    finally:
        os.close(fd)


PROTECTED = {
    "xorg",
    "xwayland",
    "gnome-shell",
    "kwin_wayland",
    "kwin_x11",
    "plasmashell",
    "sway",
    "weston",
    "cinnamon",
    "mutter",
    "xfwm4",
    "wayfire",
    "hyprland",
    "gdm",
    "gdm3",
    "sddm",
    "lightdm",
}

VERSION = "0.1.0-beta.1"
DEFAULTS = {
    "minimum": 100,
    "idle_minutes": 10,
    "alert_vram": 1024,
    "alerts": False,
    "last_idle_alert": 0,
    "width": 1180,
    "height": 780,
    "sort_column": 1,
    "sort_descending": True,
    "ignored": [],
}


class Settings:
    def __init__(self, path=None):
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.path = Path(path) if path else root / "vram-manager" / "settings.json"
        self.values = {**DEFAULTS, "ignored": []}
        self.error = ""
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict):
                raise ValueError("Expected a settings object")
            for key, low, high in [
                ("last_idle_alert", 0, 32503680000),
                ("minimum", 0, 1000000),
                ("idle_minutes", 1, 120),
                ("alert_vram", 100, 1000000),
                ("width", 760, 3000),
                ("height", 600, 2000),
                ("sort_column", 0, 10),
            ]:
                value = data.get(key)
                if type(value) in (int, float) and math.isfinite(value):
                    self.values[key] = int(max(low, min(value, high)))
            if self.values["sort_column"] not in (0, 1, 2, 3, 4, 5, 9, 10):
                self.values["sort_column"] = 1
            for key in ("alerts", "sort_descending"):
                if type(data.get(key)) is bool:
                    self.values[key] = data[key]
            if isinstance(data.get("ignored"), list):
                self.values["ignored"] = [
                    v for v in data["ignored"] if isinstance(v, str)
                ][:1000]
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.error = f"Settings could not be read; defaults loaded: {exc}"

    def save(self):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".settings-", dir=self.path.parent)
            with os.fdopen(fd, "w") as handle:
                json.dump(self.values, handle, indent=2)
                handle.write("\n")
            os.replace(temporary, self.path)
            self.error = ""
            return True
        except OSError as exc:
            self.error = f"Settings could not be saved: {exc}"
            return False
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


@dataclass
class QuitWatch:
    process: Process
    baseline_used: float | None
    requested_at: float
    known_keys: set
    exited_at: float | None = None

    def check(self, processes, used, now):
        try:
            alive = identity(self.process.target_pid)[0] == self.process.target_started
        except OSError:
            alive = False
        if alive:
            if now - self.requested_at >= 10:
                return "Still running. You can try Force quit.", True
            return "Waiting for the app to exit…", False
        if self.exited_at is None:
            self.exited_at = now
        replacement = any(
            p.app_key == self.process.app_key and p.key not in self.known_keys
            for p in processes
        )
        if replacement:
            return (
                f"{self.process.name} exited; a new matching GPU process appeared (possibly restarted).",
                True,
            )
        delta = ""
        if self.baseline_used is not None and used is not None:
            change = self.baseline_used - used
            direction = "increased" if change >= 0 else "decreased"
            delta = f" Free GPU memory {direction} by {abs(change):,.0f} MiB overall."
        return f"{self.process.name} exited.{delta}", now - self.exited_at >= 8


class AlertBudget:
    """One automatic banner per hour, including across application restarts."""

    def __init__(self, settings):
        self.settings = settings

    def ready(self, now):
        previous = self.settings.values["last_idle_alert"]
        return previous == 0 or now - previous >= 3600

    def claim(self, now, desktop_available):
        if not desktop_available or not self.ready(now):
            return False
        self.settings.values["last_idle_alert"] = now
        # Fail closed if we cannot preserve the cooldown across restarts.
        return self.settings.save()
