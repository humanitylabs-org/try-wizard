# Wizard for Mac (next)

The 0.2 line splits Wizard into two pieces:

- **Wizard.app** (front end): a native macOS app with the Wizard UX in a WebKit window. About 2 MB. It never contains a VM; it connects to a Wizard OS back end.
- **Wizard OS** (back end): a headless Debian 13 system with Hermes Agent, the onboarding server and the Wizard UX server. It runs on Apple's Virtualization.framework, managed by **Wizard Host**, a menu-bar login item embedded in Wizard.app. It keeps running when the window is closed.

On first launch the app asks *Where should Wizard live?*

1. **On this Mac**: downloads Wizard OS (about 270 MB, checked against a SHA-256 hash), unpacks it into `~/Library/Application Support/Wizard/os`, and starts it in the background.
2. **On another computer**: paste the address of an existing Wizard (tailnet or LAN). No VM is installed.

The *Wizard* menu can switch between Wizards, add another one, install Wizard OS from a downloaded file, or restart the local Wizard OS.

## Layout

| Path | What |
| --- | --- |
| `mac/App/main.swift` | Wizard.app: window, backend chooser, Wizard OS installer, `wizardNative` WebKit bridge |
| `mac/Host/main.swift` | Wizard Host: Virtualization.framework VM, vsock→loopback bridges (47823 UX, 47830 onboarding), menu-bar icon, status file |
| `mac/Shared/Shared.swift` | Paths, ports and the control protocol shared by both |
| `mac/build.sh` | Builds both bundles with `swiftc`, ad-hoc signs them (Host gets `com.apple.security.virtualization`), and makes the DMG |
| `guest/Dockerfile`, `guest/build-image.sh` | Builds the Wizard OS image (kernel, initrd, ext4 rootfs, manifest) inside Docker and packages it as `wizard-os-<ver>.tar.xz` |
| `guest/overlay/` | Wizard services, systemd units, onboarding server |
| `mac/qa-*.sh` | Acceptance scripts run on a real Mac (fresh install, offline install, lifecycle and memory, published-artifact end to end) |

## Measured on an M-series Mac mini (macOS 26), vs Try Wizard 0.1.2

| | 0.2.0 | 0.1.2 |
| --- | --- | --- |
| App download | 1.9 MB | 1.9 GB |
| Open with Wizard OS running | 0.3 s | n/a (VM boots every launch) |
| Open from fully stopped | 2.5–4.3 s | 7.3 s |
| VM memory footprint | ~0.65–0.8 GB | ~3.7 GB |
| Guest image (compressed) | 269 MB | ~1.8 GB |

## Build

```
# on an Apple Silicon Mac with Docker (colima) and Xcode
bash next/guest/build-image.sh      # -> out/wizard-os-<ver>.tar.xz
bash next/mac/build.sh              # -> mac/dist/Wizard.app, Wizard-<ver>.dmg
```

The guest build expects the existing Try Wizard runtime bundle (Hermes + Node + Wizard UX) at `out/wizard-runtime.tgz`.
