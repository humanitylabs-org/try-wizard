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
    func prepareFresh() {
        do {
            guard !HostControl.isRunning else { throw WizardUpdate.error("Stop Wizard Host before completing this fresh installation") }
            let owner = WizardDiskOwnership(); try owner.acquire(); defer { owner.release() }
            let app = Bundle.main.bundleURL
            let release = try WizardRelease.read(app); try release.validate(app)
            let manifest = WizardUpdate.json(WizardShared.osDir.appendingPathComponent("manifest.json"))
            let abi = try WizardGuestABI.image(manifest)
            let payload = app.appendingPathComponent("Contents/Resources/GuestUpdate")
            try WizardGuestABI.payload(payload, abi: abi)
            let nonce = UUID().uuidString
            var journal: [String: Any] = ["kind": "fresh", "phase": "fresh-placed", "nonce": nonce,
                "dataHome": WizardShared.supportDir.path, "diskIdentity": WizardShared.diskIdentity,
                "appPath": app.path, "releaseID": release.releaseID, "guestABI": abi,
                "legacyCold": abi == 0, "applyGuest": true]
            try WizardUpdate.write(journal, WizardUpdate.journal)
            try Self.snapshotStoppedDisk()
            if abi >= 1 && !WizardGuestABI.requiresFreshApply(baked: manifest["payloadID"] as? String, bundled: release.payloadID) {
                try WizardUpdate.write(["releaseID": release.releaseID, "payloadID": release.payloadID!,
                    "payloadBuild": release.build, "diskIdentity": WizardShared.diskIdentity,
                    "transactionNonce": nonce, "systemOwner": "host-payload"], WizardUpdate.dir.appendingPathComponent("guest-receipt.json"))
                journal["phase"] = "guest-activated"
                try WizardUpdate.write(journal, WizardUpdate.journal)
                onDone(nil); return
            }
            journal["phase"] = "fresh-prepared"
            try WizardUpdate.write(journal, WizardUpdate.journal)
            if abi == 0 { try WizardUpdate.write(["token": nonce, "admission": "cold-pid1"], WizardUpdate.maintenanceJournal) }
        } catch { onDone("Fresh installation could not be prepared safely — \(error.localizedDescription)"); return }
        activate()
    }

    func activate() {
        guard WizardUpdate.json(WizardUpdate.journal)["applyGuest"] as? Bool == true, WizardShared.osInstalled,
              FileManager.default.fileExists(atPath: Self.backup.path), !HostControl.isRunning else {
            onDone("Guest activation prerequisite failed; prior disk retained"); return
        }
        do {
            var journal = WizardUpdate.json(WizardUpdate.journal)
            let release = try WizardRelease.read(Bundle.main.bundleURL)
            try WizardGuestABI.requireSystemOwner(WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-receipt.json")),
                diskIdentity: WizardShared.diskIdentity, incomingBuild: release.build)
            journal["maintenanceCold"] = true
            let token = journal["nonce"] as? String ?? ""
            guard UUID(uuidString: token) != nil else { throw WizardUpdate.error("Missing maintenance transaction token") }
            try WizardUpdate.write(["token": token, "admission": "cold-pid1"], WizardUpdate.maintenanceJournal)
            journal["phase"] = "guest-activating"
            try WizardUpdate.write(journal, WizardUpdate.journal)
            guard WizardShared.guestUpdatePayload != nil else { throw WizardUpdate.error("Guest payload validation failed") }
            onProgress("Starting local software activation; your disk, accounts and chats stay in place…")
            // Capture the boot boundary before launching: a fast Host may already
            // have written its first output by the time ensureRunning returns.
            let bootStart = Date()
            waitingNoticeShown = false
            HostControl.ensureRunning()
            if WizardShared.coldBootstrapToken != nil {
                waitColdBoot(since: bootStart); return
            }
            HostControl.waitForLocalWizard(timeout: 300, tick: { _ in }) { ready in
                guard ready else { self.finish("Guest did not become ready for migration"); return }
                self.migrate()
            }
        } catch { onDone(error.localizedDescription) }
    }
    /// The fence budget (150 s) counts from the VM's first console output, not from launching the Host. macOS can
    /// hold the VM start behind a permission prompt (a shared folder in Documents, asked for by the Virtualization
    /// service, not by this app) for as long as the owner takes to answer. Counting that wait used to fail the upgrade.
    private var waitingNoticeShown = false
    private func waitColdBoot(since start: Date) {
        let console = WizardShared.logsDir.appendingPathComponent("console.log")
        let attributes = try? FileManager.default.attributesOfItem(atPath: console.path)
        let written = (attributes?[.size] as? NSNumber)?.intValue ?? 0
        let modified = attributes?[.modificationDate] as? Date ?? .distantPast
        // The Host truncates the console before each boot. Both ordinary output
        // and cold verdicts must be newer than this activation's launch boundary;
        // a retained verdict is not evidence that the new VM has started.
        if written > 0 && modified >= start {
            waitingNoticeShown = false; waitColdStarted(Date().addingTimeInterval(150)); return
        }
        let status = WizardUpdate.json(WizardShared.statusFile)
        if status["state"] as? String == "error", (status["updatedAt"] as? Double ?? 0) >= start.timeIntervalSince1970 {
            finish(status["error"] as? String ?? "Wizard OS could not start; restoring the stopped disk"); return
        }
        let waited = Date().timeIntervalSince(start)
        guard waited < 900 else { finish("Wizard OS did not start within 15 minutes; restoring the stopped disk"); return }
        if waited > 3 && !waitingNoticeShown {
            waitingNoticeShown = true
            onProgress("Waiting for macOS to start Wizard's computer. If it asks whether Wizard may access a folder, click Allow.")
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.waitColdBoot(since: start) }
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
                let ownership = WizardDiskOwnership(); try ownership.acquire()
                defer { ownership.release() }
                guard !HostControl.isRunning, !HostControl.hasForeignRunner else { throw WizardUpdate.error("Another Host appeared; no disk restored") }
                var journal = WizardUpdate.json(WizardUpdate.journal)
                // Recovery and successful completion must refer to the same disk
                // admitted before maintenance. Compare under the ownership lock,
                // before touching the rollback staging file or either receipt.
                try WizardDiskIdentity.requireColdOwner(journal)
                if let migrationError {
                    let disk = WizardShared.osDir.appendingPathComponent("disk.img")
                    let restored = WizardUpdate.dir.appendingPathComponent("restore-disk.img")
                    try? FileManager.default.removeItem(at: restored)
                    guard clonefile(Self.backup.path, restored.path, 0) == 0 else { throw WizardUpdate.error("Rollback clone failed") }
                    // Record the intentional inode transition BEFORE the atomic
                    // replacement, so even a crash at rename leaves explicit evidence.
                    if journal["kind"] as? String == "legacy-cold" || journal["legacyCold"] as? Bool == true {
                        guard let target = WizardDiskIdentity.read(restored) else { throw WizardUpdate.error("Rollback identity unavailable") }
                        journal["rollbackIdentityTransition"] = ["from": journal["diskIdentity"] as? String ?? "", "to": target]
                        try WizardUpdate.write(journal, WizardUpdate.journal)
                    }
                    guard rename(restored.path, disk.path) == 0 else { throw WizardUpdate.error("Rollback disk activation failed") }
                    if let transition = journal["rollbackIdentityTransition"] as? [String: String] {
                        journal["diskIdentity"] = transition["to"]
                    }
                    journal["phase"] = "guest-rolled-back"; journal["error"] = migrationError
                    try WizardUpdate.write(journal, WizardUpdate.journal)
                    if journal["kind"] as? String == "legacy-cold" || journal["legacyCold"] as? Bool == true {
                        try? FileManager.default.removeItem(at: WizardUpdate.maintenanceJournal)
                        try? FileManager.default.removeItem(at: WizardUpdate.dir.appendingPathComponent("guest-receipt.json"))
                        onDone("Prior guest restored and left stopped — \(migrationError)"); return
                    }
                } else {
                    guard let identity = WizardDiskIdentity.read(WizardShared.osDir.appendingPathComponent("disk.img")),
                          let nonce = journal["nonce"] as? String, !nonce.isEmpty else { throw WizardUpdate.error("Activation disk binding unavailable") }
                    let receiptURL = WizardUpdate.dir.appendingPathComponent("guest-receipt.json")
                    var receipt = WizardUpdate.json(receiptURL)
                    let release = try WizardRelease.read(Bundle.main.bundleURL)
                    receipt["payloadID"] = release.payloadID; receipt["payloadBuild"] = release.build
                    receipt["systemOwner"] = "host-payload"
                    receipt["diskIdentity"] = identity; receipt["transactionNonce"] = nonce
                    try WizardUpdate.write(receipt, receiptURL)
                    journal["diskIdentity"] = identity; journal["phase"] = "guest-activated"
                    try WizardUpdate.write(journal, WizardUpdate.journal)
                    if journal["kind"] as? String == "legacy-cold" || journal["legacyCold"] as? Bool == true {
                        // Admission for normal boot, not a live-runtime health claim.
                        let completion = try WizardDiskIdentity.completionRecord(journal)
                        try WizardUpdate.write(completion, WizardUpdate.dir.appendingPathComponent("legacy-complete.json"))
                    }
                }
                try? FileManager.default.removeItem(at: WizardUpdate.request)
                ownership.release()
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
            if migrationError == nil {
                let journal = WizardUpdate.json(WizardUpdate.journal)
                let health = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("apps-health.json"))
                guard health["nonce"] as? String == journal["nonce"] as? String, health["ok"] as? Bool == true else {
                    HostControl.send("verify-apps-after-update"); retry(); return
                }
            }
            self.onDone(migrationError.map { "Prior guest restored — \($0)" })
        }
    }
}
