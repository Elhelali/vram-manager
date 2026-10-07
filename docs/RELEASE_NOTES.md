# VRAM Manager 0.1.0-beta.1

A native Ubuntu app showing which NVIDIA GPU processes hold memory, with deliberate app termination and advisory notifications.

- Graphics and compute allocations in one live list, with readable app/script names and real desktop icons.
- Per-process RAM (RSS) and interval CPU percentages beside VRAM.
- Named GPUs, free/used totals and ten-minute memory history.
- Stable rows and selection, sorting and search.
- Saved thresholds, alert preferences, ignored apps, sorting and window size.
- Opt-in advisory idle alerts, requiring no observed GPU activity and near-zero CPU and batched into at most one automatic banner per hour across restarts. Locked-screen/DND suppression and transient banners prevent notification buildup.
- Branded top-bar indicator with live VRAM, one-hour global alert pause, and automatic login startup. Closing the window keeps monitoring; Quit stops it.
- Adjustable alert VRAM threshold (default 1 GiB) and duration (default 10 minutes), plus Review and in-window Snooze/Ignore controls.
- Protected desktop processes, PID-bound signaling, exit feedback and possible-restart detection.
- Ubuntu `.deb`, source archive, checksums and automated tests.

Beta limits: Linux/NVIDIA only. Ubuntu 24.04 / RTX 5070 / NVIDIA 580.178.04 is the hardware baseline. Multi-GPU data is fixture-tested, not hardware-tested. Unknown activity never triggers idle alerts. Notifications are advisory; no automatic workload termination. No queue, driver installation or self-updater. Login startup requires a desktop session; top-bar support depends on the desktop indicator host. Notification actions depend on the desktop server. Memory-release feedback reflects overall GPU changes, not exclusively the terminated app.

Measured overhead in a short hidden-indicator sample: 61.8–62.8 MiB resident RAM, 0.49% of one CPU core for the manager plus 3.37% for NVIDIA polling helpers (3.86% combined). Results vary by system; see [measurement details](RESOURCE_USE.md).
