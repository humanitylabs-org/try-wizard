import Foundation
import CoreFoundation
import CryptoKit
import Darwin

/// Versioned, additive contract. Sparkle authenticates the archive before extraction;
/// this sealed manifest binds App/Host/guest code to one release (never a factory disk).
struct WizardRelease: Codable {
    let schema: Int
    let releaseID: String
    let build: String
    let arch: String
    let minimumOS: String
    let hostProtocol: Int
    let minimumPeer: Int
    let files: [String: String]
    let guestPatch: String?
    let payloadID: String?
    // Optional only for old signed appcasts. New bundles always emit this range.
    let supportedGuestABI: WizardGuestABI.Range?

    static let peer = 1
    func validateMetadata() throws {
        guard schema == 1, arch == "arm64", hostProtocol == Self.peer, minimumPeer >= 1, minimumPeer <= Self.peer,
              releaseID.range(of: "^[A-Za-z0-9._-]{1,128}$", options: .regularExpression) != nil,
              build.range(of: "^[1-9][0-9]*$", options: .regularExpression) != nil,
              minimumOS.range(of: "^[0-9]+\\.[0-9]+(\\.[0-9]+)?$", options: .regularExpression) != nil,
              guestPatch == nil || guestPatch == "mac-stack-v1" else { throw WizardUpdate.error("Incompatible release metadata") }
        if let range = supportedGuestABI {
            guard range.min >= 0, range.min <= range.max else { throw WizardUpdate.error("Invalid supportedGuestABI range") }
        }
        let parts = minimumOS.split(separator: ".").compactMap { Int($0) }
        guard parts.count == minimumOS.split(separator: ".").count else { throw WizardUpdate.error("Invalid minimum OS version") }
        let os = OperatingSystemVersion(majorVersion: parts[0], minorVersion: parts[1], patchVersion: parts.count == 3 ? parts[2] : 0)
        guard ProcessInfo.processInfo.isOperatingSystemAtLeast(os) else { throw WizardUpdate.error("New release needs macOS \(minimumOS)") }
    }
    static func read(_ bundle: URL) throws -> WizardRelease {
        let url = bundle.appendingPathComponent("Contents/Resources/wizard-release.json")
        return try JSONDecoder().decode(Self.self, from: Data(contentsOf: url))
    }
    func validate(_ bundle: URL, verifyGuestFiles: Bool = true) throws {
        try validateMetadata()
        guard schema == 1, arch == "arm64", hostProtocol == Self.peer, minimumPeer <= Self.peer,
              !releaseID.isEmpty, build.allSatisfy({ $0.isNumber }), !build.isEmpty,
              ProcessInfo.processInfo.isOperatingSystemAtLeast(OperatingSystemVersion(majorVersion: Int(minimumOS.split(separator: ".").first ?? "0") ?? 0, minorVersion: 0, patchVersion: 0)),
              let plist = NSDictionary(contentsOf: bundle.appendingPathComponent("Contents/Info.plist")),
              plist["CFBundleVersion"] as? String == build,
              plist["CFBundleIdentifier"] as? String == WizardShared.appBundleID,
              files["Contents/MacOS/Wizard"] != nil,
              files["Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host"] != nil else {
            throw WizardUpdate.error("Incompatible or incomplete release contract")
        }
        guard let host = NSDictionary(contentsOf: bundle.appendingPathComponent("Contents/Library/LoginItems/Wizard Host.app/Contents/Info.plist")),
              host["CFBundleIdentifier"] as? String == WizardShared.hostBundleID,
              host["CFBundleVersion"] as? String == build else { throw WizardUpdate.error("Host/App release mismatch") }
        for (relative, expected) in files {
            guard !relative.hasPrefix("/"), !relative.split(separator: "/").contains(".."), expected.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else { throw WizardUpdate.error("Invalid release path or digest") }
            if !verifyGuestFiles && relative.hasPrefix("Contents/Resources/GuestUpdate/") { continue }
            let file = bundle.appendingPathComponent(relative).resolvingSymlinksInPath()
            guard file.path.hasPrefix(bundle.resolvingSymlinksInPath().path + "/"), try WizardUpdate.sha256(file) == expected else { throw WizardUpdate.error("Release digest mismatch: \(relative)") }
        }
        if let patch = guestPatch {
            guard patch == "mac-stack-v1", files.keys.contains(where: { $0.hasPrefix("Contents/Resources/GuestUpdate/") }) else { throw WizardUpdate.error("Unsupported guest migration") }
        }
    }
}

