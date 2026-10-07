# Validation for 0.1.0-beta.1

Completed locally:

- 12 unit tests: graphics/compute parsing, unavailable allocations, multi-GPU aggregation and incomplete activity coverage; unknown/zero/active readings; idle resets, mute/snooze and protected exclusions; private atomic settings saves; quit results/restarts; PID reuse rejection; SIGTERM/SIGKILL on disposable sleep processes.
- Desktop fixtures: stable row references and selection, filters, protected controls, notification callback actions, hide/reopen, settings persistence and driver-error recovery.
- Live Ubuntu GNOME / RTX 5070 / NVIDIA 580.178.04: app icons, real readings, named GPU, auto updates, selection preservation, saved preferences and graph rendering.
- Sustained `nvidia-smi pmon` and a read-only NVML utilization query were inspected. Some processes have no usable samples; they remain Unknown.

No real user GPU workloads were terminated. Notification actions are fixture-tested with captured callbacks; the real GNOME notification server also accepted a test notification and reported support for actions. Actual human interaction with notification buttons was not tested.

Limits: no second physical GPU, other driver branch or Wayland session tested. GitHub workflow has not run remotely. Idle timers use deterministic samples; no controlled real GPU busy/idle workload experiment has been run. These limits are disclosed in release notes.

- Per-user installation succeeds; launching a second copy activates the first instance.

- Clean Ubuntu 24.04 container: package dependency installation, installed launcher version, desktop-file validation, 12 unit tests, installed-code desktop fixtures, and package removal passed. The first test exposed leftover Python bytecode from root-run tests; the package now cleans its own bytecode during removal.

Final artifact check: clean Ubuntu 24.04 installation, installed-code GUI fixtures as root and as the unprivileged nobody user, and complete removal of /usr/bin/vram-manager and /usr/share/vram-manager all passed. Full package-test log is shipped alongside the local build as dist/validation.log.

CPU/RAM extension: 16 unit tests pass, including interval CPU math, missing/reused PID handling, CPU suppression of idle alerts, one-hour alert cooldown and an actual disposable busy CPU worker. Live GPU PIDs returned RSS and interval CPU readings. CPU/RAM GUI fixtures pass. The package layout and dependencies are unchanged from the clean-container installation test; the updated packaged GUI is also checked after extraction.

Indicator update: 18 unit tests pass, including configurable alert VRAM and login-startup enable/disable. Live Ubuntu registration confirmed Id vram-manager, Status Active, the branded icon and VRAM label. Default tray mode, Open, global pause/resume and close-to-indicator were exercised. Startup desktop files validate, but the user session was not rebooted/logged out during testing. The new indicator dependency resolves in an apt installation simulation. Resource usage is measured and documented in RESOURCE_USE.md.

Notification hardening: 20 unit tests pass. GUI fixtures verify seven simultaneous candidates produce one combined banner, further attempts are suppressed, and desktop suppression prevents delivery. The persisted cooldown survives restart and suppresses alerts after clock rollback; failed settings persistence prevents sending. Physical lock/unlock and a long-duration soak remain manual beta follow-up.
