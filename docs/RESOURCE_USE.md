# Resource use

VRAM Manager is itself a resident app, so its overhead belongs in the release notes.

A 30-second measurement on the development Ubuntu GNOME desktop, with an RTX 5070 / NVIDIA 580.178.04, after a five-second warm-up:

| Measurement | Observed |
| --- | --- |
| Mode | Top-bar indicator; full window hidden; two-second GPU polling |
| Manager resident RAM | 61.8–62.8 MiB |
| Manager average CPU | 0.49% of one core |
| Completed NVIDIA polling subprocess CPU | 3.37% of one core |
| Combined measured CPU | 3.86% of one core |
| Dedicated GPU allocation for manager | Not listed in NVIDIA process readings |

100% CPU means one fully occupied core, not the entire machine. The manager's RAM figure excludes transient NVIDIA helper memory and does not measure driver/kernel overhead. Not being listed is not proof of exactly zero graphics cost; the desktop compositor may do work on its behalf.

This is one short sample on one machine, not a universal guarantee or a long-duration memory-leak test. Driver, GPU, process count, desktop theme and whether the full window is visible affect overhead. The app polls twice per cycle: XML allocations and process utilization. Polling helper CPU is included rather than hidden behind the Python process's smaller number.

RSS was sampled once per second from `/proc`; CPU totals came from `getrusage(RUSAGE_SELF)` and `getrusage(RUSAGE_CHILDREN)` over monotonic elapsed time. The raw results are in [resource-sample.json](resource-sample.json). No benchmark terminated user GPU workloads.