/// The only legacy version inference table. Explicit ABI never falls back.
enum WizardGuestABI {
    struct Range: Codable {
        let min: Int
        let max: Int
        func contains(_ abi: Int) -> Bool { min >= 0 && min <= max && abi >= min && abi <= max }
    }
    static let supportedGuestABI = Range(min: 0, max: 1)
    static let legacy = ["0.3.0": 0, "0.4.0": 1, "0.4.1": 1]
    static func image(_ manifest: [String: Any]) throws -> Int {
        let abi: Int?
        if let raw = manifest["guestABI"] {
            guard let number = raw as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
                  String(cString: number.objCType) != "d", String(cString: number.objCType) != "f" else {
                throw WizardUpdate.error("Invalid guestABI: expected an integer")
            }
            abi = number.intValue
        } else { abi = legacy[manifest["version"] as? String ?? ""] }
        guard let abi, supportedGuestABI.contains(abi) else {
            throw WizardUpdate.error("Unsupported guestABI — update Wizard before using this OS image")
        }
        return abi
    }
    static func requireSystemOwner(_ receipt: [String: Any], diskIdentity: String, incomingBuild: String) throws {
        // No field is the legacy host-owned migration case; an explicit other owner never falls back.
        if let owner = receipt["systemOwner"], (owner as? String) != "host-payload" {
            throw WizardUpdate.error("System payload refused: this disk is owned by another updater")
        }
        if receipt["diskIdentity"] as? String == diskIdentity, let build = receipt["payloadBuild"] as? String,
           incomingBuild.compare(build, options: .numeric) == .orderedAscending {
            throw WizardUpdate.error("System payload downgrade refused; newer disk remains bootable")
        }
    }
    static func requiresFreshApply(baked: String?, bundled: String?) -> Bool {
        // Missing legacy IDs always apply. Only exact content identity skips.
        guard let baked, let bundled, !baked.isEmpty, !bundled.isEmpty else { return true }
        return baked != bundled
    }
    static func payload(_ url: URL, abi: Int) throws {
        let bom = WizardUpdate.json(url.appendingPathComponent("runtime-bom.json"))
        guard let object = bom["guestABI"], let data = try? JSONSerialization.data(withJSONObject: object),
              let range = try? JSONDecoder().decode(Range.self, from: data),
              range.max <= supportedGuestABI.max, range.contains(abi) else {
            throw WizardUpdate.error("Payload guestABI range does not admit this disk")
        }
    }
}

