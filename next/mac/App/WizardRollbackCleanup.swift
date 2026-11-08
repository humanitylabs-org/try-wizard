import Foundation
import Darwin

/// Deletes `updates/previous-disk.img` once a guest update is confirmed good (issue #31).
/// The rule lives in Shared/RollbackRetirement.swift. Off by default; switch it on with
/// `defaults write org.humanitylabs.wizard.mvp RetireRollbackDisk -bool true`.
@MainActor enum WizardRollbackCleanup {
    static var enabled: Bool { UserDefaults.standard.bool(forKey: "RetireRollbackDisk") }
    private static var scheduled = false

    /// Safe to call more than once; one check loop per app run.
    static func start() {
        guard enabled, !scheduled, FileManager.default.fileExists(atPath: WizardGuestActivation.backup.path) else { return }
        scheduled = true
        check(runningDeadline: Date().addingTimeInterval(15 * 60))
    }

    private static func check(runningDeadline: Date) {
        let journal = WizardUpdate.json(WizardUpdate.journal)
        // The journal is last written when the phase becomes guest-activated, so its date is the activation time.
        let activatedAt = (try? FileManager.default.attributesOfItem(atPath: WizardUpdate.journal.path))?[.modificationDate] as? Date
        let running = HostControl.isRunning && !HostControl.hasForeignRunner && !WizardUpdater.shared.isPreparing
            && WizardUpdate.json(WizardShared.statusFile)["state"] as? String == "running"
            && !FileManager.default.fileExists(atPath: WizardUpdate.maintenanceJournal.path)
        let verdict = WizardRollbackRetirement.verdict(
            journal: journal, dataHome: WizardShared.supportDir.path,
            diskIdentity: WizardDiskIdentity.read(WizardShared.osDir.appendingPathComponent("disk.img")),
            legacyComplete: WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("legacy-complete.json")),
            activatedAt: activatedAt, runningNormally: running, now: Date())
        switch verdict {
        case .retire:
            retire()
        case .waitForRunning:
            guard Date() < runningDeadline else { scheduled = false; return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) { check(runningDeadline: runningDeadline) }
        case .waitForGrace(let seconds):
            DispatchQueue.main.asyncAfter(deadline: .now() + seconds + 1) { check(runningDeadline: Date().addingTimeInterval(15 * 60)) }
        case .keep:
            scheduled = false
        }
    }

    private static func retire() {
        scheduled = false
        let url = WizardGuestActivation.backup
        // An APFS clone shares blocks with the live disk, so this is the most the delete can free.
        let allocated = (try? url.resourceValues(forKeys: [.totalFileAllocatedSizeKey]).totalFileAllocatedSize) ?? 0
        do {
            try FileManager.default.removeItem(at: url)
            log("Retired update rollback disk previous-disk.img after a confirmed update; freed up to \(allocated) bytes")
        } catch {
            log("Could not retire update rollback disk previous-disk.img: \(error.localizedDescription)")
        }
    }

    private static func log(_ message: String) {
        let line = "\(ISO8601DateFormatter().string(from: Date())) app: \(message)\n"
        let url = WizardShared.logsDir.appendingPathComponent("host.log")
        if let handle = try? FileHandle(forWritingTo: url) {
            handle.seekToEndOfFile(); handle.write(Data(line.utf8)); try? handle.close()
        } else {
            try? Data(line.utf8).write(to: url)
        }
    }
}
