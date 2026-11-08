# Try Wizard

**Wizard Desktop for the Mac**: a personal AI Wizard that lives in its own small Linux computer, packaged as an ordinary, windowed Mac app.

Try Wizard is a fork of [Try Omarchy](https://github.com/omacom/try-omarchy) (MIT). We keep its native Apple Silicon VM machinery (QEMU + Hypervisor.framework, VirGL graphics, clipboard, keyboard and display integration) and replace the Omarchy desktop with one window: the Wizard.


> **New in 0.2: Wizard for Mac (next).** A 2 MB native app plus a WizardOS back end on Apple's Virtualization framework that keeps running from the menu bar. Opens in 0.3 s and uses about 0.7 GB of memory. Source and numbers: [`next/`](next/README.md). The QEMU-based 0.1.x app below is kept for reference.

## What you get

- **A Mac app window.** Opens windowed, resizable, remembers its size. Full screen is Ctrl-Cmd-F or the green button. Cmd-Q / Cmd-H / Cmd-M / Cmd-Tab behave like any Mac app.
- **A Wizard inside.** Hermes Agent runs as a system service in an Arch Linux ARM guest, with Jan's Wizard UX in a frameless Chromium window. The Wizard has its own sudo, so it can install and run real Linux software.
- **Onboarding in four steps:** name your Wizard, connect a brain (free starter brain with no login; Sign in with ChatGPT through the Mac's own browser; or an Anthropic / OpenRouter key), hear it reply, then a first chat where it installs `figlet` and draws its name.
- **It persists.** Quit and reopen: same Wizard, same chats, same installed packages. Updating the app keeps the Wizard's disk.

## Install (testers)

1. Get `Wizard.dmg` from James (Apple Silicon, macOS 15+).
2. Open it and drag **Wizard** into **Applications**.
3. First launch: right-click Wizard > **Open** (test build, not notarized). If macOS still blocks it: System Settings > Privacy & Security > **Open Anyway**.
4. Wait about 40 seconds for first boot, then follow the four onboarding steps.

To update, quit Wizard, drag the new version over the old one (Replace), reopen.

## Where things live

| Path | What |
| --- | --- |
| `macos/` | Native Mac app (Swift launcher, QEMU patches). Wizard changes are applied by `wizard/scripts/apply-wizard-app-patch.py` and already committed here. |
| `macos/patches/wizard-cocoa-edit.py` | Window behaviour inside QEMU's Cocoa front end (Mac shortcuts, Ctrl-Cmd-F, remembered window frame, product name). |
| `guest/` | Upstream guest image build (Arch Linux ARM + Omarchy). Try Wizard remasters that image rather than rebuilding it. |
| `wizard/overlay/` | Files copied into the guest: `/opt/wizard` (services, kiosk, onboarding server), systemd units, Hyprland session config. |
| `wizard/scripts/` | Remaster, runtime payload, app and DMG builds, plus the end-to-end test scripts used on our Mac mini. |
| `UPSTREAM-README.md` | Try Omarchy's original README. |

Guest layout: Hermes API on 127.0.0.1:8865, Wizard UX on 8923, onboarding on 8930, all state under `/var/lib/wizard` (`HERMES_HOME=/var/lib/wizard/hermes`). Hidden builder terminal: Ctrl-Option-Cmd-T.

## Building

The pipeline currently runs on an Apple Silicon Mac with Xcode, Colima/Docker (arm64) and a roomy external volume; the scripts in `wizard/scripts/` show the exact order:

1. `build-runtime-payload.sh` (in an arm64 container): Python venv, Hermes Agent source, Node and the Wizard UX into `/opt/wizard`.
2. `stage1-remaster.sh` (privileged alpine container): start from the stock Try Omarchy guest image, grow it to 8 GiB, install the payload and `wizard/overlay`, enable the services.
3. `make runtime` / `macos/build-qemu-gpu-runtime.sh`: patched QEMU runtime (includes `wizard-cocoa-edit.py`).
4. `macos/build-app.sh --configuration production --sign-identity - --guest-dir <remastered guest>`.
5. `thales-dmg-headless.sh`: Wizard.app + Applications link into a compressed, ad-hoc signed DMG.

Hermes Agent and the Wizard UX are not vendored here. The payload step expects `payload/hermes-agent.tgz` (a `git archive` of Hermes Agent), `payload/ux.tgz` + `payload/ux-dist.tgz` (Wizard UX server and built front end, branch `experiment/wizard-desktop-vm`), and `payload/dl/{uv.tar.gz,node.tar.xz}` (arm64 Linux uv and Node). `wizard/payload-requirements.txt` pins the Python dependencies.

## Status

Prototype 0.1.1. Verified on a Mac mini: clean install from DMG, onboarding to first chat in about a minute, Wizard installs packages with pacman, state survives quit/reopen and app upgrade, windowed launch. ChatGPT sign-in verified by James. Not yet: notarization, auto-update, Windows.

## Credits and license

MIT, inherited from Try Omarchy (see `LICENSE`, `THIRD_PARTY_NOTICES.md`). The Omarchy name and mark belong to their owners; the Wizard build replaces them with its own name and icon.

## Portable QA configuration

Set `WIZARD_WORK_ROOT` to your work disk for build, VM and QA data; Python/local
smokes default to `${TMPDIR:-/tmp}/wizard-work`, while disk-heavy Mac shell
scripts require it explicitly. Remote staging requires `WIZARD_BUILD_HOST`
(no default). Never put personal mount paths or SSH aliases in tracked scripts.
Use `HERMES_HOME` (default `$HOME/.hermes`) for Hermes state. Source checkouts in
local smoke scripts can be selected with `WIZARD_UX_DIR` and
`WIZARD_SETUP_SCRIPT`; capture these before the disposable smoke `HOME` is set.

The tracked-file portable-paths guard runs first in `make test-contracts` (also
part of `make test` / CI). Run it alone on Linux with
`python3 tests/test-portable-paths.py`. Native Swift/VM checks still need macOS.