enum WizardUpdate {
    static var dir: URL { WizardShared.supportDir.appendingPathComponent("updates") }
    static var request: URL { dir.appendingPathComponent("host-request.json") }
    static var response: URL { dir.appendingPathComponent("host-response.json") }
    static var journal: URL { dir.appendingPathComponent("transaction.json") }
    static func error(_ text: String) -> NSError { NSError(domain: "WizardUpdate", code: 1, userInfo: [NSLocalizedDescriptionKey: text]) }
    static func json(_ url: URL) -> [String: Any] { ((try? Data(contentsOf: url)).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }) ?? [:] }
    static func write(_ object: [String: Any], _ url: URL) throws {
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .prettyPrinted]).write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
    static func sha256(_ url: URL) throws -> String {
        // Native code section digest is stable across inside-out codesigning (a full
        // executable hash in its own sealed manifest would be self-referential).
        if url.path.contains("/Contents/MacOS/") {
            let data = try Data(contentsOf: url)
            func u32(_ at: Int) -> UInt32 { data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: at, as: UInt32.self) }.littleEndian }
            func u64(_ at: Int) -> UInt64 { data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: at, as: UInt64.self) }.littleEndian }
            guard data.count > 32, u32(0) == 0xfeedfacf else { throw error("Expected thin arm64 Mach-O") }
            var offset = 32
            for _ in 0..<u32(16) {
                guard offset + 8 <= data.count else { throw error("Invalid Mach-O commands") }
                let command = u32(offset), size = Int(u32(offset + 4))
                guard size >= 8, offset + size <= data.count else { throw error("Invalid Mach-O command size") }
                if command == 0x19, size >= 72 {
                    for i in 0..<Int(u32(offset + 64)) {
                        let section = offset + 72 + i * 80
                        guard section + 80 <= offset + size else { throw error("Invalid Mach-O section") }
                        if String(data: data[section..<section+16].prefix(while: { $0 != 0 }), encoding: .utf8) == "__text" {
                            let start = Int(u32(section + 48)), length = Int(u64(section + 40))
                            guard start >= 0, length > 0, start <= data.count, length <= data.count - start else { throw error("Invalid Mach-O code range") }
                            return SHA256.hash(data: data[start..<start+length]).map { String(format: "%02x", $0) }.joined()
                        }
                    }
                }
                offset += size
            }
            throw error("Native code section missing")
        }
        let file = try FileHandle(forReadingFrom: url); defer { try? file.close() }
        var hash = SHA256()
        while let data = try file.read(upToCount: 1024 * 1024), !data.isEmpty { hash.update(data: data) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }
    /// Only the exact local Host is disruptive. Never probe/mutate a connected remote server.
    static func idle(_ done: @escaping (String?) -> Void) {
        let status = json(WizardShared.statusFile)
        guard let pid = status["pid"] as? Int32, kill(pid, 0) == 0 else { done(nil); return }
        if ["stopped", "notInstalled"].contains(status["state"] as? String ?? "") { done(nil); return }
        guard status["state"] as? String == "running" else { done("Wizard OS is starting or stopping"); return }
        var req = URLRequest(url: WizardShared.localUXHealthURL); req.timeoutInterval = 4; req.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: req) { data, response, _ in
            var reason: String? = "Cannot verify local agent activity — retry when Wizard OS is ready"
            if (response as? HTTPURLResponse)?.statusCode == 200, let data,
               let health = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               health["upstream_reachable"] as? Bool == true, let q = health["queue"] as? [String: Any],
               q["liveness_available"] as? Bool == true, let active = q["active"] as? Int, let queued = q["queued"] as? Int {
                reason = active + queued == 0 ? nil : "Agent work is active — update after it finishes"
            }
            DispatchQueue.main.async { done(reason) }
        }.resume()
    }
    /// Owner-local admission lease, not the UX queue projection. Never targets a connected remote backend.
    static let maintenanceJournal = dir.appendingPathComponent("maintenance-lease.json")
    static func maintenance(_ token: String, release: Bool = false, _ done: @escaping (String?) -> Void) {
        // The same token owns stop, maintenance boot, rollback and final release.
        let token = (json(maintenanceJournal)["token"] as? String) ?? token
        if !release {
            do { try write(["token": token], maintenanceJournal) }
            catch { done("Cannot retain local maintenance recovery token"); return }
        }
        var components = URLComponents(url: WizardShared.localUXHealthURL, resolvingAgainstBaseURL: false)!
        components.path = "/wizard/v1/maintenance"
        var req = URLRequest(url: components.url!); req.timeoutInterval = 90
        req.httpMethod = release ? "DELETE" : "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["token": token])
        URLSession.shared.dataTask(with: req) { data, response, _ in
            let body = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let ok = (response as? HTTPURLResponse)?.statusCode == (release ? 200 : 201) && body?["ok"] as? Bool == true
            DispatchQueue.main.async {
                if ok {
                    if release { try? FileManager.default.removeItem(at: maintenanceJournal) }
                    else { try? write(["token": token], maintenanceJournal) }
                }
                done(ok ? nil : "Local maintenance deferred: \(body?["message"] as? String ?? body?["error"] as? String ?? "cannot verify all local runtimes")")
            }
        }.resume()
    }
    static func releaseMaintenance(_ token: String) { maintenance(token, release: true) { _ in } }
    static func run(_ path: String, _ args: [String]) throws {
        let p = Process(); p.executableURL = URL(fileURLWithPath: path); p.arguments = args
        p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
        try p.run(); p.waitUntilExit()
        guard p.terminationStatus == 0 else { throw error("\(URL(fileURLWithPath: path).lastPathComponent) failed (\(p.terminationStatus))") }
    }
}
