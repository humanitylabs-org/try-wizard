import AppKit
import Darwin
import ServiceManagement
import WebKit

/// Native-only front door. The guest is never asked to erase anything.
@MainActor final class WizardRemovalController {
    var window: () -> NSWindow? = { nil }
    var isBusy: () -> Bool = { false }
    var admit: (@escaping (Bool) -> Void) -> Void = { $0(true) }
    var freeze: (Bool) -> Void = { _ in }
    var didStartFresh: () -> Void = {}
    private(set) var busy = false
    private var lease: WizardDiskOwnership?
    private var progress: NSAlert?
    private var menuState: [(NSMenu, Bool, [(NSMenuItem, Bool)])] = []

    private func makePlan(_ action: WizardRemovalPlan.Action) throws -> WizardRemovalPlan {
        // A corrupt choice file is not permission to assume the default folder is safe.
        let saved = WizardShared.filesFolderFile
        if FileManager.default.fileExists(atPath: saved.path), WizardShared.filesFolder == nil {
            throw WizardRemovalPlan.error("Your Files folder setting cannot be read. Repair files-folder.json before removing data.")
        }
        return WizardRemovalPlan(action: action, home: FileManager.default.homeDirectoryForCurrentUser,
            library: FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0],
            dataHome: WizardShared.supportDir, app: Bundle.main.bundleURL.standardizedFileURL,
            files: [WizardShared.defaultFilesFolder, WizardShared.filesFolder ?? WizardShared.defaultFilesFolder],
            bundleIDs: [WizardShared.appBundleID, WizardShared.hostBundleID])
    }
    func show(startFresh: Bool) {
        guard window()?.attachedSheet == nil else { return }
        guard !busy, !isBusy() else { fail("Finish the current recording, download, backup or update first."); return }
        do {
            let plan = try makePlan(startFresh ? .startFresh : .deleteData)
            try plan.validate()
            let a = NSAlert()
            a.messageText = startFresh ? "Start Fresh?" : "Uninstall Wizard?"
            let size = ByteCountFormatter.string(fromByteCount: plan.inventory.reduce(Int64(0)) { $0 + WizardRemovalPlan.allocatedBytes($1.url) } + (startFresh ? 0 : WizardRemovalPlan.allocatedBytes(plan.app)), countStyle: .file)
            a.informativeText = "Wizard and its data (\(size)). Your files in \(plan.files.last!.path) stay.\n\nDeleting Wizard data removes this Mac's VM disk, chats, sign-ins, installed apps and logs. It also clears Wizard's Mac preferences, caches, web storage and privacy permissions. Remote Wizards are not deleted.\n\nData folder: \(plan.dataHome.path)"
            let choice = NSButton(checkboxWithTitle: startFresh ? "Back up the stopped disk first (APFS clone)" : "Delete my Wizard data", target: nil, action: nil)
            choice.state = startFresh ? .on : .off
            let keep = NSTextField(wrappingLabelWithString: "Keep my Wizard data (default): only the app is moved to Trash. Reinstalling resumes this Wizard, including an external data folder.")
            let inventory = plan.inventory.map { entry in
                "\(entry.label): \(ByteCountFormatter.string(fromByteCount: WizardRemovalPlan.allocatedBytes(entry.url), countStyle: .file))\n\(entry.url.path)"
            }.joined(separator: "\n\n")
            let details = NSTextView(frame: NSRect(x: 0, y: 0, width: 420, height: 600))
            details.isEditable = false; details.isRichText = false; details.drawsBackground = false
            details.string = "If you delete Wizard data:\n\n" + inventory
            details.textColor = .labelColor; details.font = .systemFont(ofSize: 11)
            let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 430, height: 140))
            scroll.hasVerticalScroller = true; scroll.documentView = details; scroll.drawsBackground = false
            let stack = NSStackView(views: startFresh ? [choice, scroll] : [keep, choice, scroll])
            stack.orientation = .vertical; stack.alignment = .leading
            scroll.widthAnchor.constraint(equalToConstant: 430).isActive = true
            scroll.heightAnchor.constraint(equalToConstant: 140).isActive = true
            stack.setFrameSize(NSSize(width: 430, height: startFresh ? 180 : 230)); a.accessoryView = stack
            // Cancel is the keyboard default. The data-retention choice defaults to Keep.
            a.addButton(withTitle: "Cancel")
            a.addButton(withTitle: startFresh ? "Continue…" : "Uninstall…")
            present(a) { [weak self] response in
                guard let self, response == .alertSecondButtonReturn else { return }
                let action: WizardRemovalPlan.Action = startFresh ? .startFresh : (choice.state == .on ? .deleteData : .keepData)
                if action == .keepData { self.run(action, backup: nil); return }
                let second = NSAlert(); second.alertStyle = .critical
                second.messageText = startFresh ? "Delete Wizard data and start again?" : "Permanently delete Wizard data?"
                second.informativeText = "This cannot be undone without a backup. All chats, sign-ins and apps on this Mac's Wizard disk will be removed. Your Files folder stays."
                second.addButton(withTitle: "Cancel"); second.addButton(withTitle: startFresh ? "Delete Data and Start Fresh" : "Delete Data and Uninstall")
                self.present(second) { [weak self] answer in
                    guard let self, answer == .alertSecondButtonReturn else { return }
                    if startFresh && choice.state == .on { self.chooseBackup { if let url = $0 { self.run(action, backup: url) } } }
                    else { self.run(action, backup: nil) }
                }
            }
        } catch { fail(error.localizedDescription) }
    }
    private func present(_ alert: NSAlert, completion: @escaping (NSApplication.ModalResponse) -> Void) {
        if let window = window() { alert.beginSheetModal(for: window, completionHandler: completion) }
        else { completion(alert.runModal()) }
    }
    private func chooseBackup(_ done: @escaping (URL?) -> Void) {
        let panel = NSSavePanel(); panel.title = "Save stopped Wizard disk backup"
        panel.nameFieldStringValue = "Wizard-stopped-backup-\(Int(Date().timeIntervalSince1970))"
        panel.message = "Choose a new folder on the same APFS volume as the Wizard data. The backup contains your disk, sign-ins and apps; keep it private."
        if let window = window() { panel.beginSheetModal(for: window) { done($0 == .OK ? panel.url : nil) } }
        else { done(panel.runModal() == .OK ? panel.url : nil) }
    }
    private func run(_ action: WizardRemovalPlan.Action, backup: URL?) {
        guard !busy, !isBusy(), !HostControl.hasForeignRunner else { fail("Another Wizard task or Host is running. Nothing was removed."); return }
        busy = true
        admit { [weak self] admitted in
            guard let self else { return }
            guard admitted else { self.busy = false; self.fail("Finish voice capture before continuing. Nothing was removed."); return }
            HostControl.maintenanceInProgress = true; self.freeze(true)
            self.disableMenus(NSApp.mainMenu)
            let a = NSAlert(); a.messageText = "Stopping Wizard OS safely…"
            a.informativeText = "Please wait. No data is removed until Wizard Host confirms the VM is stopped."
            a.addButton(withTitle: "Working…").isEnabled = false
            self.progress = a
            if let w = self.window() { a.beginSheetModal(for: w) }
            self.stopHost { result in
                switch result {
                case .failure(let error): self.finish(error)
                case .success:
                    Task { @MainActor in
                    do {
                        let plan = try self.makePlan(action); try plan.validate()
                        if plan.removesApp && !FileManager.default.isWritableFile(atPath: plan.app.deletingLastPathComponent().path) {
                            throw WizardRemovalPlan.error("Wizard's app folder is read-only. Move the app to a writable Applications folder before uninstalling.")
                        }
                        // Host releases the same lock only after clean VZ stop and disk repair.
                        if FileManager.default.fileExists(atPath: WizardShared.osDir.path) {
                            let ownership = WizardDiskOwnership(); try ownership.acquire(); self.lease = ownership
                        }
                        guard !HostControl.isRunning, !HostControl.hasForeignRunner else { throw WizardRemovalPlan.error("Wizard Host restarted. Nothing was removed.") }
                        // Unregister only this embedded Host. Never terminate a Host process.
                        let service = SMAppService.loginItem(identifier: WizardShared.hostBundleID)
                        if service.status == .enabled || service.status == .requiresApproval { try await service.unregister() }
                        try WizardRemoval.execute(plan, isStopped: { !HostControl.isRunning && !HostControl.hasForeignRunner }, backup: backup, effects: Self.effects(dataHome: plan.dataHome))
                        self.lease = nil
                        if action == .startFresh {
                            // A running WKWebView can recreate WebKit storage; clear its live store too.
                            let store = WKWebsiteDataStore.default()
                            store.removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: .distantPast) {
                                Task { @MainActor in
                                    // Keep an external DataHome authoritative for the new install.
                                    UserDefaults.standard.set(plan.dataHome.path, forKey: "DataHome")
                                    self.finish(nil); self.didStartFresh()
                                }
                            }
                        } else {
                            self.finish(nil)
                            NSApp.terminate(nil)
                        }
                    } catch { self.finish(error) }
                    }
                }
            }
        }
    }
    private func stopHost(_ done: @escaping (Result<Void, Error>) -> Void) {
        guard !HostControl.hasForeignRunner else { done(.failure(WizardRemovalPlan.error("A different Wizard Host is running."))); return }
        guard HostControl.isRunning else { done(.success(())); return }
        let nonce = UUID().uuidString, started = Date()
        // Reuse the guarded quit/update handshake: its nonce is acknowledged only after VM .stopped.
        do {
            guard WizardUpdate.json(WizardShared.statusFile)["hostProtocol"] as? Int == WizardRelease.peer,
                  WizardUpdate.json(WizardShared.statusFile)["dataHome"] as? String == WizardShared.supportDir.path else {
                throw WizardRemovalPlan.error("The running Host cannot confirm this data folder. Stop it using its own menu first.")
            }
            try FileManager.default.createDirectory(at: WizardUpdate.dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            try WizardUpdate.write(["nonce": nonce, "pid": getpid(), "peer": WizardRelease.peer,
                "expires": Date().timeIntervalSince1970 + 180, "appPath": Bundle.main.bundleURL.standardizedFileURL.path], WizardUpdate.request)
            HostControl.send("prepare-update")
        } catch { done(.failure(error)); return }
        func poll() {
            let response = WizardUpdate.json(WizardUpdate.response)
            let acknowledged = response["nonce"] as? String == nonce && response["state"] as? String == "stopped"
            if response["nonce"] as? String == nonce && ["busy", "failed"].contains(response["state"] as? String ?? "") {
                done(.failure(WizardRemovalPlan.error(response["error"] as? String ?? "Wizard Host is busy."))); return
            }
            if acknowledged && !HostControl.isRunning && !HostControl.hasForeignRunner { done(.success(())); return }
            if Date().timeIntervalSince(started) > 180 { done(.failure(WizardRemovalPlan.error("Wizard Host did not confirm a clean stop. Nothing was removed. Try again after Wizard OS stops."))); return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: poll)
        }
        poll()
    }
    private func disableMenus(_ menu: NSMenu?) {
        guard let menu else { return }
        menuState.append((menu, menu.autoenablesItems, menu.items.map { ($0, $0.isEnabled) }))
        menu.autoenablesItems = false
        for item in menu.items { item.isEnabled = false; disableMenus(item.submenu) }
    }
    private func finish(_ error: Error?) {
        lease = nil
        if let a = progress, let parent = a.window.sheetParent { parent.endSheet(a.window) }
        progress = nil
        for (menu, automatic, items) in menuState { menu.autoenablesItems = automatic; for (item, enabled) in items { item.isEnabled = enabled } }
        menuState = []; busy = false; HostControl.maintenanceInProgress = false; freeze(false)
        if let error { fail("\(error.localizedDescription)\n\nThe operation stopped. Some earlier cleanup may already have finished. Your Files folder was not removed. You can retry.") }
    }
    private func fail(_ message: String) { let a = NSAlert(); a.messageText = "Wizard was not removed"; a.informativeText = message; present(a) { _ in } }

    static func effects(dataHome: URL) -> WizardRemovalEffects {
        let fm = FileManager.default
        return WizardRemovalEffects(remove: { url in
            guard fm.fileExists(atPath: url.path) else { return }
            if url == dataHome {
                // Keep the old disk-owner inode locked while atomically removing its path from admission.
                // A concurrent new install must never be swept up by recursive deletion at the old path.
                let retired = url.deletingLastPathComponent().appendingPathComponent(".Wizard-removing-" + UUID().uuidString)
                try fm.moveItem(at: url, to: retired)
                do { try fm.removeItem(at: retired) }
                catch { throw WizardRemovalPlan.error("Cleanup stopped. The old data was moved to \(retired.path); it may be partly removed. \(error.localizedDescription)") }
            } else { try fm.removeItem(at: url) }
        }, clearPreferences: { id in
            let defaults = id == Bundle.main.bundleIdentifier ? UserDefaults.standard : UserDefaults(suiteName: id)!
            defaults.removePersistentDomain(forName: id)
            guard defaults.synchronize(), CFPreferencesSynchronize(id as CFString, kCFPreferencesCurrentUser, kCFPreferencesAnyHost) else {
                throw WizardRemovalPlan.error("Could not clear \(id) preferences.")
            }
        }, resetPrivacy: { id in
            let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/tccutil"); p.arguments = ["reset", "All", id]
            p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
            try p.run(); p.waitUntilExit()
            guard p.terminationStatus == 0 else { throw WizardRemovalPlan.error("macOS could not reset privacy permissions for \(id).") }
        }, trash: { url in
            if fm.fileExists(atPath: url.path) { try fm.trashItem(at: url, resultingItemURL: nil) }
        }, clone: { source, destination in
            // clonefile never falls back to a full disk copy: wrong volume / non-APFS is a clear refusal.
            guard fm.fileExists(atPath: source.appendingPathComponent("disk.img").path) else { throw WizardRemovalPlan.error("There is no installed disk to back up. Uncheck backup to start fresh without one.") }
            try fm.createDirectory(at: destination, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            do {
                for name in try fm.contentsOfDirectory(atPath: source.path) where name != "disk-owner.lock" {
                    let src = source.appendingPathComponent(name), dst = destination.appendingPathComponent(name)
                    if name == "disk.img" {
                        guard clonefile(src.path, dst.path, 0) == 0 else { throw WizardRemovalPlan.error("The APFS disk backup failed (\(String(cString: strerror(errno)))). Nothing was removed; choose the same APFS volume or cancel backup.") }
                    } else { try fm.copyItem(at: src, to: dst) }
                }
            } catch { try? fm.removeItem(at: destination); throw error }
        })
    }
}
