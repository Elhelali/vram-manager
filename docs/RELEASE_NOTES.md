# VRAM Manager 0.1.0-beta.2

- Idle detection permits background CPU below 5% of one core when GPU activity is measured as zero.
- Unsupported, missing and failed GPU readings remain Unknown and never trigger idle alerts. NVIDIA pmon dashes are not proof of inactivity; an earlier proposed change treating them as zero was corrected before release.
- Display servers remain protected even when another user's process details cannot be read.
- App ID and desktop entry now use `io.github.Elhelali.VramManager`.
- Startup entries check executable availability. A per-user uninstaller removes the application and login entry while retaining settings. System package removal also removes its system startup entry.
- Existing combined alerts, persisted one-hour cooldown, lock/DND suppression, branded top-bar indicator and adjustable thresholds remain.

Ubuntu 24.04 / NVIDIA beta. No automatic termination. Some drivers/processes lack usable activity readings and cannot receive idle alerts. Multi-GPU and other desktops need additional hardware testing.

Measured beta.1 background footprint: 61.8–62.8 MiB manager RAM and 3.86% of one CPU core including NVIDIA polling helpers during a 30-second sample. Beta.2 was not separately profiled; see [measurement details](RESOURCE_USE.md).

Install the `.deb` with `sudo apt install ./vram-manager_0.1.0-beta2_all.deb`. Fully quit older instances before reopening after upgrade; this release changes the app ID.
