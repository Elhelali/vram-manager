#!/usr/bin/python3
"""Install this app for the current user without administrator access."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = Path.home() / ".local"
APP = PREFIX / "share/vram-manager"


def main():
    APP.mkdir(parents=True, exist_ok=True)
    for name in (
        "backend.py",
        "ui.py",
        "indicator.py",
        "autostart.py",
        "vram_manager.py",
    ):
        shutil.copy2(ROOT / name, APP / name)
    shutil.copytree(ROOT / "assets", APP / "assets", dirs_exist_ok=True)
    launcher = PREFIX / "bin/vram-manager"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(
        "#!/usr/bin/python3\nimport runpy\nimport sys\n"
        f"sys.path.insert(0, {str(APP)!r})\n"
        f'runpy.run_path({str(APP / "vram_manager.py")!r}, run_name="__main__")\n'
    )
    launcher.chmod(0o755)
    desktop = (ROOT / "packaging/vram-manager.desktop").read_text()
    escaped = (
        str(launcher)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("%", "%%")
    )
    desktop = desktop.replace("Exec=vram-manager", f'Exec="{escaped}"')
    desktop = desktop.replace("TryExec=vram-manager", f"TryExec={launcher}")
    target = PREFIX / "share/applications/io.github.Elhelali.VramManager.desktop"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(desktop)
    (PREFIX / "share/applications/vram-manager.desktop").unlink(missing_ok=True)
    icon = PREFIX / "share/icons/hicolor/scalable/apps/vram-manager.svg"
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "assets/vram-manager.svg", icon)
    import sys

    sys.path.insert(0, str(ROOT))
    import autostart

    if not autostart.path().exists():
        autostart.set_enabled(True, [str(launcher)])
    print(f"Installed for current user: {launcher}")


if __name__ == "__main__":
    main()
