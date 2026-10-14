# Always-on Wizard: product plan

**Status:** direction locked 9 October 2026 (Bangkok). Each item below has one issue in this repo; the issue is where status lives.

## Direction

1. **Owned hardware beats a VPS.** Hostinger introduced CPU credits on 1 October 2026: a KVM 4 earns credits below 40% CPU, spends them above it, and is throttled to about 10% CPU when the balance runs out. Light Wizard use is fine on a VPS, but the long-term home for a Wizard is a machine the owner controls.
2. **Stopgap until Wizard One:** recommend an always-on machine running Wizard for Mac (or the Windows/Linux build later). A VPS stays the fallback for people without a suitable machine or with poor home internet.

## Recommended home machine

| | Minimum | Recommended |
| --- | --- | --- |
| CPU | 4 cores | 4+ cores (Apple M1 or newer; N150/Ryzen mini PC) |
| Memory | 8 GB (Wizard gets 4 GB) | 16 GB (Wizard gets 8 GB) |
| Storage | SSD, 100 GB free | SSD, 256 GB+ |
| Network | Wi-Fi | Wired ethernet |
| Power | Always plugged in, never sleeps | Plus a small UPS |

- Wizard OS is ARM64-only today, so Intel Macs are unsupported until an x86_64 image ships ([#17](https://github.com/humanitylabs-org/try-wizard/issues/17)).
- Old laptops are acceptable: cap the charge at about 80% and allow lid-closed operation.
- Remote access is Tailscale; public publishing goes through a Cloudflare tunnel. No static IP or port forwarding.

## Product work (benefits every owner)

1. **Configurable resources.** ([#1](https://github.com/humanitylabs-org/try-wizard/issues/1)) A user setting for guest CPU and memory with hardware-based defaults.
2. **Growable disk on a chosen volume.** ([#2](https://github.com/humanitylabs-org/try-wizard/issues/2)) Grow on demand and allow placing the Wizard disk on an external volume.
3. **Encrypted export/import bundle.** ([#3](https://github.com/humanitylabs-org/try-wizard/issues/3)) One bundle carries the Wizard core (memory, skills, sessions, config, credentials, app data) between VPS, Mac VM and Wizard One. The same code powers migration, backup and restore. **Build this first.**
4. **Headless always-on mode.** ([#4](https://github.com/humanitylabs-org/try-wizard/issues/4)) Start at boot without a GUI login, restart on crash, keep the host awake.
5. **Tailscale inside Wizard OS.** ([#5](https://github.com/humanitylabs-org/try-wizard/issues/5)) Give the guest its own tailnet identity so the owner's phone reaches it directly.
6. **In-place Wizard OS updates.** ([#6](https://github.com/humanitylabs-org/try-wizard/issues/6)) Existing installs receive guest updates without a reinstall.
7. **Scheduled off-machine backups.** ([#7](https://github.com/humanitylabs-org/try-wizard/issues/7)) The export bundle on a schedule to object storage, with a tested restore.

## Done when

An owner can move an existing Wizard onto their own always-on machine with the export bundle, run it headless with its own tailnet name, update it in place, and restore it from an off-machine backup onto a fresh install.
