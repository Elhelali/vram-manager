# VRAM Manager 0.1.0-beta.4

- Fixed: the per-user installer (`packaging/install_user.py`) wrote a quoted `TryExec` path, so GNOME rejected its desktop entry and the dock showed `io.github.Elhelali.VramManager` with a generic icon. Re-run the per-user installer to repair an existing install. The `.deb` was not affected.
- Everything else is unchanged from beta.3: idle detection, alerts, the top-bar indicator and quit controls.

Ubuntu 24.04 / NVIDIA beta. No automatic termination. Some drivers/processes lack usable activity readings and cannot receive idle alerts. Multi-GPU and other desktops need additional hardware testing.

Install the `.deb` with `sudo apt install ./vram-manager_0.1.0-beta4_all.deb`. Fully quit older instances before reopening after upgrade.
