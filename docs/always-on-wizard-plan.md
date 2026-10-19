# Always-on Wizard plan: owned hardware, and Archimedes onto Thales

**Status:** locked by James, 9 October 2026 (Bangkok).
**Tracking:** issues labelled `always-on` in this repo. Each item below has one issue; the issue is where status lives.
**Daily coordination:** Archimedes posts a short "what to move today" note in the Wizard thread *Always-on Wizard — daily moves*.

## Direction

1. **Owned hardware beats a VPS.** Hostinger introduced CPU credits on 1 October 2026: a KVM 4 earns credits below 40% CPU, spends them above it, and is throttled to about 10% CPU when the balance runs out. Light Wizard use is fine on a VPS, but the long-term home for a Wizard is a machine the owner controls.
2. **Stopgap until Wizard One:** recommend an always-on machine running Wizard for Mac (or the Windows/Linux build later). A VPS stays the fallback for people without a suitable machine or with poor home internet.
3. **Archimedes moves to Thales only when the packaged installer is complete,** so the migration is also the end-to-end test of the product.

## Recommended home machine

| | Minimum | Recommended |
| --- | --- | --- |
| CPU | 4 cores | 4+ cores (Apple M1 or newer; N150/Ryzen mini PC) |
| Memory | 8 GB (Wizard gets 4 GB) | 16 GB (Wizard gets 8 GB) |
| Storage | SSD, 100 GB free | SSD, 256 GB+ |
| Network | Wi-Fi | Wired ethernet |
| Power | Always plugged in, never sleeps | Plus a small UPS |

- Wizard OS is ARM64-only today, so Intel Macs are unsupported until an x86_64 image ships.
- Old laptops are acceptable: cap the charge at about 80% and allow lid-closed operation.
- Remote access is Tailscale; public publishing goes through a Cloudflare tunnel. No static IP or port forwarding.

## Thales split (when Archimedes moves)

- Wizard OS VM: 8 vCPU, 16 GB RAM, disk on the external `ThalesMedia` SSD.
- macOS keeps 16 GB and does Android builds, ffmpeg/VideoToolbox rendering and Mizel capture. The VM cannot reach Apple's hardware encoders, so media work stays native.

## Phase 1 — installer gaps (product work, benefits every customer)

1. **Configurable resources.** ([#1](https://github.com/humanitylabs-org/try-wizard/issues/1)) Today `Host/main.swift` caps the guest at 4 vCPU and 4 GB. Add a setting with hardware-based defaults.
2. **Growable disk on a chosen volume.** ([#2](https://github.com/humanitylabs-org/try-wizard/issues/2)) The rootfs is a fixed ~2 GB image in `~/Library/Application Support/Wizard/os`. Grow on demand and allow placement on an external volume.
3. **Encrypted export/import bundle.** ([#3](https://github.com/humanitylabs-org/try-wizard/issues/3)) One bundle carries the Wizard core (memory, skills, sessions, config, credentials, app data) between VPS, Mac VM and Wizard One. The same code powers migration, backup and restore. **Build this first.**
4. **Headless always-on mode.** ([#4](https://github.com/humanitylabs-org/try-wizard/issues/4)) Start at boot without a GUI login, restart on crash, keep the host awake.
5. **Tailscale inside Wizard OS.** ([#5](https://github.com/humanitylabs-org/try-wizard/issues/5)) The guest is behind host NAT today; it needs its own tailnet identity so phones and other tailnet devices reach it directly.
6. **In-place Wizard OS updates.** ([#6](https://github.com/humanitylabs-org/try-wizard/issues/6)) Existing installs need guest updates without a reinstall.
7. **Scheduled off-machine backups.** ([#7](https://github.com/humanitylabs-org/try-wizard/issues/7)) The export bundle on a schedule to object storage, with a tested restore.

## Phase 2 — Thales preparation

8. **Power resilience.** ([#8](https://github.com/humanitylabs-org/try-wizard/issues/8)) UPS, or FileVault's authenticated-restart flow. Today an abrupt reboot stops at the FileVault unlock screen and Thales stays offline.
9. **Workload split and host access.** ([#9](https://github.com/humanitylabs-org/try-wizard/issues/9)) Lock the 8 vCPU / 16 GB allocation. Archimedes currently drives Thales over SSH for builds and renders; that becomes VM → host and must be verified.
10. **Network.** ([#10](https://github.com/humanitylabs-org/try-wizard/issues/10)) Thales is on Wi-Fi (`en1`); move it to wired ethernet and confirm home upload capacity.

## Phase 3 — rehearsal and cutover

11. **One-week shadow run.** ([#11](https://github.com/humanitylabs-org/try-wizard/issues/11)) Fresh install on Thales, import a copy of Archimedes' bundle, run on the tailnet alongside Telos. Check cron jobs, the Wizard app connection, private sites, and memory/search parity.
12. **Cutover runbook.** ([#12](https://github.com/humanitylabs-org/try-wizard/issues/12)) Replace the retired custom domain with the configured tailnet origin, move cron, and guarantee a single active scheduler (no double-firing jobs).
13. **Rollback window.** ([#13](https://github.com/humanitylabs-org/try-wizard/issues/13)) Keep the Hostinger VPS for 30 days after cutover.

## Done when

A fresh Wizard for Mac install on Thales imports Archimedes' bundle, runs a week beside Telos with no missed jobs, and survives a reboot and a pulled plug without anyone touching it. Then Telos is retired after the 30-day rollback window.

## Hardware to buy now

- UPS for Thales and the router (950 VA class is enough: a Mac mini M4 draws well under 100 W).
- Cat6 ethernet cable to the router.
- Optional: smart plug on Thales only, for remote power-cycling.
