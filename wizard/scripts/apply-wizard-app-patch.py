#!/usr/bin/env python3
"""Apply Wizard Desktop changes to the Try Omarchy fork (idempotent).

1. NativeSettingsBridge: accept one bounded `open-url https://...` line and open it
   in the Mac's default browser (used by onboarding's "Sign in with ChatGPT").
2. Rebrand user-visible strings, bundle identity and storage folder to Wizard.
3. Wizard app icon.
"""
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1])
mac = repo / "macos"
src = mac / "Sources" / "OmarchyVMHelper"


def edit(path: Path, pairs, *, required=True):
    text = path.read_text()
    out = text
    for old, new in pairs:
        if new in out:
            continue
        if old not in out:
            if required:
                raise SystemExit(f"{path}: anchor not found: {old[:80]!r}")
            continue
        out = out.replace(old, new)
    if out != text:
        path.write_text(out)
        print(f"patched {path.relative_to(repo)}")


# 1. open-url bridge ---------------------------------------------------------
edit(src / "NativeSettingsBridge.swift", [
    ("import Darwin\nimport Foundation\n", "import AppKit\nimport Darwin\nimport Foundation\n"),
    ("    private(set) var migrationReports: [GuestBootFixReport] = []\n",
     "    private(set) var migrationReports: [GuestBootFixReport] = []\n"
     "    /// Wizard Desktop: https links the guest asked the Mac to open.\n"
     "    private(set) var openURLs: [URL] = []\n"),
    ("        migrationReports.removeAll(keepingCapacity: true)\n",
     "        migrationReports.removeAll(keepingCapacity: true)\n"
     "        openURLs.removeAll(keepingCapacity: true)\n"),
    ("                requested = requested || (!discarding && line == Data(\"open-settings\".utf8))\n",
     "                requested = requested || (!discarding && line == Data(\"open-settings\".utf8))\n"
     "                if !discarding, let url = Self.openURLRequest(line) { openURLs.append(url) }\n"),
    ("        return requested\n    }\n}\n",
     "        return requested\n    }\n\n"
     "    /// Only plain https URLs, bounded, no whitespace or control bytes.\n"
     "    static func openURLRequest(_ line: Data) -> URL? {\n"
     "        let prefix = Data(\"open-url \".utf8)\n"
     "        guard line.count > prefix.count, line.count <= 2048, line.starts(with: prefix),\n"
     "              let text = String(data: line.dropFirst(prefix.count), encoding: .utf8),\n"
     "              !text.unicodeScalars.contains(where: { $0.value <= 0x20 || $0.value == 0x7f }),\n"
     "              let url = URL(string: text), url.scheme?.lowercased() == \"https\",\n"
     "              let host = url.host, !host.isEmpty else { return nil }\n"
     "        return url\n"
     "    }\n}\n"),
    ("        var requested = false\n        for _ in 0..<16 {\n",
     "        var requested = false\n        var opened: [URL] = []\n        for _ in 0..<16 {\n"),
    ("                for report in requests.migrationReports { migrationReport(report) }\n",
     "                for report in requests.migrationReports { migrationReport(report) }\n"
     "                opened.append(contentsOf: requests.openURLs)\n"),
    ("        guard requested else { return }\n",
     "        for url in opened.prefix(4) {\n"
     "            let ok = NSWorkspace.shared.open(url)\n"
     "            let reply = Data((ok ? \"opened\\n\" : \"unavailable\\n\").utf8)\n"
     "            let written = reply.withUnsafeBytes { Darwin.write(descriptor, $0.baseAddress, $0.count) }\n"
     "            if written != reply.count { stop(); return }\n"
     "        }\n"
     "        guard requested else { return }\n"),
])

