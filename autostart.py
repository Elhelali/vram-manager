"""XDG desktop-session startup, with a per-user opt-out."""

import os
import sys
from pathlib import Path


def path():
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "autostart/vram-manager.desktop"
    )


def enabled():
    target = path()
    if target.exists():
        return "Hidden=true" not in target.read_text()
    return Path("/etc/xdg/autostart/vram-manager.desktop").exists()


def quote(argument):
    escaped = (
        str(argument)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("%", "%%")
    )
    return f'"{escaped}"'


def set_enabled(value, command=None):
    if command is None:
        location = Path(__file__).resolve().parent
        if location == Path("/usr/share/vram-manager"):
            command = ["/usr/bin/vram-manager"]
        elif location == Path.home() / ".local/share/vram-manager":
            command = [str(Path.home() / ".local/bin/vram-manager")]
        else:
            command = [sys.executable, str(location / "vram_manager.py")]
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "[Desktop Entry]\nType=Application\nName=VRAM Manager\n"
        f'Exec={" ".join(quote(arg) for arg in command)}\n'
        f"TryExec={command[0]}\n"
        "Icon=vram-manager\nTerminal=false\n"
        f'Hidden={"false" if value else "true"}\n'
        "X-GNOME-Autostart-Delay=5\n"
    )
