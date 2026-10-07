#!/usr/bin/python3
"""Build an unprivileged Debian package and a clean source archive."""

import gzip
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import VERSION

DEB_VERSION = VERSION.replace("-beta.", "~beta")
ARTIFACT_VERSION = DEB_VERSION.replace("~", "-")


def build():
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vram-package-") as temporary:
        stage = Path(temporary)
        app = stage / "usr/share/vram-manager"
        app.mkdir(parents=True)
        for name in (
            "backend.py",
            "ui.py",
            "indicator.py",
            "autostart.py",
            "vram_manager.py",
        ):
            shutil.copy2(ROOT / name, app / name)
        shutil.copytree(ROOT / "assets", app / "assets")
        targets = {
            "packaging/vram-manager": "usr/bin/vram-manager",
            "packaging/vram-manager.desktop": "usr/share/applications/io.github.Elhelali.VramManager.desktop",
            "assets/vram-manager.svg": "usr/share/icons/hicolor/scalable/apps/vram-manager.svg",
            "README.md": "usr/share/doc/vram-manager/README.md",
        }
        if (ROOT / "LICENSE").exists():
            targets["LICENSE"] = "usr/share/doc/vram-manager/copyright"
        else:
            targets["packaging/copyright"] = "usr/share/doc/vram-manager/copyright"
        for source, target in targets.items():
            destination = stage / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / source, destination)
        (stage / "usr/bin/vram-manager").chmod(0o755)
        startup = stage / "etc/xdg/autostart/vram-manager.desktop"
        startup.parent.mkdir(parents=True, exist_ok=True)
        startup.write_text(
            (ROOT / "packaging/vram-manager.desktop").read_text()
            + "X-GNOME-Autostart-Delay=5\n"
        )
        control = stage / "DEBIAN"
        control.mkdir()
        prerm = control / "prerm"
        prerm.write_text(
            "#!/bin/sh\nset -e\nif command -v py3clean >/dev/null 2>&1; then\n    py3clean /usr/share/vram-manager\nfi\n"
        )
        prerm.chmod(0o755)
        installed_size = (
            sum(p.stat().st_size for p in stage.rglob("*") if p.is_file()) // 1024 + 1
        )
        (control / "control").write_text(
            f"""Package: vram-manager
Version: {DEB_VERSION}
Section: utils
Priority: optional
Architecture: all
Maintainer: VRAM Manager contributors
Installed-Size: {installed_size}
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-notify-0.7, gir1.2-ayatanaappindicator3-0.1, librsvg2-common
Description: NVIDIA GPU memory monitor and process manager
 Lists graphics and compute processes holding GPU memory, with live updates,
 memory history, advisory idle notifications and deliberate process termination.
 Requires an installed NVIDIA driver providing nvidia-smi and a Linux desktop.
"""
        )
        # Never inherit the temporary directory's 0700 or the user's umask.
        stage.chmod(0o755)
        for path in stage.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        (stage / "usr/bin/vram-manager").chmod(0o755)
        prerm.chmod(0o755)
        output = dist / f"vram-manager_{ARTIFACT_VERSION}_all.deb"
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(stage), str(output)],
            check=True,
        )
    sources = [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not any(
            part in {"dist", "__pycache__", ".git", ".venv"}
            for part in p.relative_to(ROOT).parts
        )
    ]
    archive = dist / f"vram-manager-{VERSION}-source.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(sources):
            tar.add(path, arcname=f"vram-manager-{VERSION}/{path.relative_to(ROOT)}")
    with (dist / "SHA256SUMS").open("w") as checksums:
        for path in (output, archive):
            checksums.write(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            )
    print(output)
    print(archive)


if __name__ == "__main__":
    build()
