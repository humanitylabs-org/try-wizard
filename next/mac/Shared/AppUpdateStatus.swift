import Foundation

/// The Mac app's own update state for the page (try-wizard#126), on for every Mac.
///
/// The bar at the top of the window used to be the only place that showed Sparkle's progress, so an owner who
/// pressed Later had no way back but the menu, and Settings couldn't say which Wizard for Mac version runs. The
/// native bridge answers `updates.status` with `object(...)` below and pushes the same object as the
/// window event `wizard:app-update` each time the bar changes.
///
/// Some releases can't install themselves (a change Sparkle can't apply in place, an old updater, a signing change).
/// Sparkle marks those items information-only (`<sparkle:informationalUpdate>`). Wizard then remembers the version
/// and its download page (`ManualRecord`, kept in updates/manual.json beside ui.json) until the installed build
/// reaches it, and the bar offers Download. Only aiwizards.com download pages ever open (`allowsDownload`).
enum WizardAppUpdateStatus {
    static let schema = 1
    static let event = "wizard:app-update"
    static let phases = ["idle", "checking", "current", "downloading", "verifying", "ready", "installing", "manual", "failed"]
    static let defaultDownloadURL = "https://www.aiwizards.com/downloads"
    static let allowedHosts: Set<String> = ["www.aiwizards.com", "downloads.aiwizards.com"]

    /// The bar's own states (WizardUpdater.show) in the page's words.
    /// - ready: Sparkle holds a downloaded update; manual: a release that needs a new download is remembered.
    static func phase(_ state: String, ready: Bool, manual: Bool) -> String {
        switch state {
        case "checking": return "checking"
        case "available", "downloading": return "downloading"
        case "verifying": return "verifying"
        case "ready", "guest-pending": return "ready"
        case "busy": return ready ? "ready" : (manual ? "manual" : "idle")
        case "installing", "stopping", "activating", "guest-activating", "recovering": return "installing"
        case "manual": return "manual"
        case "failed", "host-recovery": return "failed"
        case "current", "installed": return manual ? "manual" : "current"
        default: return ready ? "ready" : (manual ? "manual" : "idle")
        }
    }

    /// Only https pages on Wizard's own download hosts; no other host, port, user or scheme.
    static func allowsDownload(_ text: String?) -> Bool {
        guard let text, let parts = URLComponents(string: text), parts.scheme?.lowercased() == "https",
              let host = parts.host?.lowercased(), allowedHosts.contains(host),
              parts.user == nil, parts.password == nil, parts.port == nil || parts.port == 443 else { return false }
        return true
    }

    /// The download page of an information-only item: its `<link>` when that is one of ours, else the downloads page.
    static func manualURL(link: String?) -> String { allowsDownload(link) ? link! : defaultDownloadURL }

    /// Sparkle versions here are build numbers (`sparkle:version` = CFBundleVersion).
    static func isOlder(_ installed: String, than other: String) -> Bool {
        installed.compare(other, options: .numeric) == .orderedAscending
    }

    struct ManualRecord: Equatable {
        let version: String   // shown to the owner, e.g. 0.9.0
        let build: String     // Sparkle's version, compared with CFBundleVersion
        let url: String

        var json: [String: Any] { ["schema": WizardAppUpdateStatus.schema, "version": version, "build": build, "url": url] }

        /// A stored record still applies only while the installed build is older and its page is one of ours.
        static func read(_ json: [String: Any], installedBuild: String) -> ManualRecord? {
            guard let build = json["build"] as? String, !build.isEmpty,
                  let url = json["url"] as? String, WizardAppUpdateStatus.allowsDownload(url),
                  WizardAppUpdateStatus.isOlder(installedBuild, than: build) else { return nil }
            let version = (json["version"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? build
            return ManualRecord(version: version, build: build, url: url)
        }
    }

    /// The bar text for a release that needs a new download.
    static func manualText(_ version: String) -> String { "Wizard for Mac \(version) needs a new download" }

    /// Why `updates.install` can't start now, in plain words; nil means it goes the bar's Update and restart way.
    static func installRefusal(ready: Bool, finishPending: Bool, preparing: Bool, recording: Bool, work: Bool,
                               foreignHost: Bool) -> String? {
        if preparing { return "An update is already being prepared." }
        guard ready || finishPending else { return "No update is ready to install." }
        if recording { return "Recording is on. Update after it ends." }
        if work { return "Wizard is working. Update after it finishes." }
        if foreignHost { return "Another Wizard Host is running. Close it, then update." }
        return nil
    }

    /// The `updates.status` answer and the `wizard:app-update` detail. JSON-ready: a missing value is NSNull.
    /// `urgent` (try-wizard#128, switch UpdateDeadlines): the coming release is critical. Only then does the object
    /// carry `"urgent": true`, and only while that release is on its way or ready; otherwise the key is absent, so the
    /// object is exactly what it was before.
    static func object(installedVersion: String, installedBuild: String, phase: String,
                       latest: (version: String, build: String)?, progress: Double?, checkedAt: Date?,
                       waitingFor: String?, manualURL: String?, error: String?, channel: String? = nil,
                       urgent: Bool = false) -> [String: Any] {
        func value(_ v: Any?) -> Any { v ?? NSNull() }
        let showsLatest = latest.map { !$0.build.isEmpty } == true && ["downloading", "verifying", "ready", "installing", "manual"].contains(phase)
        var object: [String: Any] = [
            "schema": schema,
            "installed": ["version": installedVersion, "build": installedBuild],
            "phase": phases.contains(phase) ? phase : "idle",
            "latest": showsLatest ? ["version": latest!.version.isEmpty ? latest!.build : latest!.version, "build": latest!.build] as Any : NSNull(),
            "progress": value(["downloading", "verifying"].contains(phase) ? progress.map { min(1, max(0, ($0 * 100).rounded() / 100)) } : nil),
            "checkedAt": value(checkedAt.map { Int64(($0.timeIntervalSince1970 * 1000).rounded()) }),
            "waitingFor": value(phase == "ready" && ["recording", "work"].contains(waitingFor ?? "") ? waitingFor : nil),
            "manual": phase == "manual" && allowsDownload(manualURL) ? ["url": manualURL!] as Any : NSNull(),
            "error": value(phase == "failed" ? error : nil),
            "channel": value(channel),
        ]
        if urgent && showsLatest && phase != "manual" { object["urgent"] = true }
        return object
    }
}
