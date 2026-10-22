import AppKit
import CryptoKit
import Security
import UniformTypeIdentifiers

/// Native-only file transport. URLSession streams files; no whole-bundle Data and no shared Files staging.
/// Reject redirects rather than forwarding a key or archive to a different service.
final class WizardBackupClient: NSObject, URLSessionTaskDelegate {
    let base: URL
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil; config.httpCookieStorage = nil; config.urlCredentialStorage = nil
        config.timeoutIntervalForResource = 14400
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()
    init(base: URL) { self.base = base; super.init() }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }

    func call(_ path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> [String: Any] {
        let request = try WizardBackupContract.request(base: base, path: path, method: method, body: body)
        let (data, response) = try await session.data(for: request)
        return try decode(data, response)
    }
    private func decode(_ data: Data, _ response: URLResponse) throws -> [String: Any] {
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
              let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw BackupFailure("Wizard could not complete the backup request. Check that Wizard OS is running and up to date.")
        }
        return result
    }
    func upload(_ file: URL) async throws -> [String: Any] {
        var request = try WizardBackupContract.request(base: base, path: "upload", method: "POST")
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        let size = try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0 else { throw BackupFailure("This backup file is empty.") }
        request.setValue(String(size), forHTTPHeaderField: "Content-Length")
        let (data, response) = try await session.upload(for: request, fromFile: file)
        return try decode(data, response)
    }
    func download(_ job: [String: Any], to destination: URL) async throws {
        guard let id = job["id"] as? String, let expectedHash = job["sha256"] as? String,
              let expectedBytes = job["total_bytes"] as? NSNumber else { throw BackupFailure("Wizard did not return a complete backup receipt.") }
        let request = try WizardBackupContract.request(base: base, path: "jobs/\(id)/download")
        let (temporary, response) = try await session.download(for: request)
        defer { try? FileManager.default.removeItem(at: temporary) }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw BackupFailure("Backup download did not finish. Keep Wizard open and retry.") }
        try await Task.detached {
            let size = try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            let file = try FileHandle(forReadingFrom: temporary); defer { try? file.close() }
            var hash = SHA256()
            while let data = try file.read(upToCount: 1 << 20), !data.isEmpty { hash.update(data: data) }
            let actual = hash.finalize().map { String(format: "%02x", $0) }.joined()
            guard size == expectedBytes.intValue, actual == expectedHash else { throw BackupFailure("The downloaded backup failed its integrity check. Nothing was saved over your previous backup.") }
            // First copy beside the destination; then atomic replace. Never remove an existing backup before copy succeeds.
            let staging = destination.deletingLastPathComponent().appendingPathComponent(".wizardbackup-\(UUID().uuidString).part")
            defer { try? FileManager.default.removeItem(at: staging) }
            try FileManager.default.copyItem(at: temporary, to: staging)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: staging.path)
            if FileManager.default.fileExists(atPath: destination.path) {
                _ = try FileManager.default.replaceItemAt(destination, withItemAt: staging)
            } else { try FileManager.default.moveItem(at: staging, to: destination) }
        }.value
    }
}

/// Keychain storage is optional and local to this Mac. Secrets are never preferences, logs, or command arguments.
enum WizardBackupKeychain {
    static func save(_ secret: String) throws {
        // A random account ID avoids exposing a fast, unsalted hash of a human passphrase.
        let account = UUID().uuidString
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "Wizard Backup", kSecAttrAccount as String: account]
        var item = query
        item[kSecValueData as String] = Data(secret.utf8)
        item[kSecAttrLabel as String] = "Wizard backup recovery key or passphrase"
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess || status == errSecDuplicateItem else {
            throw BackupFailure("The key could not be saved in Keychain. Keep your own safe copy before continuing.")
        }
    }
}

@MainActor
final class WizardBackupController: NSObject, NSMenuItemValidation {
    let client = WizardBackupClient(base: WizardShared.localSetupURL)
    var isLocal: () -> Bool = { false }
    var wizardName: () -> String = { "Wizard" }
    var didRestore: () -> Void = {}
    private var supported = false
    private var busy = false
    private var refreshing = false
    private var items: [NSMenuItem] = []
    private var note: NSMenuItem?
    private var timer: Timer?
    private var progress: NSPanel?
    private var progressLabel: NSTextField?