# 2. rebrand -----------------------------------------------------------------
edit(mac / "build-app.sh", [
    ("    bundle_identifier=dev.tryomarchy.native.development\n    app_display_name='Try Omarchy Dev'\n",
     "    bundle_identifier=com.aiwizards.desktop.development\n    app_display_name='Wizard Dev'\n"),
    ("    bundle_identifier=dev.tryomarchy.native\n    app_display_name='Try Omarchy'\n",
     "    bundle_identifier=com.aiwizards.desktop\n    app_display_name='Wizard'\n"),
    ('legacy_app="$repo_dir/dist/Try Omarchy.app"', 'legacy_app="$repo_dir/dist/Wizard.app"'),
    ('app="$repo_dir/dist/app.noindex/Try Omarchy.app"', 'app="$repo_dir/dist/app.noindex/Wizard.app"'),
    ('  app="$repo_dir/dist/release.noindex/Try Omarchy.app"', '  app="$repo_dir/dist/release.noindex/Wizard.app"'),
    ('bundled_qemu="$contents/Resources/runtime/bin/Try Omarchy"', 'bundled_qemu="$contents/Resources/runtime/bin/Wizard"'),
    ('app_icon_source="$macos_dir/OmarchyIcon.svg"', 'app_icon_source="$macos_dir/WizardIcon.svg"'),
])
edit(mac / "run-qemu-gpu.sh", [
    ('qemu_bin="$resources_dir/runtime/bin/Try Omarchy"', 'qemu_bin="$resources_dir/runtime/bin/Wizard"'),
    ("  -name 'Try Omarchy'\n", "  -name 'Wizard'\n"),
    ("      -name 'Try Omarchy Boot Recovery' \\\n", "      -name 'Wizard Boot Recovery' \\\n"),
    ('    "sizeMiB": 6144,\n', '    "sizeMiB": 8192,\n'),
])
edit(mac / "qemu-persistent-storage.sh", [
    ('qps_configured_root="$HOME/Library/Application Support/Try Omarchy/VM/v1"',
     'qps_configured_root="$HOME/Library/Application Support/Wizard/VM/v1"'),
])
edit(mac / "resize-vm-disk.sh", [
    ("Default: ~/Library/Application Support/Try Omarchy/VM/v1", "Default: ~/Library/Application Support/Wizard/VM/v1"),
    ('state_root="${HOME:?}/Library/Application Support/Try Omarchy/VM/v1"',
     'state_root="${HOME:?}/Library/Application Support/Wizard/VM/v1"'),
])
edit(mac / "package-dmg.sh", [('diskutil rename "$mount_dir" "Try Omarchy"', 'diskutil rename "$mount_dir" "Wizard"')])
edit(src / "QEMUGPULauncher.swift", [
    ('            .appendingPathComponent("Try Omarchy", isDirectory: true)', '            .appendingPathComponent("Wizard", isDirectory: true)'),
    ('    static let appName = "Try Omarchy.app"', '    static let appName = "Wizard.app"'),
])
edit(src / "NativeAuthenticationBridge.swift", [
    ('            .appendingPathComponent("Try Omarchy", isDirectory: true)', '            .appendingPathComponent("Wizard", isDirectory: true)'),
])
edit(src / "StorageLocation.swift", [('    static let workspaceDirectoryName = "Try Omarchy"', '    static let workspaceDirectoryName = "Wizard"')])
edit(src / "main.swift", [('                applicationName: "Try Omarchy",', '                applicationName: "Wizard",')])
edit(src / "FocusedCommandSuperBridge.swift", [('        if name == "Try Omarchy" {', '        if name == "Wizard" {')])
edit(src / "StartMenuWindow.swift", [
    ('    static let requiredText = "Try Omarchy"', '    static let requiredText = "Wizard"'),
    ('        window.title = "Try Omarchy"', '        window.title = "Wizard"'),
    ('virtualMachineRunning ? "Try Omarchy Settings" : "Try Omarchy"', 'virtualMachineRunning ? "Wizard Settings" : "Wizard"'),
])

