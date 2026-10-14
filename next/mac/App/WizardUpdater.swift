import AppKit
import Sparkle
import Darwin

/// Sparkle owns signature validation, download, atomic replacement and relaunch.
/// Wizard owns the top notice, explicit restart choice and local Host shutdown lease.
@MainActor final class WizardUpdater: NSObject, SPUUserDriver, SPUUpdaterDelegate {
    static let shared = WizardUpdater()
    let view = NSView()
    let label = NSTextField(wrappingLabelWithString: "")
    let action = NSButton(title: "Update and restart", target: nil, action: nil)
    let later = NSButton(title: "Later", target: nil, action: nil)
    var height: NSLayoutConstraint!
    private var updater: SPUUpdater!
    private var ready: ((SPUUserUpdateChoice) -> Void)?
    private var cancel: (() -> Void)?
    private var phase = "idle"
    private var message = ""
    private var version = ""
    private var expected: UInt64 = 0
    private var received: UInt64 = 0
    private var leaseFD: Int32 = -1
    private(set) var restartAuthorized = false
    private var preparing = false
    private var ordinaryQuitPending = false
    var isRecording: () -> Bool = { false }
    // The main page owns manual mic/Right Command takes. Unknown activity
    // defers installation; the trusted page freezes new starts atomically.
    var admitWebRestart: (@escaping (Bool) -> Void) -> Void = { done in done(false) }
    var isPreparing: Bool { preparing || activatingGuest }
    /// Native recorder callbacks are synchronous. Read the live actor-owned
    /// gate only on the main thread; an unexpected background caller defers.
    nonisolated static var captureStartAllowed: Bool {
        guard Thread.isMainThread else { return false }
        return MainActor.assumeIsolated { !shared.isPreparing }
    }
    var onFreeze: (Bool) -> Void = { _ in }
    var qaBusy = false
    private var stoppedHost = false
    private var incomingGuest = false
    private var incomingReleaseID = ""
    private var plannedGuestActivation = false
    private(set) var activatingGuest = false
    var onGuestFinished: () -> Void = {}