    func install(in menu: NSMenu) {
        menu.addItem(.separator())
        for (title, selector) in [("Back Up This Wizard…", #selector(backUp)),
            ("Restore a Wizard Backup…", #selector(restore)), ("Undo Last Restore", #selector(undo)),
            ("Make This My Active Wizard…", #selector(activate))] {
            let item = menu.addItem(withTitle: title, action: selector, keyEquivalent: "")
            item.target = self; items.append(item)
        }
        let item = NSMenuItem(title: "Backup needs Wizard OS update", action: nil, keyEquivalent: "")
        item.isEnabled = false; menu.addItem(item); note = item
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.refresh() }
        }
        Task { await refresh() }
    }
    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool { supported && isLocal() && !busy }
    func refresh() async {
        guard !refreshing, !busy else { return }
        refreshing = true; defer { refreshing = false }
        let local = isLocal()
        let info = local ? (try? await client.call("capabilities")) : nil
        supported = (info?["version"] as? Int) == 1
        for item in items { item.isEnabled = supported && local }
        note?.title = local ? "Backup needs Wizard OS update" : "Select This Mac to back up or restore"
        note?.isHidden = supported && local
    }
    private func alert(_ title: String, _ message: String, buttons: [String] = ["OK"]) -> NSAlert {
        let a = NSAlert(); a.messageText = title; a.informativeText = message
        buttons.forEach { a.addButton(withTitle: $0) }
        return a
    }
    private func confirm(_ title: String, _ message: String, action: String) -> Bool {
        alert(title, message, buttons: [action, "Cancel"]).runModal() == .alertFirstButtonReturn
    }
    private func showProgress(_ text: String) {
        if progress == nil {
            let p = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 480, height: 140), styleMask: [.titled], backing: .buffered, defer: false)
            p.title = "Wizard Backup"; p.isReleasedWhenClosed = false
            let spin = NSProgressIndicator(frame: NSRect(x: 24, y: 56, width: 28, height: 28))
            spin.style = .spinning; spin.startAnimation(nil); p.contentView?.addSubview(spin)
            let label = NSTextField(wrappingLabelWithString: text); label.frame = NSRect(x: 70, y: 35, width: 380, height: 65)
            label.font = .systemFont(ofSize: 14); p.contentView?.addSubview(label)
            p.center(); p.makeKeyAndOrderFront(nil); progress = p; progressLabel = label
        }
        progressLabel?.stringValue = text
    }
    private func hideProgress() { progress?.close(); progress = nil; progressLabel = nil }
    private func operation(_ body: @escaping () async throws -> Void) {
        guard !busy, supported, isLocal() else { return }
        busy = true
        Task {
            defer { busy = false; hideProgress(); Task { await refresh() } }
            do { try await body() }
            catch {
                hideProgress()
                // Only our curated errors are displayed; transport exceptions can contain URLs/body fragments.
                let message = (error as? BackupFailure)?.message ?? "The connection to Wizard was interrupted. An accepted job may still be running. Keep Wizard open and check its status before retrying."
                alert("Wizard backup needs attention", message).runModal()
            }
        }
    }
    private func wait(_ start: [String: Any]) async throws -> [String: Any] {
        guard let id = start["id"] as? String else { throw BackupFailure("Wizard did not accept the backup job.") }
        let deadline = Date().addingTimeInterval(14400)
        var current = start
        while current["state"] as? String == "running" {
            showProgress((current["phase"] as? String ?? "Working") + "…\nKeep Wizard running. This may take a few minutes.")
            guard Date() < deadline else { throw BackupFailure("This operation is taking longer than expected. Keep Wizard running and check backup status before retrying.") }
            try await Task.sleep(nanoseconds: 1_000_000_000)
            current = try await client.call("jobs/\(id)")
        }
        guard ["verified", "complete"].contains(current["state"] as? String ?? "") else {
            throw BackupFailure(current["error"] as? String ?? "The operation was interrupted. Keep both copies and check the restore status.")
        }
        return current
    }
    private func secretPrompt(passphrase: Bool = false) -> (String, Bool)? {
        let a = alert(passphrase ? "Choose a backup passphrase" : "Unlock this Wizard backup",
            passphrase ? "Use a long, unique passphrase. You will need it on the other machine. Losing it means losing access to this backup." : "Enter the recovery key or passphrase used when this backup was made.", buttons: ["Continue", "Cancel"])
        let view = NSView(frame: NSRect(x: 0, y: 0, width: 420, height: passphrase ? 112 : 76))
        let field = NSSecureTextField(frame: NSRect(x: 0, y: passphrase ? 82 : 46, width: 420, height: 24))
        field.placeholderString = passphrase ? "Passphrase" : "Recovery key or passphrase"
        let again = NSSecureTextField(frame: NSRect(x: 0, y: 46, width: 420, height: 24)); again.placeholderString = "Type the passphrase again"
        let save = NSButton(checkboxWithTitle: "Save in this Mac's Keychain (optional)", target: nil, action: nil)
        save.frame = NSRect(x: 0, y: 4, width: 420, height: 24)
        view.addSubview(field); if passphrase { view.addSubview(again) }; view.addSubview(save)
        a.accessoryView = view; a.window.initialFirstResponder = field
        while true {
            guard a.runModal() == .alertFirstButtonReturn else { field.stringValue = ""; again.stringValue = ""; return nil }
            let value = field.stringValue
            if !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && (!passphrase || (value.count >= 12 && value == again.stringValue)) {
                field.stringValue = ""; again.stringValue = ""
                return (value, save.state == .on)
            }
            a.informativeText = passphrase ? "Use at least 12 characters and type the same passphrase twice." : "Enter the key or passphrase to continue."
        }
    }
    private func showRecovery(_ key: String) throws {
        let a = alert("Save your recovery key", "This key is shown once. Save it somewhere safe, separate from this Mac. It opens your Wizard backups; without it they cannot be recovered.", buttons: ["I Saved It", "Copy"])
        let view = NSView(frame: NSRect(x: 0, y: 0, width: 460, height: 100))
        let field = NSTextField(wrappingLabelWithString: key); field.isSelectable = true
        field.font = .monospacedSystemFont(ofSize: 13, weight: .regular); field.frame = NSRect(x: 0, y: 42, width: 460, height: 58)
        let save = NSButton(checkboxWithTitle: "Also save in this Mac's Keychain (optional)", target: nil, action: nil)
        save.frame = NSRect(x: 0, y: 4, width: 460, height: 26); view.addSubview(field); view.addSubview(save); a.accessoryView = view
        while a.runModal() == .alertSecondButtonReturn {
            NSPasteboard.general.clearContents(); NSPasteboard.general.setString(key, forType: .string)
        }
        field.stringValue = ""
        if save.state == .on { try WizardBackupKeychain.save(key) }
    }
    @objc func backUp() {
        operation { [self] in
            let cap = try await client.call("capabilities")
            let panel = NSSavePanel(); panel.title = "Back Up This Wizard"
            panel.allowedContentTypes = [UTType(filenameExtension: "wizardbackup") ?? .data]
            panel.nameFieldStringValue = WizardBackupContract.filename(name: cap["name"] as? String ?? wizardName())
            guard panel.runModal() == .OK, let destination = panel.url else { return }
            let stored = cap["stored_key"] as? Bool == true
            let choice = alert("How should this backup be locked?", stored ? "Use your saved recovery key, or add a passphrase for this copy." : "A recovery key is recommended. You can use a passphrase instead for a one-off backup or move.",
                               buttons: [stored ? "Use Recovery Key" : "Create Recovery Key", "Use Passphrase…", "Cancel"]).runModal()
            if choice == .alertThirdButtonReturn { return }
            var body: [String: Any] = [:]
            if choice == .alertSecondButtonReturn {
                guard let (secret, save) = secretPrompt(passphrase: true) else { return }
                if save { try WizardBackupKeychain.save(secret) }
                body["secret"] = secret
            } else if !stored {
                let key = try await client.call("key/new", method: "POST", body: [:])
                guard let secret = key["recovery_key"] as? String else { throw BackupFailure("Wizard could not create a recovery key.") }
                try showRecovery(secret)
            }
            showProgress("Starting encrypted backup…")
            let started = try await client.call("export", method: "POST", body: body)
            body.removeAll()
            let finished = try await wait(started)
            showProgress("Saving and checking the backup on your Mac…")
            try await client.download(finished, to: destination)
            hideProgress()
            let warnings = ((finished["result"] as? [String: Any])?["warnings_count"] as? Int) ?? 0
            alert("Your Wizard backup is saved", "Saved \(destination.lastPathComponent). The downloaded size and checksum match. Keep the backup and its key in separate safe places.\n\nThe original Wizard is still active." + (warnings > 0 ? "\n\nSome files were omitted or changed during capture. Verify this copy before relying on it." : "")).runModal()
        }
    }
    @objc func restore() {
        operation { [self] in
            let panel = NSOpenPanel(); panel.title = "Restore a Wizard Backup"; panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
            panel.allowedContentTypes = [UTType(filenameExtension: "wizardbackup") ?? .data]
            guard panel.runModal() == .OK, let source = panel.url, let (secret, save) = secretPrompt() else { return }
            showProgress("Sending the encrypted backup into Wizard…\nIt is not stored in shared Files.")
            let uploaded = try await client.upload(source)
            guard let id = uploaded["id"] as? String else { throw BackupFailure("Wizard did not receive the backup.") }
            let verified = try await wait(client.call("jobs/\(id)/verify", method: "POST", body: ["secret": secret]))
            hideProgress()
            if save { try WizardBackupKeychain.save(secret) }
            guard confirm("Restore this Wizard backup?", WizardBackupContract.summary(verified["result"] as? [String: Any] ?? [:]), action: "Restore Here") else {
                _ = try? await client.call("jobs/\(id)", method: "DELETE"); return
            }
            let imported = try await wait(client.call("jobs/\(id)/import", method: "POST", body: ["secret": secret, "confirm": true]))
            hideProgress(); didRestore()
            let result = imported["result"] as? [String: Any] ?? [:]
            if result["partial"] as? Bool == true {
                alert("Partly restored — kept paused", WizardBackupContract.partialRestoreSummary(result)).runModal()
                return  // Never offer immediate activation as if every app arrived.
            }
            if alert("Restored — paused until you switch over", "Your agents, apps and files are here. Messaging, scheduled jobs and backups stay paused so they do not run alongside the original. Undo Last Restore puts back what was here.",
                     buttons: ["Keep Paused", "Make This My Active Wizard…"]).runModal() == .alertSecondButtonReturn {
                try await activateConfirmed()
            }
        }
    }
    @objc func undo() {
        operation { [self] in
            guard confirm("Undo the last restore?", "This puts back the Wizard that was here before the restore, including its previous messaging and scheduled jobs. Stop any other active copy first. Changes made since the restore will be set aside.", action: "Undo Last Restore") else { return }
            _ = try await wait(client.call("undo", method: "POST", body: ["confirm": true]))
            hideProgress(); didRestore(); alert("Your previous Wizard is back", "Wizard checked its saved-state digest after undo.").runModal()
        }
    }
    @objc func activate() { operation { [self] in try await activateConfirmed() } }
    private func activateConfirmed() async throws {
        guard confirm("Is the old Wizard switched off?", "Shut down the old machine or stop its Wizard first. This turns back on the messaging, scheduled jobs and backups that were active when the backup was made. Running both copies can send duplicate messages and tasks.", action: "The Old Wizard Is Off — Switch Over") else { return }
        _ = try await wait(client.call("activate", method: "POST", body: ["old_is_off": true]))
        hideProgress(); didRestore(); alert("This is now your active Wizard", "Keep the old copy off. Your previously active messaging and scheduled jobs can run here.").runModal()
    }
}