# Remaining visible copy in the launcher UI: plain-text product name swap in string literals.
for path in [src / "StartMenuWindow.swift", src / "StartMenuPresentation.swift", src / "VMApplicationController.swift",
             src / "OmarchyLauncherControls.swift"]:
    if not path.exists():
        continue
    text = path.read_text()
    out = re.sub(r'"([^"\n]*?)Try Omarchy([^"\n]*?)"', lambda m: f'"{m.group(1)}Wizard{m.group(2)}"', text)
    out = re.sub(r'"([^"\n]*?)Launch Omarchy([^"\n]*?)"', lambda m: f'"{m.group(1)}Open Wizard{m.group(2)}"', out)
    out = re.sub(r'"([^"\n]*?)Start Omarchy([^"\n]*?)"', lambda m: f'"{m.group(1)}Open Wizard{m.group(2)}"', out)
    if out != text:
        path.write_text(out)
        print(f"rebranded copy in {path.relative_to(repo)}")

# Auto-start by default once a Wizard exists: the app should feel like an app.
edit(src / "StartupPreferenceStore.swift", [
    ("        guard let storageRoot else { return false }\n        if let pending = pendingChoices[storageRoot] { return pending }\n",
     "        guard let storageRoot else { return true }\n        if let pending = pendingChoices[storageRoot] { return pending }\n"),
    ("              payload.schemaVersion == 1 else { return false }\n",
     "              payload.schemaVersion == 1 else { return true }\n"),
])


# Never poll Try Omarchy's GitHub releases from a Wizard build.
edit(src / "AppReleaseChecker.swift", [
    ("    func checkAutomaticallyIfDue() {\n        guard preferences.shouldCheckAutomatically(now: now()) else { return }\n",
     "    func checkAutomaticallyIfDue() {\n        return  // Wizard Desktop: no upstream update polling\n        guard preferences.shouldCheckAutomatically(now: now()) else { return }\n"),
])
for path in [src / "AppRelease.swift", src / "AppReleaseWindow.swift", src / "ApplicationPresentation.swift",
             src / "NativeAuthenticationBridge.swift"]:
    text = path.read_text()
    out = re.sub(r'"([^"\n]*?)Try Omarchy([^"\n]*?)"', lambda m: f'"{m.group(1)}Wizard{m.group(2)}"', text)
    if out != text:
        path.write_text(out)
        print(f"rebranded copy in {path.relative_to(repo)}")


# Wizard is an app, not a VM manager: open straight into the Wizard on every launch
# (Option-key held still shows the start menu, reset/ephemeral still respected).
edit(src / "StartupPreferenceStore.swift", [
    ("        return isEnabled && hasExistingVM && !optionKeyHeld && !resetRequested\n",
     "        _ = isEnabled; _ = hasExistingVM  // Wizard Desktop: always open straight into the Wizard\n        return !optionKeyHeld && !resetRequested\n"),
])

# 3. icon ----------------------------------------------------------------------
(mac / "WizardIcon.svg").write_text("""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#1b1640"/>
      <stop offset="1" stop-color="#0b0b12"/>
    </linearGradient>
    <linearGradient id="hat" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#b9a6ff"/>
      <stop offset="1" stop-color="#6d4dff"/>
    </linearGradient>
  </defs>
  <rect x="100" y="100" width="824" height="824" rx="191" fill="url(#bg)" stroke="#8b7bff" stroke-opacity="0.35" stroke-width="4"/>
  <path d="M512 210 L700 690 L324 690 Z" fill="url(#hat)"/>
  <rect x="262" y="672" width="500" height="62" rx="31" fill="#e9e7f5"/>
  <circle cx="560" cy="430" r="22" fill="#fff6c9"/>
  <circle cx="470" cy="540" r="14" fill="#fff6c9"/>
  <circle cx="600" cy="590" r="10" fill="#fff6c9"/>
</svg>
""")
print("wrote WizardIcon.svg")
# DMG: Wizard volume and file names.
edit(mac / "package-dmg.sh", [
    ('working_volume_name="Try Omarchy ${work_dir##*/}"', 'working_volume_name="Wizard ${work_dir##*/}"'),
    ('diskutil rename "$mount_dir" "Try Omarchy" >/dev/null', 'diskutil rename "$mount_dir" "Wizard" >/dev/null'),
    ('    --identifier dev.tryomarchy.native.disk-image \\', '    --identifier com.aiwizards.desktop.disk-image \\'),
])
edit(mac / "build-app.sh", [
    ('  dmg="$repo_dir/dist/TryOmarchy.dmg"', '  dmg="$repo_dir/dist/Wizard.dmg"'),
])

