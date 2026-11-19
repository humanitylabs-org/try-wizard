import Foundation

/// The app's name on disk (try-wizard#124). Builds before 0.8.0 shipped as `Wizard MVP.app`, and Sparkle updates an
/// app in place under the name it already has, so Macs that updated from those builds still show "Wizard MVP" in the
/// Dock, Cmd-Tab, Finder, Mission Control and Privacy & Security, even though the bundle now says WizardOS.
/// The app renames its own bundle, once, to `WizardOS.app` in the same folder, and only when nothing can be holding
/// the old path: the Host is not running, no other copy of the app is open and no update is half way.
/// Only the .app is renamed: the bundle id, the `Wizard MVP` data folder in Application Support (kept so installed
/// Macs find their data) and every setting stay where they are.
enum WizardBundleName {
    /// Legacy on-disk name of installs from before 0.8.0. Kept only to recognise them; never shown.
    static let legacyFileName = "Wizard MVP.app"
    static let fileName = "WizardOS.app"
    /// Update phases that still point at the current path (WizardUpdater's transaction.json).
    static let updateInFlightPhases: Set<String> = ["prepared", "installing", "guest-activating"]

    struct Facts {
        var bundle: URL
        var hostRunning: Bool
        var otherAppRunning: Bool
        var updatePhase: String?
    }

    /// Where the bundle should move to, or nil to leave it as it is.
    static func renameTarget(_ f: Facts, exists: (String) -> Bool, writable: (String) -> Bool) -> URL? {
        let bundle = f.bundle.standardizedFileURL
        guard bundle.lastPathComponent == legacyFileName,
              !f.hostRunning, !f.otherAppRunning,
              !updateInFlightPhases.contains(f.updatePhase ?? "") else { return nil }
        let parent = bundle.deletingLastPathComponent()
        // A translocated or read-only copy (DMG, quarantine) can't be renamed and is not the installed app.
        guard !parent.path.contains("/AppTranslocation/"), writable(parent.path) else { return nil }
        let target = parent.appendingPathComponent(fileName, isDirectory: true)
        // Never replace or merge into another app already called WizardOS.app.
        guard !exists(target.path) else { return nil }
        return target
    }

    /// Moves the bundle (a rename in the same folder). Returns false and leaves it in place on any error.
    static func rename(_ bundle: URL, to target: URL, fileManager fm: FileManager = .default) -> Bool {
        do { try fm.moveItem(at: bundle, to: target); return true } catch { return false }
    }
}
