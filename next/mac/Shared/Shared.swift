import Foundation
import Darwin

/// Contract shared by the Wizard app (front end) and Wizard Host (back-end runner).
enum WizardShared {
    static let hostBundleID = "org.humanitylabs.wizard.mvp.host"
    static let appBundleID = "org.humanitylabs.wizard.mvp"

    /// Mac loopback ports bridged into Wizard OS over vsock.
    static let uxPort: UInt16 = 48023      // -> guest 8923 -> the wizard-shell app (Agent Service + Wizard UX)
    static let setupPort: UInt16 = 48030   // -> guest 8930 (front door / onboarding)
    static let guestUXPort: UInt32 = 8923
    static let guestSetupPort: UInt32 = 8930
    static let guestControlPort: UInt32 = 9100
    static let hostOpenURLPort: UInt32 = 9101
    static let devShellPort: UInt16 = 48000       // -> guest 9200, only when `dev-shell` exists (QA)
    static let guestDevShellPort: UInt32 = 9200
    static var devShell: Bool { FileManager.default.fileExists(atPath: supportDir.appendingPathComponent("dev-shell").path) }
    private static var validatedGuestPayload: (app: String, nonce: String, url: URL)?
    static var guestUpdatePayload: URL? {
        let journal = WizardUpdate.json(WizardUpdate.journal)
        guard journal["phase"] as? String == "guest-activating", journal["dataHome"] as? String == supportDir.path,
              let path = journal["appPath"] as? String else { return nil }
        let app = URL(fileURLWithPath: path)
        let nonce = journal["nonce"] as? String ?? ""
        if journal["kind"] as? String == "legacy-cold" {
            guard journal["diskIdentity"] as? String == diskIdentity,
                  let release = try? WizardRelease.read(app),
                  journal["releaseID"] as? String == release.releaseID else { return nil }
        }
        if let cached = validatedGuestPayload, cached.app == path, cached.nonce == nonce { return cached.url }
        guard let release = try? WizardRelease.read(app), release.guestPatch == "mac-stack-v1",
              (try? release.validate(app)) != nil else { return nil }
        let payload = app.appendingPathComponent("Contents/Resources/GuestUpdate")
        validatedGuestPayload = (path, nonce, payload)
        return payload
    }

    static var legacyBootstrapNeeded: Bool {
        guard osInstalled else { return false }
        let manifest = WizardUpdate.json(osDir.appendingPathComponent("manifest.json"))
        if manifest["version"] as? String == "0.4.0" { return false }
        let receipt = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("legacy-complete.json"))
        let modern = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-receipt.json"))
        return !WizardDiskIdentity.completed(receipt, modern: modern, journal: WizardUpdate.json(WizardUpdate.journal),
                                             disk: osDir.appendingPathComponent("disk.img"), home: supportDir)
    }
    static var diskIdentity: String {
        WizardDiskIdentity.read(osDir.appendingPathComponent("disk.img")) ?? "unknown"
    }
    static var coldBootstrapToken: String? {
        let j = WizardUpdate.json(WizardUpdate.journal)
        guard j["kind"] as? String == "legacy-cold", j["phase"] as? String == "guest-activating",
              j["diskIdentity"] as? String == diskIdentity,
              let token = j["nonce"] as? String, UUID(uuidString: token) != nil,
              guestUpdatePayload != nil else { return nil }
        return token
    }
    static var supportDir: URL {
        // Pin the runner to the launching App's exact DataHome. Suite-only preference
        // lookup is not a reliable handoff across an NSWorkspace login-item launch.
        if Bundle.main.bundleIdentifier == hostBundleID,
           let i = CommandLine.arguments.firstIndex(of: "--wizard-data-home"), i + 1 < CommandLine.arguments.count,
           CommandLine.arguments[i + 1].hasPrefix("/") {
            return URL(fileURLWithPath: CommandLine.arguments[i + 1], isDirectory: true)
        }
        // Dedicated internal-test identity; never opens or migrates the daily Wizard VM.
        let defaults = Bundle.main.bundleIdentifier == appBundleID ? UserDefaults.standard : UserDefaults(suiteName: appBundleID)
        if let p = defaults?.string(forKey: "DataHome"), p.hasPrefix("/") {
            return URL(fileURLWithPath: p, isDirectory: true)
        }
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Wizard MVP", isDirectory: true)
    }
    static var osDir: URL { supportDir.appendingPathComponent("os", isDirectory: true) }
    static var logsDir: URL { supportDir.appendingPathComponent("logs", isDirectory: true) }
    static var statusFile: URL { supportDir.appendingPathComponent("host-status.json") }

    /// The Mac folder shared into Wizard OS as its user-files folder (Runtipi media root). Chosen on first run;
    /// nil = not chosen yet (the guest then keeps files on its own disk).
    static let filesShareTag = "wizard-files"
    static var filesFolderFile: URL { supportDir.appendingPathComponent("files-folder.json") }
    // User-created files belong in a Finder-visible folder. Changing this suggestion
    // never changes a persisted files-folder.json or moves an existing user's files.
    static var defaultFilesFolder: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Wizard MVP", isDirectory: true)
    }
    static var filesFolder: URL? {
        guard let d = try? Data(contentsOf: filesFolderFile),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let p = o["path"] as? String, !p.isEmpty else { return nil }
        return URL(fileURLWithPath: p, isDirectory: true)
    }
    static func setFilesFolder(_ url: URL) throws {
        try FileManager.default.createDirectory(at: supportDir, withIntermediateDirectories: true)
        let d = try JSONSerialization.data(withJSONObject: ["path": url.path], options: [.prettyPrinted])
        try d.write(to: filesFolderFile, options: .atomic)
    }

    static var localSetupURL: URL { URL(string: "http://127.0.0.1:\(setupPort)/")! }
    static var localHealthURL: URL { URL(string: "http://127.0.0.1:\(setupPort)/healthz")! }
    static var localUXHealthURL: URL { URL(string: "http://127.0.0.1:\(uxPort)/wizard/health")! }

    /// Ready = the front door AND the Wizard UX server both answer.
    static func probeReady(_ done: @escaping (Bool) -> Void) {
        func check(_ url: URL, _ next: @escaping (Bool) -> Void) {
            var req = URLRequest(url: url); req.timeoutInterval = 1
            req.cachePolicy = .reloadIgnoringLocalCacheData
            URLSession.shared.dataTask(with: req) { _, resp, _ in
                next((resp as? HTTPURLResponse)?.statusCode == 200)
            }.resume()
        }
        check(localHealthURL) { ok in
            guard ok else { done(false); return }
            check(localUXHealthURL, done)
        }
    }

    static var osInstalled: Bool {
        let fm = FileManager.default
        return ["manifest.json", "boot/vmlinux", "boot/initrd", "disk.img"].allSatisfy {
            fm.fileExists(atPath: osDir.appendingPathComponent($0).path)
        }
    }
}