# Ask for Accessibility once on first launch so Command-C/V/Z work as on a Mac.
edit(src / "VMApplicationController.swift", [
    ("        prepareStartMenu(startAutomatically: startAutomatically)\n        appReleaseChecker.checkAutomaticallyIfDue()",
     "        prepareStartMenu(startAutomatically: startAutomatically)\n"
     "        if !AXIsProcessTrusted(), !UserDefaults.standard.bool(forKey: \"wizardAccessibilityAsked\") {\n"
     "            UserDefaults.standard.set(true, forKey: \"wizardAccessibilityAsked\")\n"
     "            requestOptionalAccessibilityPermission()\n"
     "        }\n"
     "        appReleaseChecker.checkAutomaticallyIfDue()"),
])

# Stage the DMG on the build volume (TMPDIR) instead of the system disk.
edit(mac / "package-dmg.sh", [
    ('work_dir=$(mktemp -d /private/tmp/omarchy-dmg.XXXXXX)', 'work_dir=$(mktemp -d "${TMPDIR:-/private/tmp}/omarchy-dmg.XXXXXX")'),
])

# Windowed by default: Wizard is a Mac app window, not a takeover. Full screen
# stays one chord away (green button, View menu, Ctrl-Cmd-F).
edit(src / "FullscreenPreferences.swift", [
    ("    static let defaults = Self(isImmersive: true)\n", "    static let defaults = Self(isImmersive: false)\n"),
])
edit(src / "VMApplicationController.swift", [
    ("                self?.fullscreenPreferenceStore.load().isImmersive ?? true\n",
     "                self?.fullscreenPreferenceStore.load().isImmersive ?? false\n"),
])
edit(src / "StartMenuPresentation.swift", [
    ('            ? "Omarchy opens Full Screen with the Mac menu bar and Dock hidden."\n',
     '            ? "Wizard opens Full Screen with the Mac menu bar and Dock hidden."\n'),
    ('            : "Omarchy opens in a window with the Mac menu bar and Dock available."\n',
     '            : "Wizard opens in a resizable window, like any Mac app."\n'),
])
edit(mac / "run-qemu-gpu.sh", [
    ("case ${OMARCHY_QEMU_GPU_IMMERSIVE:-1} in\n", "case ${OMARCHY_QEMU_GPU_IMMERSIVE:-0} in\n"),
])

# Native window behaviour inside QEMU's Cocoa front end (host chords, Ctrl-Cmd-F,
# remembered window frame, product name). Applied after Try Omarchy's own patches.
cocoa_edit = Path(__file__).with_name("wizard-cocoa-edit.py")
(mac / "patches" / "wizard-cocoa-edit.py").write_text(cocoa_edit.read_text())
edit(mac / "build-qemu-gpu-runtime.sh", [
    ('patch -d "$source_dir" -p1 -f -i "$usb_exact_bus_patch"\n',
     'patch -d "$source_dir" -p1 -f -i "$usb_exact_bus_patch"\n'
     '/usr/bin/python3 "$native_dir/patches/wizard-cocoa-edit.py" "$source_dir/ui/cocoa.m"\n'),
    # Big QEMU/ANGLE scratch builds go to TMPDIR (a roomy volume), and cleanup accepts it.
    ("work_dir=$(mktemp -d /private/tmp/omarchy-qemu-source-build.XXXXXX)\n",
     'work_dir=$(mktemp -d "${TMPDIR:-/private/tmp}/omarchy-qemu-source-build.XXXXXX")\n'),
    ("  [[ $path == /private/tmp/omarchy-qemu-source-build.* ]] || \\\n",
     "  [[ $path == */omarchy-qemu-source-build.* ]] || \\\n"),
])

print("WIZARD_PATCH_OK")
