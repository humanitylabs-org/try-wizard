import AppKit
import Darwin

/// One bounded migration, executed from the authenticated installed bundle.
/// Never replaces disk with a factory image, never touches a remote backend.
@MainActor final class WizardGuestActivation {
    static let shared = WizardGuestActivation()
    var onProgress: (String) -> Void = { _ in }
    var onDone: (String?) -> Void = { _ in }
    static var backup: URL { WizardUpdate.dir.appendingPathComponent("previous-disk.img") }
    static func snapshotStoppedDisk() throws {
        guard !HostControl.isRunning, !HostControl.hasForeignRunner else { throw WizardUpdate.error("Refusing snapshot while any Wizard Host is running") }
        let disk = WizardShared.osDir.appendingPathComponent("disk.img")
        guard FileManager.default.fileExists(atPath: disk.path) else { return }
        try? FileManager.default.removeItem(at: backup)
        guard clonefile(disk.path, backup.path, 0) == 0 else { throw WizardUpdate.error("APFS stopped-disk rollback clone failed — update deferred (\(errno))") }
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: backup.path)
    }
    func activate() {
        guard WizardUpdate.json(WizardUpdate.journal)["applyGuest"] as? Bool == true, WizardShared.osInstalled,
              FileManager.default.fileExists(atPath: Self.backup.path), !HostControl.isRunning else {
            onDone("Guest activation prerequisite failed; prior disk retained"); return
        }
        do {
            var journal = WizardUpdate.json(WizardUpdate.journal)
            journal["phase"] = "guest-activating"
            try WizardUpdate.write(journal, WizardUpdate.journal)
            guard WizardShared.guestUpdatePayload != nil else { throw WizardUpdate.error("Guest payload validation failed") }
            onProgress("Starting local software activation; your disk, accounts and chats stay in place…")
            HostControl.ensureRunning()
            if WizardShared.coldBootstrapToken != nil {
                waitColdStarted(Date().addingTimeInterval(150)); return
            }
            HostControl.waitForLocalWizard(timeout: 300, tick: { _ in }) { ready in
                guard ready else { self.finish("Guest did not become ready for migration"); return }
                self.migrate()
            }
        } catch { onDone(error.localizedDescription) }
    }
    private func waitColdStarted(_ deadline: Date) {
        let log = (try? String(contentsOf: WizardShared.logsDir.appendingPathComponent("console.log"), encoding: .utf8)) ?? ""
        if log.contains("WIZARD_COLD_FAILED") { finish("Cold admission refused the legacy layout; restoring stopped disk"); return }
        if HostControl.isRunning && log.contains("WIZARD_COLD_FENCED") { migrate(); return }
        guard Date() < deadline else { finish("Cold bootstrap did not establish its launch fence"); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.waitColdStarted(deadline) }
    }
    func recoverInterruptedActivation() {
        // Do not infer success from a partial journal or replay an interrupted migration.
        finish("Interrupted local software activation")
    }
    private func migrate() {
        onProgress("Activating verified local Wizard software…")
        do {
            let nonce = UUID().uuidString
            try WizardUpdate.write(["nonce": nonce, "pid": getpid(), "peer": WizardRelease.peer, "expires": Date().timeIntervalSince1970 + 1000, "appPath": Bundle.main.bundleURL.standardizedFileURL.path], WizardUpdate.dir.appendingPathComponent("guest-command.json"))
            HostControl.send("apply-guest-update")
            waitApplied(nonce, Date().addingTimeInterval(950))
        } catch { finish(error.localizedDescription) }
    }
    private func waitApplied(_ nonce: String, _ deadline: Date) {
        let reply = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-response.json"))
        if reply["nonce"] as? String == nonce {
            if reply["state"] as? String == "failed" { finish(reply["error"] as? String ?? "Guest migration failed; private log retained"); return }
            if reply["state"] as? String == "applied", let receipt = reply["receipt"] as? [String: Any] {
                do { try WizardUpdate.write(receipt, WizardUpdate.dir.appendingPathComponent("guest-receipt.json")) }
                catch { finish("Could not retain guest activation receipt"); return }
                // The authenticated receipt is produced while executable admission is
                // held. Live-agent health is deliberately unavailable until the
                // maintenance VM stops and the normal Host releases that lease.
                finish(nil)
                return
            }
        }
        guard Date() < deadline else { finish("Guest migration did not finish within its bounded window"); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.waitApplied(nonce, deadline) }
    }
    private func finish(_ error: String?) {
        onProgress(error == nil ? "Software activated; restarting without maintenance access…" : "Activation failed; stopping safely to restore the prior disk…")
        if !HostControl.isRunning { completeStopped(error); return }
        do {
            let nonce = UUID().uuidString
            try WizardUpdate.write(["nonce": nonce, "pid": getpid(), "peer": WizardRelease.peer, "expires": Date().timeIntervalSince1970 + 110, "appPath": Bundle.main.bundleURL.standardizedFileURL.path, "maintenance": true], WizardUpdate.request)
            HostControl.send("prepare-update")
            waitStopped(nonce, Date().addingTimeInterval(105), error)
        } catch { onDone("Could not stop maintenance guest — retained rollback disk; \(error.localizedDescription)") }
    }
    private func waitStopped(_ nonce: String, _ deadline: Date, _ migrationError: String?) {
        let response = WizardUpdate.json(WizardUpdate.response)
        if response["nonce"] as? String == nonce, response["state"] as? String == "failed" { onDone("Guest shutdown failed; no live disk restored, rollback copy retained"); return }
        if response["nonce"] as? String == nonce, response["state"] as? String == "stopped", !HostControl.isRunning {
            completeStopped(migrationError)
            return
        }
        guard Date() < deadline else { onDone("Clean guest shutdown not confirmed; no live disk restored, prior disk retained"); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.waitStopped(nonce, deadline, migrationError) }
    }
    private func completeStopped(_ migrationError: String?) {
            do {
                guard !HostControl.isRunning, !HostControl.hasForeignRunner else { throw WizardUpdate.error("Another Host appeared; no disk restored") }
                if let migrationError {
                    let ownership = WizardDiskOwnership(); try ownership.acquire()
                    defer { ownership.release() }
                    let disk = WizardShared.osDir.appendingPathComponent("disk.img")
                    let restored = WizardUpdate.dir.appendingPathComponent("restore-disk.img")
                    try? FileManager.default.removeItem(at: restored)
                    guard clonefile(Self.backup.path, restored.path, 0) == 0 else { throw WizardUpdate.error("Rollback clone failed") }
                    // Same stopped owner's disk, atomic replacement; hardware IDs/shares/prefs untouched.
                    guard rename(restored.path, disk.path) == 0 else { throw WizardUpdate.error("Rollback disk activation failed") }
                    var journal = WizardUpdate.json(WizardUpdate.journal); journal["phase"] = "guest-rolled-back"; journal["error"] = migrationError
                    try WizardUpdate.write(journal, WizardUpdate.journal)
                    if journal["kind"] as? String == "legacy-cold" {
                        try? FileManager.default.removeItem(at: WizardUpdate.maintenanceJournal)
                        try? FileManager.default.removeItem(at: WizardUpdate.dir.appendingPathComponent("guest-receipt.json"))
                        onDone("Prior guest restored and left stopped — \(migrationError)"); return
                    }
                } else {
                    var journal = WizardUpdate.json(WizardUpdate.journal); journal["phase"] = "guest-activated"
                    try WizardUpdate.write(journal, WizardUpdate.journal)
                }
                try? FileManager.default.removeItem(at: WizardUpdate.request)
                HostControl.ensureRunning()
                HostControl.waitForLocalWizard(timeout: 300, tick: { _ in }) { ready in
                    guard ready else { self.onDone("Normal boot did not pass health checks; prior disk and app remain available"); return }
                    self.waitForNormalRuntime(Date().addingTimeInterval(180), migrationError)
                }
            } catch { onDone("Rollback/activation failed — \(error.localizedDescription); prior disk retained") }
    }
    private func waitForNormalRuntime(_ deadline: Date, _ migrationError: String?) {
        // Host owns lease release and verifies its authenticated response. HTTP200
        // alone does not mean the retained user runtime has resumed.
        let running = HostControl.isRunning && WizardUpdate.json(WizardShared.statusFile)["state"] as? String == "running"
        let held = FileManager.default.fileExists(atPath: WizardUpdate.maintenanceJournal.path)
        func retry() {
            guard Date() < deadline else { self.onDone("Normal runtime did not reconnect after maintenance; prior disk and app remain available"); return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.waitForNormalRuntime(deadline, migrationError) }
        }
        guard running, !held else { retry(); return }
        WizardUpdate.idle { reason in
            guard reason == nil else { retry(); return }
            self.onDone(migrationError.map { "Prior guest restored — \($0)" })
        }
    }
}
