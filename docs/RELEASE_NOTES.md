# VRAM Manager 0.1.0-beta.3

- Dash-only pmon rows now count as no observed GPU activity when another row in the same sample has a numeric SM reading on the same GPU. Evidence from one GPU never enables idle detection on another.
- A GPU with no numeric SM samples keeps dash-only processes Unknown. Failed queries, empty output and unlisted processes also remain Unknown. Drivers that never return per-process numbers cannot trigger idle alerts.
- Numeric engine readings keep their maximum value, including zero. Quiet also requires CPU below 5% of one core. Inferring quiet from dashes is advisory, not proof that a process has no useful work.
- Display servers remain protected even when another user's process details cannot be read.
- App ID and desktop entry now use `io.github.Elhelali.VramManager`.
- Startup entries check executable availability. A per-user uninstaller removes the application and login entry while retaining settings. System package removal also removes its system startup entry.
- Existing combined alerts, persisted one-hour cooldown, lock/DND suppression, branded top-bar indicator and adjustable thresholds remain.

Ubuntu 24.04 / NVIDIA beta. No automatic termination. Some drivers/processes lack usable activity readings and cannot receive idle alerts. Multi-GPU and other desktops need additional hardware testing.

Measured beta.1 background footprint: 61.8–62.8 MiB manager RAM and 3.86% of one CPU core including NVIDIA polling helpers during a 30-second sample. Beta.3 was not separately profiled; see [measurement details](RESOURCE_USE.md).

Install the `.deb` with `sudo apt install ./vram-manager_0.1.0-beta3_all.deb`. Fully quit older instances before reopening after upgrade. The app ID and uninstall/startup behavior introduced in beta.2 are retained.
