# Beta release checklist

## Local preparation

- [x] Saved preferences, stable rows and selection
- [x] Real app icons plus bundled fallback icons
- [x] Memory graph, named GPUs and expandable details
- [x] Protected processes and PID-bound signaling
- [x] Notification actions and background monitoring
- [x] Quit feedback and possible-restart detection
- [x] Unit and desktop fixture tests
- [x] Portable package layout, source archive and checksums
- [x] Clean Ubuntu install, non-root GUI and complete uninstall verified
- [x] Install, upgrade, uninstall and limitations documentation
- [x] GitHub CI workflow prepared

## Before publication

- [x] Owner confirms GitHub repository and license
- [x] Apply approved license and replace pending-license text
- [ ] Run final checks and rebuild release assets/checksums
- [ ] Create repository, push reviewed source and run GitHub CI
- [ ] Create prerelease v0.1.0-beta.1 with package, source, checksums and release notes

Additional NVIDIA drivers, Wayland and multi-GPU hardware are beta follow-up. AppImage, Snap and job queuing are later releases.
