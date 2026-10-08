import Foundation

/// Contract shared by the Wizard app (front end) and Wizard Host (back-end runner).
enum WizardShared {
    static let hostBundleID = "org.humanitylabs.wizard.host"
    static let appBundleID = "org.humanitylabs.wizard"

    /// Mac loopback ports bridged into Wizard OS over vsock.
    static let uxPort: UInt16 = 47823      // -> guest 8923 (Wizard UX)
    static let setupPort: UInt16 = 47830   // -> guest 8930 (front door / onboarding)
    static let guestUXPort: UInt32 = 8923
    static let guestSetupPort: UInt32 = 8930
    static let guestControlPort: UInt32 = 9100
    static let hostOpenURLPort: UInt32 = 9101

    static var supportDir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Wizard", isDirectory: true)
    }
    static var osDir: URL { supportDir.appendingPathComponent("os", isDirectory: true) }
    static var logsDir: URL { supportDir.appendingPathComponent("logs", isDirectory: true) }
    static var statusFile: URL { supportDir.appendingPathComponent("host-status.json") }

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