    func attach(to root: NSView) -> NSView {
        view.translatesAutoresizingMaskIntoConstraints = false
        view.wantsLayer = true; view.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor
        root.addSubview(view)
        height = view.heightAnchor.constraint(equalToConstant: 0)
        NSLayoutConstraint.activate([view.leadingAnchor.constraint(equalTo: root.leadingAnchor), view.trailingAnchor.constraint(equalTo: root.trailingAnchor), view.topAnchor.constraint(equalTo: root.topAnchor), height])
        label.font = .systemFont(ofSize: 12); label.maximumNumberOfLines = 3
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        action.target = self; action.action = #selector(updateAndRestart)
        later.target = self; later.action = #selector(hideNotice)
        for control in [label, action, later] { control.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(control) }
        NSLayoutConstraint.activate([label.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 14), label.topAnchor.constraint(equalTo: view.topAnchor, constant: 30), label.trailingAnchor.constraint(equalTo: action.leadingAnchor, constant: -8), action.centerYAnchor.constraint(equalTo: label.centerYAnchor), action.trailingAnchor.constraint(equalTo: later.leadingAnchor, constant: -6), later.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -12), later.centerYAnchor.constraint(equalTo: label.centerYAnchor)])
        view.isHidden = true
        return view
    }
    func start() {
        do {
            try WizardRelease.read(Bundle.main.bundleURL).validate(Bundle.main.bundleURL, verifyGuestFiles: false)
            updater = SPUUpdater(hostBundle: .main, applicationBundle: .main, userDriver: self, delegate: self)
            try updater.start()
            if updater.automaticallyChecksForUpdates { updater.checkForUpdatesInBackground() }
            recoverActivation()
        } catch { show("failed", "Updates unavailable — \(error.localizedDescription)", retry: true) }
    }
    @objc func checkForUpdates(_ sender: Any? = nil) {
        guard let updater else { return }
        if ready != nil { show("ready", "Update \(version) available — ready to restart"); return }
        if updater.canCheckForUpdates { updater.checkForUpdates() }
    }
    @objc private func hideNotice() { view.isHidden = true; height.constant = 0 }
    private func show(_ state: String, _ text: String, retry: Bool = false) {
        phase = state; message = text; label.stringValue = text
        view.isHidden = false; height?.constant = 94
        action.title = retry ? "Retry" : "Update and restart"
        action.isEnabled = retry || ready != nil && !preparing
        later.isEnabled = !preparing
        try? WizardUpdate.write(snapshot, WizardUpdate.dir.appendingPathComponent("ui.json"))
    }
    var snapshot: [String: Any] {
        let installed = NSDictionary(contentsOf: Bundle.main.bundleURL.appendingPathComponent("Contents/Info.plist"))?["CFBundleVersion"] as? String ?? "unconfirmed"
        return ["pid": getpid(), "appPath": Bundle.main.bundleURL.path, "phase": phase, "message": message, "version": version, "build": Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") ?? "", "installedBundleBuild": installed, "ready": ready != nil, "restartAuthorized": restartAuthorized, "dataHome": WizardShared.supportDir.path, "hostRunning": HostControl.isRunning, "recording": isRecording(), "visible": !view.isHidden]
    }
    func shouldTerminate() -> NSApplication.TerminateReply {
        if restartAuthorized { return .terminateNow }
        // Sparkle otherwise installs a prepared update on an ordinary quit, outside the Host lease.
        // Cancel the pending installation first; never treat Later as permission to install on quit.
        if preparing { return .terminateCancel }
        if let reply = ready { ordinaryQuitPending = true; ready = nil; reply(.skip); return .terminateCancel }
        if let cancel { ordinaryQuitPending = true; self.cancel = nil; cancel(); return .terminateCancel }
        return .terminateNow
    }
    @objc func updateAndRestart() {
        if ready == nil { checkForUpdates(); return }
        guard !preparing else { return }
        if isRecording() || qaBusy { show("busy", "Recording or agent work is active — update after it finishes"); return }
        if HostControl.hasForeignRunner { show("busy", "Another candidate's Wizard Host is running — close that candidate before updating"); return }
        plannedGuestActivation = incomingGuest && Store.active?.kind == .thisMac && WizardShared.osInstalled
        preparing = true
        admitWebRestart { [weak self] idle in
            guard let self, self.preparing else { return }
            guard idle, !self.isRecording(), !self.qaBusy else {
                self.preparing = false; self.onFreeze(false)
                self.show("busy", "Finish recording or let the chat finish loading before updating")
                return
            }
            self.onFreeze(true)
            self.prepareIdleHost()
        }
    }
    private func prepareIdleHost() {
        WizardUpdate.idle { [weak self] reason in
            guard let self else { return }
            if let reason { self.preparing = false; self.onFreeze(false); self.show("busy", reason); return }
            do {
                try FileManager.default.createDirectory(at: WizardUpdate.dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
                self.leaseFD = open(WizardUpdate.dir.appendingPathComponent("lease").path, O_CREAT | O_RDWR, 0o600)
                guard self.leaseFD >= 0, flock(self.leaseFD, LOCK_EX | LOCK_NB) == 0 else { throw WizardUpdate.error("Another update is already active") }
                let prior = WizardUpdate.dir.appendingPathComponent("previous.app")
                try? FileManager.default.removeItem(at: prior)
                try WizardUpdate.run("/usr/bin/ditto", [Bundle.main.bundleURL.path, prior.path])
                let nonce = UUID().uuidString
                self.stoppedHost = HostControl.isRunning
                try WizardUpdate.write(["nonce": nonce, "pid": getpid(), "peer": WizardRelease.peer, "expires": Date().timeIntervalSince1970 + 110, "appPath": Bundle.main.bundleURL.standardizedFileURL.path], WizardUpdate.request)
                try WizardUpdate.write(["nonce": nonce, "from": Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") ?? "", "to": self.version, "releaseID": self.incomingReleaseID, "guestPatch": self.incomingGuest, "applyGuest": self.plannedGuestActivation, "phase": "prepared", "appPath": Bundle.main.bundleURL.path, "restartHost": self.stoppedHost, "dataHome": WizardShared.supportDir.path, "previous": prior.path], WizardUpdate.journal)
                if !self.stoppedHost { self.install(); return }
                guard WizardUpdate.json(WizardShared.statusFile)["hostProtocol"] as? Int == WizardRelease.peer else { throw WizardUpdate.error("Installed Host needs the updater bootstrap first") }
                HostControl.send("prepare-update")
                self.show("stopping", "Stopping local Wizard OS safely before restarting…")
                self.waitForHost(nonce: nonce, deadline: Date().addingTimeInterval(105))
            } catch { self.fail(error.localizedDescription) }
        }
    }
    private func waitForHost(nonce: String, deadline: Date) {
        let response = WizardUpdate.json(WizardUpdate.response)
        if response["nonce"] as? String == nonce {
            let state = response["state"] as? String
            if state == "failed" || state == "busy" { fail(response["error"] as? String ?? "Host could not stop safely"); return }
            if state == "stopped", !HostControl.isRunning { install(); return }
        }
        guard Date() < deadline else { fail("Host shutdown was not confirmed — prior app remains installed"); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.waitForHost(nonce: nonce, deadline: deadline) }
    }
    private func install() {
        guard !isRecording(), !qaBusy, ready != nil else { fail("Activity started; restart deferred"); return }
        admitWebRestart { [weak self] idle in
            guard let self, self.preparing else { return }
            guard idle, !self.isRecording(), !self.qaBusy else { self.fail("Recording started or its state is unknown; restart deferred"); return }
            self.installApproved()
        }
    }
    private func installApproved() {
        guard !isRecording(), !qaBusy, let reply = ready else { fail("Activity started; restart deferred"); return }
        do {
            if plannedGuestActivation { try WizardGuestActivation.snapshotStoppedDisk() }
        } catch { fail(error.localizedDescription); return }
        restartAuthorized = true; ready = nil; cancel = nil
        var journal = WizardUpdate.json(WizardUpdate.journal); journal["phase"] = "installing"
        do { try WizardUpdate.write(journal, WizardUpdate.journal) } catch { restartAuthorized = false; ready = reply; fail(error.localizedDescription); return }
        show("installing", "Installing update and restarting…")
        reply(.install)
    }
    private func releaseLease() {
        try? FileManager.default.removeItem(at: WizardUpdate.request)
        if leaseFD >= 0 { flock(leaseFD, LOCK_UN); close(leaseFD); leaseFD = -1 }
        preparing = false; onFreeze(false)
    }
    private func fail(_ text: String) {
        restartAuthorized = false; releaseLease()
        var journal = WizardUpdate.json(WizardUpdate.journal)
        if journal["phase"] as? String == "prepared" || journal["phase"] as? String == "installing" { journal["phase"] = "install-failed"; try? WizardUpdate.write(journal, WizardUpdate.journal) }
        if stoppedHost && !HostControl.isRunning { HostControl.ensureRunning() }
        show("failed", "Update failed — \(text). Previous installed app or retained recovery bundle remains available.", retry: ready == nil)
    }
    private func recoverActivation() {
        var journal = WizardUpdate.json(WizardUpdate.journal)
        guard journal["dataHome"] as? String == WizardShared.supportDir.path else { return }
        if journal["phase"] as? String == "guest-activating" {
            activatingGuest = true; preparing = true; onFreeze(true)
            WizardGuestActivation.shared.onProgress = { [weak self] text in self?.show("recovering", text) }
            WizardGuestActivation.shared.onDone = { [weak self] error in
                guard let self else { return }
                self.activatingGuest = false; self.releaseLease(); self.onGuestFinished()
                self.show("failed", error ?? "Interrupted update recovered; prior guest restored")
            }
            WizardGuestActivation.shared.recoverInterruptedActivation()
            return
        }
        guard journal["phase"] as? String == "installing" else {
            if ["prepared", "install-failed", "guest-activated", "guest-rolled-back"].contains(journal["phase"] as? String ?? "") { releaseLease() }
            return
        }
        let current = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? ""
        guard current != journal["from"] as? String else { releaseLease(); show("failed", "Previous app preserved — installation did not complete", retry: true); return }
        do {
            let release = try WizardRelease.read(Bundle.main.bundleURL); try release.validate(Bundle.main.bundleURL)
            guard current == journal["to"] as? String, release.releaseID == journal["releaseID"] as? String,
                  (release.guestPatch != nil) == journal["guestPatch"] as? Bool else { throw WizardUpdate.error("Installed release does not match the approved transaction") }
            if release.guestPatch != nil, journal["applyGuest"] as? Bool == true {
                activatingGuest = true; preparing = true; onFreeze(true)
                WizardGuestActivation.shared.onProgress = { [weak self] text in self?.show("guest-activating", text) }
                WizardGuestActivation.shared.onDone = { [weak self] error in
                    guard let self else { return }
                    self.activatingGuest = false; self.releaseLease(); self.onGuestFinished()
                    self.show(error == nil ? "installed" : "failed", error ?? "Wizard and local software updated — build \(current)")
                }
                WizardGuestActivation.shared.activate()
                return
            }
            releaseLease()
            if journal["restartHost"] as? Bool == true {
                HostControl.ensureRunning()
                show("activating", "Mac app installed; confirming new local Host…")
                confirmNativeHost(build: current, deadline: Date().addingTimeInterval(300))
            } else {
                journal["phase"] = "native-activated"; journal["installedBuild"] = current
                try WizardUpdate.write(journal, WizardUpdate.journal)
                show("installed", "Wizard updated — build \(current)")
            }
        } catch { releaseLease(); show("failed", "New app health failed — previous app retained in updates/previous.app", retry: false) }
    }

    private func confirmNativeHost(build: String, deadline: Date) {
        let status = WizardUpdate.json(WizardShared.statusFile)
        if status["build"] as? String == build, status["hostProtocol"] as? Int == WizardRelease.peer,
           status["dataHome"] as? String == WizardShared.supportDir.path,
           let pid = status["pid"] as? Int32, kill(pid, 0) == 0 {
            if status["state"] as? String == "notInstalled" { nativeActivated(build); return }
            if status["state"] as? String == "running" {
                WizardShared.probeReady { ready in DispatchQueue.main.async {
                    if ready { self.nativeActivated(build) }
                    else { self.retryNativeHost(build, deadline) }
                } }
                return
            }
        }
        retryNativeHost(build, deadline)
    }
    private func retryNativeHost(_ build: String, _ deadline: Date) {
        guard Date() < deadline else { show("failed", "New Host health not confirmed — previous app remains available in updates/previous.app"); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.confirmNativeHost(build: build, deadline: deadline) }
    }
    private func nativeActivated(_ build: String) {
        var journal = WizardUpdate.json(WizardUpdate.journal); journal["phase"] = "native-activated"; journal["installedBuild"] = build; journal["hostBuild"] = build
        do { try WizardUpdate.write(journal, WizardUpdate.journal); show("installed", "Wizard and local Host updated — build \(build)") }
        catch { show("failed", "Installed Host verified; activation receipt could not be saved") }
    }
    func updater(_ updater: SPUUpdater, shouldProceedWithUpdate item: SUAppcastItem, updateCheck: SPUUpdateCheck) throws {
        let properties = item.propertiesDictionary
        guard let text = properties["wizard:contract"] as? String, let data = text.data(using: .utf8),
              let contract = try? JSONDecoder().decode(WizardRelease.self, from: data),
              contract.schema == 1, contract.arch == "arm64", contract.minimumPeer <= WizardRelease.peer,
              contract.hostProtocol == WizardRelease.peer, contract.build == item.versionString,
              !contract.releaseID.isEmpty, item.installationType == "application" else { throw WizardUpdate.error("Incompatible release contract — prior app preserved") }
        try contract.validateMetadata()
        incomingGuest = contract.guestPatch != nil
        incomingReleaseID = contract.releaseID
    }
    func updater(_ updater: SPUUpdater, didAbortWithError error: Error) { if (error as NSError).code != 1001 { show("failed", "Update access unavailable or validation failed — \(error.localizedDescription)", retry: true) } }
    func show(_ request: SPUUpdatePermissionRequest, reply: @escaping (SUUpdatePermissionResponse) -> Void) { reply(SUUpdatePermissionResponse(automaticUpdateChecks: true, sendSystemProfile: false)) }
    func showUserInitiatedUpdateCheck(cancellation: @escaping () -> Void) { cancel = cancellation; show("checking", "Checking for updates…") }
    func showUpdateFound(with item: SUAppcastItem, state: SPUUserUpdateState, reply: @escaping (SPUUserUpdateChoice) -> Void) {
        version = item.versionString
        if item.isInformationOnlyUpdate { show("unavailable", "Update available but cannot be downloaded from this feed"); reply(.dismiss); return }
        show("available", "Update \(item.displayVersionString) available — downloading…")
        // Automatic download; the ready callback below keeps restart under deliberate user control.
        reply(.install)
    }
    func showUpdateReleaseNotes(with downloadData: SPUDownloadData) {}
    func showUpdateReleaseNotesFailedToDownloadWithError(_ error: Error) {}
    func showUpdateNotFoundWithError(_ error: Error, acknowledgement: @escaping () -> Void) { cancel = nil; show("current", "No compatible newer update is available", retry: true); acknowledgement() }
    func showUpdaterError(_ error: Error, acknowledgement: @escaping () -> Void) { cancel = nil; ready = nil; fail(error.localizedDescription); acknowledgement() }
    func showDownloadInitiated(cancellation: @escaping () -> Void) { cancel = cancellation; expected = 0; received = 0; show("downloading", "Update available — downloading…") }
    func showDownloadDidReceiveExpectedContentLength(_ expectedContentLength: UInt64) { expected = expectedContentLength }
    func showDownloadDidReceiveData(ofLength length: UInt64) { received += length; show("downloading", expected > 0 ? "Update available — downloading \(min(100, Int(Double(received) / Double(expected) * 100)))%" : "Update available — downloading…") }
    func showDownloadDidStartExtractingUpdate() { cancel = nil; show("verifying", "Verifying and preparing update…") }
    func showExtractionReceivedProgress(_ progress: Double) { show("verifying", "Preparing update \(Int(progress * 100))%") }
    func showReady(toInstallAndRelaunch reply: @escaping (SPUUserUpdateChoice) -> Void) { cancel = nil; ready = reply; show("ready", "Update \(version) available — ready to restart") }
    func showInstallingUpdate(withApplicationTerminated applicationTerminated: Bool, retryTerminatingApplication: @escaping () -> Void) {
        show("installing", "Installing update and restarting…")
        // Installation handoff is confirmed. Quit ourselves after the deliberate
        // restart lease, rather than depending on a helper's cross-app quit event.
        if restartAuthorized && !applicationTerminated { DispatchQueue.main.async { NSApp.terminate(nil) } }
    }
    func showUpdateInstalledAndRelaunched(_ relaunched: Bool, acknowledgement: @escaping () -> Void) { acknowledgement() }
    func dismissUpdateInstallation() {
        cancel = nil; ready = nil
        if !restartAuthorized { releaseLease() }
        if ordinaryQuitPending { ordinaryQuitPending = false; DispatchQueue.main.async { NSApp.terminate(nil) } }
    }
}
