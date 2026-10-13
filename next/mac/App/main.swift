import AVFoundation
import AppKit
import CryptoKit
import ServiceManagement
import WebKit

// Wizard: the native front end. Opens instantly and connects to a Wizard OS back end,
// either on this Mac (run by the Wizard Host menu-bar service) or on another computer.

// MARK: - Back-end connections

struct Backend: Codable, Equatable {
    enum Kind: String, Codable { case thisMac, remote }
    var kind: Kind
    var name: String
    var url: String   // remote: base URL of that computer's Wizard
}

enum Store {
    static let d = UserDefaults.standard
    static var backends: [Backend] {
        get { (d.data(forKey: "backends")).flatMap { try? JSONDecoder().decode([Backend].self, from: $0) } ?? [] }
        set { d.set(try? JSONEncoder().encode(newValue), forKey: "backends") }
    }
    static var activeIndex: Int {
        get { d.integer(forKey: "activeBackend") }
        set { d.set(newValue, forKey: "activeBackend") }
    }
    static var active: Backend? {
        let b = backends
        return b.indices.contains(activeIndex) ? b[activeIndex] : b.first
    }
    static var osFeedURL: URL {
        // GitHub release feed. QA and testers can point a build elsewhere with
        // `defaults write org.humanitylabs.wizard.mvp osFeedURL <url>`.
        URL(string: d.string(forKey: "osFeedURL") ?? "https://github.com/humanitylabs-org/try-wizard/releases/latest/download/latest.json")!
    }
}

// MARK: - Wizard OS installer (download on demand)

final class OSInstaller: NSObject, URLSessionDataDelegate {
    var onProgress: ((String, Double?) -> Void)?
    var onDone: ((Error?) -> Void)?
    private var expectedSHA = ""
    private var version = ""
    // Delegate callbacks on a private serial queue: writing into tar blocks there, which throttles the download.
    private let queue: OperationQueue = { let q = OperationQueue(); q.maxConcurrentOperationCount = 1; return q }()
    private lazy var session = URLSession(configuration: .default, delegate: self, delegateQueue: queue)
    private var tar: Process?
    private var tarIn: FileHandle?
    private var tarErr: Pipe?
    private var hasher = SHA256()
    private var received: Int64 = 0
    private var expected: Int64 = 0
    private var lastProgress = Date.distantPast
    private var failure: Error?

    /// A feed names one archive, or the same archive split into ordered parts (each under GitHub's 2 GiB asset
    /// limit). `sha256` is always the hash of the whole archive; each part also carries its own hash.
    struct Part: Decodable { let url: String; let bytes: Int64?; let sha256: String }
    /// Apps Wizard OS fetches by itself right after first launch (voice), so the space they take is never a surprise.
    struct Background: Decodable { let label: String; let bytes: Int64?; let installBytes: Int64? }
    struct Feed: Decodable {
        let version: String; let url: String?; let sha256: String; let bytes: Int64?; let installBytes: Int64?
        let parts: [Part]?
        let background: [Background]?
        /// Everything Wizard OS will take on this Mac once the background downloads finish.
        var totalInstallBytes: Int64 { (installBytes ?? (11 << 30)) + (background ?? []).reduce(0) { $0 + ($1.installBytes ?? 0) } }
    }

    static func gb(_ b: Int64) -> String { String(format: "%.1f GB", Double(b) / 1e9) }

    /// "Wizard OS will use about 6.4 GB on this Mac: 1.1 GB to download now, then 1.3 GB for voice in the background."
    static func sizeNote(_ f: Feed) -> String {
        var s = "Wizard OS will use about \(gb(f.totalInstallBytes)) on this Mac"
        if let b = f.bytes { s += ": \(gb(b)) to download now" }
        let extra = (f.background ?? []).filter { ($0.bytes ?? 0) > 0 }
        if !extra.isEmpty {
            s += ", then " + extra.map { "\(gb($0.bytes ?? 0)) for \($0.label)" }.joined(separator: " and ") + " in the background"
        }
        return s + "."
    }

    /// Read the feed only to say how much space Wizard OS needs (shown before anything downloads).
    func fetchSizeNote(_ done: @escaping (String?) -> Void) {
        var req = URLRequest(url: Store.osFeedURL); req.timeoutInterval = 6
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            let f = data.flatMap { (resp as? HTTPURLResponse)?.statusCode == 200 ? try? JSONDecoder().decode(Feed.self, from: $0) : nil }
            DispatchQueue.main.async { done(f.map(Self.sizeNote)) }
        }.resume()
    }
    private var partURLs: [(url: URL, sha: String)] = []
    private var partIndex = 0
    private var partHasher = SHA256()
    private var feedBytes: Int64 = 0
    /// Set while an install runs; cleared just before onDone fires.
    private(set) var busy = false

    static var staging: URL { WizardShared.supportDir.appendingPathComponent("os-staging", isDirectory: true) }

    /// macOS extraction can allocate more than the Linux factory disk's used blocks.
    /// Full-stack QA needs at least 16 GiB available for staging and recovery.
    static func checkFreeSpace(install: Int64) throws {
        let need = max(install + (1 << 30), 16 << 30)
        // Check the volume receiving staging, including an explicitly relocated support directory.
        let destination = WizardShared.supportDir.resolvingSymlinksInPath()
        let probe = FileManager.default.fileExists(atPath: destination.path) ? destination : destination.deletingLastPathComponent()
        let values = try probe
            .resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
        guard let free = values.volumeAvailableCapacityForImportantUsage else {
            throw error("Couldn't check free disk space for Wizard OS. Try again before installing.")
        }
        guard free < need else { return }
        throw error(String(format: "Wizard OS needs about %.0f GB of free space on this Mac (%.0f GB free now). Free up some space and try again.",
                           Double(need) / 1e9, Double(free) / 1e9))
    }

    /// Install from a local wizard-os-*.tar.xz (or its ordered parts); integrity comes from the per-file hashes in
    /// its manifest. The app reads the file itself and streams it into tar, so the read happens in the process the
    /// user chose the file in. Files on external drives need macOS's "Removable Volumes" permission; if macOS holds
    /// the read waiting for that answer, say so instead of sitting on "Checking…" forever.
    func install(from file: URL) { install(from: [file]) }

    func install(from files: [URL]) {
        // One install at a time: the download and file paths share tar and the staging folder.
        guard !busy else { onProgress?("Wizard OS is already being set up…", nil); return }
        let files = files.sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
        guard let first = files.first else { return }
        if let problem = Self.partsProblem(files) { onDone?(Self.error(problem)); return }
        onProgress?("Setting up Wizard OS from \(files.count == 1 ? first.lastPathComponent : "\(files.count) files")…", nil)
        do {
            // Reject insufficient capacity before creating staging or touching the current OS.
            try Self.checkFreeSpace(install: 0)
            try startTar()
        } catch { onDone?(error); return }
        busy = true
        // The read state decides whether the permission notice may show: only while still waiting to open the file.
        enum ReadState { case waiting, reading, finished }
        let lock = NSLock(); var state = ReadState.waiting
        func set(_ s: ReadState) { lock.lock(); state = s; lock.unlock() }
        DispatchQueue.global(qos: .userInitiated).async {
            let where_ = Self.locationKind(first)
            DispatchQueue.main.asyncAfter(deadline: .now() + Self.permissionWait) { [self] in
                lock.lock(); let st = state; lock.unlock()
                guard st == .waiting else { return }
                self.onProgress?(Self.permissionMessage(volume: where_.name, kind: where_.kind), nil)
            }
            var failure: Error?
            var done: Int64 = 0
            let total = files.reduce(Int64(0)) { $0 + Int64((try? $1.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) }
            var last = Date.distantPast
            for file in files where failure == nil {
                let h: FileHandle
                do { h = try FileHandle(forReadingFrom: file) }   // blocks here while macOS asks for drive access
                catch {
                    failure = Self.error("Couldn't read \(file.lastPathComponent): \(error.localizedDescription)")
                    break
                }
                set(.reading)
                defer { try? h.close() }
                do {
                    while true {
                        // FileHandle bridges autoreleased NSData. Drain per chunk,
                        // not at the end of a multi-GB background install.
                        let count: Int = try autoreleasepool {
                            guard let chunk = try h.read(upToCount: 8 << 20), !chunk.isEmpty else { return 0 }
                            do { try self.tarIn?.write(contentsOf: chunk) }
                            catch { return 0 } // completeTar reports tar's error
                            return chunk.count
                        }
                        if count == 0 { break }
                        done += Int64(count)
                        if total > 0, Date().timeIntervalSince(last) > 0.25 {
                            last = Date()
                            let frac = Double(done) / Double(total), mb = Double(done) / 1_048_576, all = Double(total) / 1_048_576
                            DispatchQueue.main.async {
                                self.onProgress?(String(format: "Unpacking Wizard OS… %.0f of %.0f MB", mb, all), frac)
                            }
                        }
                    }
                } catch {
                    failure = Self.error("Couldn't read \(file.lastPathComponent): \(error.localizedDescription)")
                }
            }
            set(.finished)
            self.completeTar(error: failure, expectedDigest: nil)
        }
    }

    /// Selected files must be one archive, or the ordered parts of one archive (name.part00, name.part01, … with no
    /// gaps). A lone part other than part00 is a missing part too.
    static func partsProblem(_ files: [URL]) -> String? {
        let partRE = #"\.part[0-9]{2}$"#
        guard files.count > 1 || files.contains(where: { $0.lastPathComponent.range(of: partRE, options: .regularExpression) != nil })
        else { return nil }
        var prefix: String?
        for (i, f) in files.enumerated() {
            let name = f.lastPathComponent
            guard let r = name.range(of: partRE, options: .regularExpression) else {
                return "Choose either one wizard-os-….tar.xz file, or every part of it (….part00, ….part01, …), not a mix."
            }
            let base = String(name[..<r.lowerBound]), num = Int(name[r].dropFirst(5)) ?? -1
            if prefix == nil { prefix = base }
            guard base == prefix else { return "Those parts come from different Wizard OS downloads. Choose the parts of one download." }
            guard num == i else { return "Part \(String(format: "%02d", i)) is missing. Choose every part of the download." }
        }
        return nil
    }

    enum LocationKind { case internalDisk, removable, network }
    static func locationKind(_ url: URL) -> (name: String, kind: LocationKind) {
        let v = try? url.resourceValues(forKeys: [.volumeNameKey, .volumeIsInternalKey, .volumeIsLocalKey,
                                                  .volumeIsRemovableKey, .volumeIsEjectableKey])
        let name = v?.volumeName ?? "that drive"
        if v?.volumeIsLocal == false { return (name, .network) }
        if v?.volumeIsInternal == false || v?.volumeIsRemovable == true || v?.volumeIsEjectable == true { return (name, .removable) }
        return (name, .internalDisk)
    }

    static var permissionWait: TimeInterval {
        let v = UserDefaults.standard.double(forKey: "permissionWaitSeconds"); return v > 0 ? v : 8
    }

    static func permissionMessage(volume: String, kind: LocationKind) -> String {
        switch kind {
        case .removable:
            return "Waiting for macOS to let Wizard read files on “\(volume)”. Click Allow if macOS asks, or turn on Wizard in System Settings › Privacy & Security › Files and Folders › Removable Volumes. You can also move the file into your Downloads folder and choose it again."
        case .network:
            return "Waiting for macOS to let Wizard read files on “\(volume)”. Click Allow if macOS asks, or turn on Wizard in System Settings › Privacy & Security › Files and Folders › Network Volumes. You can also copy the file into your Downloads folder and choose it again."
        case .internalDisk:
            return "Waiting for macOS to let Wizard read this file. Click Allow if macOS asks, or move the file into your Downloads folder and choose it again."
        }
    }

    func install() {
        guard !busy else { onProgress?("Wizard OS is already being set up…", nil); return }
        busy = true   // held from here: the feed request can take seconds and must not race a file install
        onProgress?("Finding the latest Wizard OS…", nil)
        var req = URLRequest(url: Store.osFeedURL); req.timeoutInterval = 8
        session.dataTask(with: req) { data, resp, err in
            DispatchQueue.main.async {
                guard let data, (resp as? HTTPURLResponse)?.statusCode == 200,
                      let feed = try? JSONDecoder().decode(Feed.self, from: data),
                      let list = Self.downloadList(feed) else {
                    self.busy = false
                    self.onDone?(err ?? Self.error("Couldn't reach the Wizard OS download. Check your connection and try again.")); return
                }
                self.expectedSHA = feed.sha256.lowercased(); self.version = feed.version
                do {
                    try Self.checkFreeSpace(install: feed.totalInstallBytes)
                    try self.startTar()
                } catch { self.busy = false; self.onDone?(error); return }
                self.partURLs = list; self.partIndex = 0; self.partHasher = SHA256()
                let partSum = (feed.parts ?? []).reduce(Int64(0)) { $0 + ($1.bytes ?? 0) }
                self.feedBytes = feed.bytes ?? partSum; self.expected = self.feedBytes
                self.onProgress?("Downloading Wizard OS \(feed.version)… \(Self.sizeNote(feed))", 0)
                self.session.dataTask(with: list[0].url).resume()
            }
        }.resume()
    }

    /// The download is unpacked while it arrives: bytes go to the SHA-256 and to `tar -xJf -` at the same time.
    private func startTar() throws {
        let staging = try Self.freshStaging()
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/tar")
        p.arguments = ["-xJf", "-", "-C", staging.path]
        let input = Pipe(), err = Pipe()
        p.standardInput = input; p.standardOutput = FileHandle.nullDevice; p.standardError = err
        do { try p.run() } catch { try? FileManager.default.removeItem(at: staging); throw error }
        tar = p; tarIn = input.fileHandleForWriting; tarErr = err
        hasher = SHA256(); received = 0; expected = 0; failure = nil
    }

    /// One archive, or its parts in order. Part hashes are checked one by one, the whole archive at the end.
    static func downloadList(_ feed: Feed) -> [(url: URL, sha: String)]? {
        if let parts = feed.parts, !parts.isEmpty {
            let list = parts.compactMap { p in URL(string: p.url, relativeTo: Store.osFeedURL).map { ($0, p.sha256.lowercased()) } }
            return list.count == parts.count ? list : nil
        }
        guard let u = feed.url, let url = URL(string: u, relativeTo: Store.osFeedURL) else { return nil }
        return [(url, "")]
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            failure = Self.error("Download failed (HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)).")
            completionHandler(.cancel); return
        }
        // One archive: its length is the total. Parts: the feed's total, or (without one) the sum seen so far.
        if partURLs.count <= 1 { expected = response.expectedContentLength }
        else if feedBytes <= 0 { expected += max(response.expectedContentLength, 0) }
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        hasher.update(data: data); partHasher.update(data: data)
        do { try tarIn?.write(contentsOf: data) } catch {
            failure = Self.error("Unpacking Wizard OS failed. Please try again."); dataTask.cancel(); return
        }
        received += Int64(data.count)
        guard expected > 0, Date().timeIntervalSince(lastProgress) > 0.25 else { return }
        lastProgress = Date()
        let mb = Double(received) / 1_048_576, total = Double(expected) / 1_048_576, v = version
        let frac = Double(received) / Double(expected)
        DispatchQueue.main.async {
            self.onProgress?(String(format: "Downloading and unpacking Wizard OS %@… %.0f of %.0f MB", v, mb, total), frac)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard task is URLSessionDataTask, tar != nil else { return }   // the feed request has its own handler
        if failure == nil, error == nil, partURLs.count > 1 {
            let want = partURLs[partIndex].sha
            let got = partHasher.finalize().map { String(format: "%02x", $0) }.joined()
            if got != want { failure = Self.error("Part \(partIndex + 1) of the Wizard OS download was corrupted. Please try again.") }
            else if partIndex + 1 < partURLs.count {
                partIndex += 1; partHasher = SHA256()
                session.dataTask(with: partURLs[partIndex].url).resume()
                return
            }
        }
        completeTar(error: failure ?? error, expectedDigest: expectedSHA)
    }

    /// Close tar's input and finish: check tar, the whole-archive hash (downloads), then move the OS into place.
    private func completeTar(error: Error?, expectedDigest: String?) {
        guard let p = tar else { return }
        try? tarIn?.close(); tarIn = nil
        p.waitUntilExit(); tar = nil
        let tarText = String(data: tarErr?.fileHandleForReading.readDataToEndOfFile() ?? Data(), encoding: .utf8) ?? ""
        var result: Error? = error
        if result == nil, let want = expectedDigest {
            let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
            if digest != want { result = Self.error("The Wizard OS download was corrupted. Please try again.") }
        }
        if result == nil && p.terminationStatus != 0 { result = Self.error("Unpacking Wizard OS failed: \(tarText.suffix(200))") }
        if let result {
            try? FileManager.default.removeItem(at: Self.staging)
            DispatchQueue.main.async { self.busy = false; self.onDone?(result) }
            return
        }
        DispatchQueue.main.async { self.onProgress?("Setting up Wizard OS on this Mac…", nil) }
        DispatchQueue.global(qos: .userInitiated).async {
            let r = Result { try Self.finish(Self.staging) }
            DispatchQueue.main.async {
                self.busy = false
                if case .failure(let e) = r { self.onDone?(e) } else { self.onDone?(nil) }
            }
        }
    }

    static func error(_ s: String) -> NSError { NSError(domain: "Wizard", code: 1, userInfo: [NSLocalizedDescriptionKey: s]) }

    @discardableResult
    static func run(_ tool: String, _ args: [String]) throws -> String {
        let p = Process(); p.executableURL = URL(fileURLWithPath: tool); p.arguments = args
        let out = Pipe(); p.standardOutput = out; p.standardError = out
        try p.run(); p.waitUntilExit()
        let text = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        if p.terminationStatus != 0 { throw error("\(URL(fileURLWithPath: tool).lastPathComponent) failed: \(text.suffix(300))") }
        return text
    }

    /// Streaming SHA-256 (CryptoKit): about 5x faster than shasum on multi-GB disk images.
    static func sha256(of url: URL) throws -> String {
        let h = try FileHandle(forReadingFrom: url); defer { try? h.close() }
        var hasher = SHA256()
        while try autoreleasepool(invoking: {
            guard let chunk = try h.read(upToCount: 8 << 20), !chunk.isEmpty else { return false }
            hasher.update(data: chunk)
            return true
        }) {}
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    static func verifyManifest(in dir: URL) throws {
        let bad = error("This file isn't a valid Wizard OS image. Download it again from the release page.")
        guard let data = try? Data(contentsOf: dir.appendingPathComponent("manifest.json")),
              let m = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let files = m["files"] as? [String: String], !files.isEmpty else { throw bad }
        for (rel, want) in files {
            guard !rel.contains(".."), FileManager.default.fileExists(atPath: dir.appendingPathComponent(rel).path) else { throw bad }
            let got = try sha256(of: dir.appendingPathComponent(rel))
            guard got == want.lowercased() else { throw bad }
        }
    }

    static func freshStaging() throws -> URL {
        let fm = FileManager.default
        try? fm.removeItem(at: staging)
        try fm.createDirectory(at: staging, withIntermediateDirectories: true)
        return staging
    }

    /// Check the unpacked image, then move it into place (keeping an existing Wizard's disk).
    static func finish(_ staging: URL) throws {
        let fm = FileManager.default
        let dest = WizardShared.osDir
        try verifyManifest(in: staging)
        let rootfs = staging.appendingPathComponent("rootfs.img")
        let disk = staging.appendingPathComponent("disk.img")
        try fm.moveItem(at: rootfs, to: disk)
        // Sparse 64 GB disk: only blocks Wizard actually writes take space on the Mac.
        let h = try FileHandle(forWritingTo: disk); try h.truncate(atOffset: 64 << 30); try h.close()
        if fm.fileExists(atPath: dest.path) {
            // Keep the existing disk (the Wizard's memory, chats and installed apps); only replace boot files.
            // A disk from a different stack (0.1/0.2 bundled Hermes vs the Runtipi-based Wizard OS) can't boot the new
            // kernel's system, so it's kept beside it as disk-previous.img instead and the new disk is used.
            let old = dest.appendingPathComponent("disk.img")
            func stack(_ dir: URL) -> String {
                let m = (try? Data(contentsOf: dir.appendingPathComponent("manifest.json")))
                    .flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                return (m?["stack"] as? String) ?? "bundled-hermes"
            }
            if fm.fileExists(atPath: old.path) {
                if stack(dest) == stack(staging) {
                    try fm.removeItem(at: disk); try fm.moveItem(at: old, to: disk)
                } else {
                    let keep = staging.appendingPathComponent("disk-previous.img")
                    try? fm.removeItem(at: keep); try fm.moveItem(at: old, to: keep)
                }
            }
            if let mac = try? Data(contentsOf: dest.appendingPathComponent("mac-address")) {
                try mac.write(to: staging.appendingPathComponent("mac-address"))
            }
            try fm.removeItem(at: dest)
        }
        try fm.moveItem(at: staging, to: dest)
    }
}

// MARK: - Wizard Host (back-end service) control

enum HostControl {
    static var embeddedHostURL: URL {
        Bundle.main.bundleURL.appendingPathComponent("Contents/Library/LoginItems/Wizard Host.app")
    }

    static var isRunning: Bool {
        !NSRunningApplication.runningApplications(withBundleIdentifier: WizardShared.hostBundleID).isEmpty
    }

    /// Internal MVP: start on demand, never register or change daily login services.
    static func ensureRunning() {
        if !isRunning {
            let cfg = NSWorkspace.OpenConfiguration(); cfg.activates = false; cfg.addsToRecentItems = false
            NSWorkspace.shared.openApplication(at: embeddedHostURL, configuration: cfg) { _, err in
                if let err { NSLog("Wizard: couldn't launch Wizard Host: \(err)") }
            }
        }
    }

    static func send(_ command: String) {
        DistributedNotificationCenter.default().postNotificationName(
            Notification.Name("org.humanitylabs.wizard.mvp.host.command"), object: command, userInfo: nil, deliverImmediately: true)
    }

    static func waitForLocalWizard(timeout: TimeInterval, tick: @escaping (TimeInterval) -> Void, done: @escaping (Bool) -> Void) {
        let start = Date()
        func poll() {
            WizardShared.probeReady { ok in
                DispatchQueue.main.async {
                    if ok { done(true); return }
                    let elapsed = Date().timeIntervalSince(start)
                    if elapsed > timeout { done(false); return }
                    tick(elapsed)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15, execute: poll)
                }
            }
        }
        poll()
    }
}

// MARK: - Native bridge (window.webkit.messageHandlers.wizardNative)

/// One namespaced page→native channel. Capabilities register a handler under a prefix
/// (e.g. "app.", later "meeting."). Message: {id, method, params}; reply via window.wizardNativeReply(id, result).
final class NativeBridge: NSObject, WKScriptMessageHandler {
    static let name = "wizardNative"
    static let shared = NativeBridge()
    typealias Handler = (_ method: String, _ params: [String: Any], _ reply: @escaping (Any?) -> Void) -> Void
    private var handlers: [String: Handler] = [:]

    override init() {
        super.init()
        register("app.") { method, _, reply in
            switch method {
            case "app.info":
                reply(["version": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") ?? "",
                       "backend": Store.active?.kind.rawValue ?? "", "capabilities": Array(NativeBridge.shared.handlers.keys)])
            default: reply(nil)
            }
        }
    }

    func register(_ prefix: String, _ handler: @escaping Handler) { handlers[prefix] = handler }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let web = message.webView, let body = message.body as? [String: Any],
              let method = body["method"] as? String,
              let origin = URL(string: "\(message.frameInfo.securityOrigin.protocol)://\(message.frameInfo.securityOrigin.host)"),
              ["127.0.0.1", "localhost", Store.active.flatMap { URL(string: $0.url)?.host }].contains(origin.host)
        else { return }
        let id = body["id"] ?? NSNull()
        var params = body["params"] as? [String: Any] ?? [:]
        let so = message.frameInfo.securityOrigin
        params["_origin"] = "\(so.protocol)://\(so.host)\(so.port != 0 ? ":\(so.port)" : "")"
        guard let handler = handlers.first(where: { method.hasPrefix($0.key) })?.value else { return }
        handler(method, params) { result in
            let payload = (try? JSONSerialization.data(withJSONObject: ["id": id, "result": result ?? NSNull()], options: [.fragmentsAllowed]))
                .flatMap { String(data: $0, encoding: .utf8) } ?? "null"
            DispatchQueue.main.async {
                web.evaluateJavaScript("window.wizardNativeReply && window.wizardNativeReply(\(payload))")
            }
        }
    }
}

// MARK: - Local voice presentation (Foundation-only; tested separately)

struct LocalVoiceStatus: Decodable {
    let state: String
    let stage: String
    let downloaded: Int64
    let total: Int64

    var isReady: Bool { state == "ready" }
    var canRetry: Bool { ["preparing", "retrying", "error"].contains(state) }
    var summary: String {
        let heading: String
        switch state {
        case "ready": heading = "Local voice ready"
        case "preparing": heading = "Preparing local voice"
        case "retrying": heading = "Local voice retrying"
        default: heading = "Local voice needs attention"
        }
        var parts = [heading]
        if !stage.isEmpty && stage != heading { parts.append(stage) }
        if total > 0 && downloaded >= 0 {
            // Model download is not total preparation: even 100% is not ready
            // until the producer confirms engine/model health.
            let bytes = ByteCountFormatter.string(fromByteCount: downloaded, countStyle: .file)
            let size = ByteCountFormatter.string(fromByteCount: total, countStyle: .file)
            parts.append("Model: \(bytes) / \(size)")
        }
        return parts.joined(separator: " · ")
    }
}

// MARK: - Window

final class WizardWindowController: NSWindowController, WKNavigationDelegate, WKUIDelegate {
    let web: WKWebView
    let overlay = NSView()
    let title = NSTextField(labelWithString: "")
    let subtitle = NSTextField(labelWithString: "")
    let progress = NSProgressIndicator()
    let stack = NSStackView()
    var buttons: [NSButton] = []
    var loadedAt: Date?
    let installer = OSInstaller()
    private let voiceBar = NSView()
    private let voiceLabel = NSTextField(wrappingLabelWithString: "")
    private let voiceRetry = NSButton(title: "Retry", target: nil, action: nil)
    private var voiceHeight: NSLayoutConstraint!
    private var voiceTimer: Timer?
    private var voiceTask: URLSessionDataTask?
    private var voiceGeneration = UUID()
    private var voiceRetryPending = false
    var localVoiceQAState: [String: Any] {
        ["visible": !voiceBar.isHidden, "summary": voiceLabel.stringValue,
         "retryEnabled": voiceRetry.isEnabled, "retryPending": voiceRetryPending,
         "polling": voiceTimer != nil]
    }

    init() {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        cfg.userContentController.add(NativeBridge.shared, name: NativeBridge.name)
        // window.wizardNative.meetings etc. — present only inside Wizard.app; pages fall back to web APIs elsewhere.
        cfg.userContentController.addUserScript(WKUserScript(source: MeetingBridge.adapterJS, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = WKWebView(frame: .zero, configuration: cfg)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 780),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                              backing: .buffered, defer: false)
        window.title = "Wizard"
        window.titlebarAppearsTransparent = true
        window.minSize = NSSize(width: 380, height: 560)
        window.backgroundColor = NSColor(calibratedRed: 0.06, green: 0.06, blue: 0.08, alpha: 1)
        window.appearance = NSAppearance(named: .darkAqua)
        window.setFrameAutosaveName("WizardMainWindow")
        if !window.setFrameUsingName("WizardMainWindow") { window.center() }
        super.init(window: window)

        web.navigationDelegate = self
        web.uiDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        web.customUserAgent = nil
        web.allowsBackForwardNavigationGestures = false

        let root = NSView()
        root.wantsLayer = true
        root.layer?.backgroundColor = window.backgroundColor.cgColor
        window.contentView = root
        voiceBar.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(voiceBar)
        voiceHeight = voiceBar.heightAnchor.constraint(equalToConstant: 0)
        NSLayoutConstraint.activate([voiceBar.leadingAnchor.constraint(equalTo: root.leadingAnchor),
                                     voiceBar.trailingAnchor.constraint(equalTo: root.trailingAnchor),
                                     voiceBar.bottomAnchor.constraint(equalTo: root.bottomAnchor), voiceHeight])
        voiceBar.isHidden = true
        voiceLabel.font = .systemFont(ofSize: 12)
        voiceLabel.maximumNumberOfLines = 3
        voiceLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        voiceRetry.target = self; voiceRetry.action = #selector(retryLocalVoice)
        voiceRetry.bezelStyle = .rounded
        for v in [voiceLabel, voiceRetry] { v.translatesAutoresizingMaskIntoConstraints = false; voiceBar.addSubview(v) }
        NSLayoutConstraint.activate([voiceLabel.leadingAnchor.constraint(equalTo: voiceBar.leadingAnchor, constant: 14),
                                     voiceLabel.centerYAnchor.constraint(equalTo: voiceBar.centerYAnchor),
                                     voiceLabel.trailingAnchor.constraint(equalTo: voiceRetry.leadingAnchor, constant: -10),
                                     voiceRetry.trailingAnchor.constraint(equalTo: voiceBar.trailingAnchor, constant: -14),
                                     voiceRetry.centerYAnchor.constraint(equalTo: voiceBar.centerYAnchor)])
        for v in [web, overlay] {
            v.translatesAutoresizingMaskIntoConstraints = false
            root.addSubview(v)
            NSLayoutConstraint.activate([v.leadingAnchor.constraint(equalTo: root.leadingAnchor),
                                         v.trailingAnchor.constraint(equalTo: root.trailingAnchor),
                                         v.topAnchor.constraint(equalTo: root.topAnchor),
                                         v.bottomAnchor.constraint(equalTo: voiceBar.topAnchor)])
        }
        overlay.wantsLayer = true
        overlay.layer?.backgroundColor = window.backgroundColor.cgColor
        buildOverlay()
    }
    required init?(coder: NSCoder) { fatalError() }

    private func buildOverlay() {
        let mark = NSTextField(labelWithString: "✦")
        mark.font = .systemFont(ofSize: 44, weight: .light)
        mark.textColor = NSColor(calibratedRed: 0.72, green: 0.62, blue: 1, alpha: 1)
        title.font = .systemFont(ofSize: 24, weight: .semibold)
        title.textColor = .white
        title.alignment = .center
        subtitle.font = .systemFont(ofSize: 14)
        subtitle.textColor = NSColor(white: 0.72, alpha: 1)
        subtitle.alignment = .center
        subtitle.maximumNumberOfLines = 4
        subtitle.preferredMaxLayoutWidth = 420
        subtitle.lineBreakMode = .byWordWrapping
        progress.style = .bar
        progress.isIndeterminate = true
        progress.controlSize = .small
        progress.widthAnchor.constraint(equalToConstant: 280).isActive = true
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        [mark, title, subtitle, progress].forEach { stack.addArrangedSubview($0) }
        stack.setCustomSpacing(6, after: title)
        overlay.addSubview(stack)
        NSLayoutConstraint.activate([stack.centerXAnchor.constraint(equalTo: overlay.centerXAnchor),
                                     stack.centerYAnchor.constraint(equalTo: overlay.centerYAnchor),
                                     stack.widthAnchor.constraint(lessThanOrEqualToConstant: 460)])
    }

    func showOverlay(_ t: String, _ s: String, progress p: Double? = nil, spinning: Bool = true, actions: [(String, Selector)] = []) {
        overlay.isHidden = false
        title.stringValue = t
        subtitle.stringValue = s
        progress.isHidden = !spinning
        if let p { progress.isIndeterminate = false; progress.doubleValue = p * 100 }
        else { progress.isIndeterminate = true; progress.startAnimation(nil) }
        buttons.forEach { $0.removeFromSuperview() }
        buttons = actions.enumerated().map { i, a in
            let b = NSButton(title: a.0, target: self, action: a.1)
            b.bezelStyle = .rounded
            b.controlSize = .large
            if i == 0 { b.keyEquivalent = "\r" }
            b.widthAnchor.constraint(greaterThanOrEqualToConstant: 300).isActive = true
            stack.addArrangedSubview(b)
            return b
        }
    }

    // The bar belongs to the native window, not onboarding's WK page. It stays
    // visible after /api/finish redirects into Wizard UX, including ready state.
    private func clearLocalVoice() {
        voiceGeneration = UUID()
        voiceTimer?.invalidate(); voiceTimer = nil
        voiceTask?.cancel(); voiceTask = nil
        voiceRetryPending = false
        voiceBar.isHidden = true; voiceHeight.constant = 0
        voiceLabel.stringValue = ""; voiceLabel.toolTip = nil
        voiceRetry.isEnabled = false
    }

    private func startLocalVoice() {
        clearLocalVoice()
        guard Store.active?.kind == .thisMac else { return }
        voiceBar.isHidden = false; voiceHeight.constant = 64
        voiceLabel.stringValue = "Checking local voice preparation…"
        pollLocalVoice()
        voiceTimer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in self?.pollLocalVoice() }
    }

    private func voiceURL(_ path: String) -> URL {
        URL(string: path, relativeTo: WizardShared.localSetupURL)!.absoluteURL
    }

    private func pollLocalVoice() {
        guard Store.active?.kind == .thisMac, !voiceBar.isHidden, voiceTask == nil, !voiceRetryPending else { return }
        let generation = voiceGeneration
        var request = URLRequest(url: voiceURL("/api/voice/status"), cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 5)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        voiceTask = URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            let status = data.flatMap { (response as? HTTPURLResponse)?.statusCode == 200
                ? try? JSONDecoder().decode(LocalVoiceStatus.self, from: $0) : nil }
            DispatchQueue.main.async {
                guard let self, self.voiceGeneration == generation, Store.active?.kind == .thisMac else { return }
                self.voiceTask = nil
                self.voiceLabel.stringValue = status?.summary ?? "Local voice status unavailable — Retry to request preparation."
                self.voiceLabel.toolTip = self.voiceLabel.stringValue
                self.voiceRetry.isEnabled = status?.canRetry ?? true
            }
        }
        voiceTask?.resume()
    }

    @objc private func retryLocalVoice() {
        guard Store.active?.kind == .thisMac, !voiceBar.isHidden, !voiceRetryPending else { return }
        // Fence a pre-retry GET response as well as responses from old backends.
        voiceTask?.cancel(); voiceTask = nil
        voiceGeneration = UUID()
        let generation = voiceGeneration
        voiceRetryPending = true; voiceRetry.isEnabled = false
        voiceLabel.stringValue = "Requesting local voice preparation…"
        var request = URLRequest(url: voiceURL("/api/voice/retry"), timeoutInterval: 8)
        request.httpMethod = "POST"
        voiceTask = URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            let accepted = (response as? HTTPURLResponse)?.statusCode == 202
            DispatchQueue.main.async {
                guard let self, self.voiceGeneration == generation, Store.active?.kind == .thisMac else { return }
                self.voiceTask = nil; self.voiceRetryPending = false
                self.voiceLabel.stringValue = accepted ? "Preparation requested — waiting for local voice status."
                    : "Could not request local voice preparation. Try again."
                self.voiceLabel.toolTip = self.voiceLabel.stringValue
                self.voiceRetry.isEnabled = true
                // A queued systemd start is never labelled ready. Poll the sole
                // producer again on the timer, without manufacturing progress.
            }
        }
        voiceTask?.resume()
    }

    // MARK: Flow

    func begin() {
        clearLocalVoice()
        homeURL = nil; resolvedOrigins = []
        guard let backend = Store.active else { showChooser(); return }
        switch backend.kind {
        case .thisMac:
            guard WizardShared.filesFolder != nil else { askFilesFolder(); return }
            guard WizardShared.osInstalled else { installOnThisMac(); return }
            connectLocal()
        case .remote:
            showOverlay("Connecting…", backend.name, spinning: true)
            if let url = URL(string: backend.url) { resolveHome(url) { [weak self] home in self?.homeURL = home; self?.load(home) } }
        }
    }

    // MARK: Wizard UX (wizard-ux) and the native bridge (wizard-os spec/NATIVE_BRIDGE.md)

    /// Where this window's Wizard lives right now: Wizard UX when the back end serves it, else the address as given.
    var homeURL: URL?
    func loadHome() {
        if let homeURL { load(homeURL); return }
        if let b = Store.active, let u = URL(string: b.url) { load(u) }
    }

    /// Wizard UX is served at /wizard-os-home/ on a Wizard's origin and picks its desktop shell inside this app.
    /// A root or legacy /wizard/ address is upgraded to it when the back end answers there; a deeper address stays as typed.
    /// `defaults write org.humanitylabs.wizard.mvp LegacyUX -bool true` keeps the old UX.
    func resolveHome(_ base: URL, done: @escaping (URL) -> Void) {
        let p = base.path.isEmpty ? "/" : base.path
        guard !UserDefaults.standard.bool(forKey: "LegacyUX"), p == "/" || p == "/wizard" || p.hasPrefix("/wizard/"),
              let scheme = base.scheme, let host = base.host else { done(base); return }
        var c = URLComponents(); c.scheme = scheme; c.host = host; c.port = base.port
        guard let origin = c.url, let entry = URL(string: "/wizard-os-home/", relativeTo: origin)?.absoluteURL,
              let probe = URL(string: "desktop.html", relativeTo: entry)?.absoluteURL else { done(base); return }
        var req = URLRequest(url: probe, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 4)
        req.httpMethod = "GET"
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200 && (data.map { String(decoding: $0.prefix(4096), as: UTF8.self) }?.contains("data-shell") ?? false)
            NSLog("Wizard: Wizard UX %@ at %@", ok ? "found" : "not found", entry.absoluteString)
            DispatchQueue.main.async { done(ok ? entry : base) }
        }.resume()
    }

    /// Native → page: dispatch a bridge event when the page is Wizard UX and handles it.
    /// Calls back nil when it isn't (legacy UX, onboarding, still loading) so callers can fall back.
    /// For wizard:orb it waits for the page's wizard:orb-state answer.
    func uxSend(_ event: String, _ detail: [String: Any], done: @escaping (String?) -> Void) {
        let js = """
        const ux = window.wizardUX;
        if (!ux || !Array.isArray(ux.events) || !ux.events.includes(name)) return null;
        if (name !== 'wizard:orb') { window.dispatchEvent(new CustomEvent(name, { detail })); return 'sent'; }
        return await new Promise(res => {
          const t = setTimeout(() => res('pending'), 2000);
          window.addEventListener('wizard:orb-state', e => { clearTimeout(t); res((e.detail && e.detail.state) || 'none'); }, { once: true });
          window.dispatchEvent(new CustomEvent(name, { detail }));
        });
        """
        web.callAsyncJavaScript(js, arguments: ["name": event, "detail": detail], in: nil, in: .page) { r in
            switch r {
            case .success(let v): done(v as? String)
            case .failure(let e): NSLog("Wizard: bridge %@ failed: %@", event, e.localizedDescription); done(nil)
            }
        }
    }

    /// Is the page in the window Wizard UX (bridge ready)?
    func uxState(_ done: @escaping ([String: Any]?) -> Void) {
        web.evaluateJavaScript("window.wizardUX ? JSON.stringify(window.wizardUX) : ''") { r, _ in
            let s = (r as? String) ?? ""
            done(s.isEmpty ? nil : (try? JSONSerialization.jsonObject(with: Data(s.utf8))) as? [String: Any])
        }
    }

    func showChooser() {
        clearLocalVoice()
        showOverlay("Where should Wizard live?",
                    "Wizard is your own AI with its own computer. Run it on this Mac, or connect to a Wizard you already have on another computer.",
                    spinning: false,
                    actions: [("On this Mac", #selector(chooseThisMac)),
                              ("On another computer…", #selector(chooseRemote))])
    }

    @objc func chooseThisMac() {
        var list = Store.backends.filter { $0.kind != .thisMac }
        list.insert(Backend(kind: .thisMac, name: "This Mac", url: WizardShared.localSetupURL.absoluteString), at: 0)
        Store.backends = list; Store.activeIndex = 0
        begin()
    }

    @objc func chooseRemote() {
        let alert = NSAlert()
        alert.messageText = "Connect to a Wizard on another computer"
        alert.informativeText = "Paste the address of that computer's Wizard (for example https://wizard.your-tailnet.ts.net or http://192.168.1.20:8923)."
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 360, height: 24))
        field.placeholderString = "https://…"
        alert.accessoryView = field
        alert.addButton(withTitle: "Connect"); alert.addButton(withTitle: "Cancel")
        alert.window.initialFirstResponder = field
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        var text = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.contains("://") { text = "https://" + text }
        guard let url = URL(string: text), let host = url.host, ["http", "https"].contains(url.scheme ?? "") else {
            showOverlay("That address doesn't look right", text, spinning: false,
                        actions: [("Try again", #selector(chooseRemote)), ("Back", #selector(backToChooser))]); return
        }
        var list = Store.backends.filter { $0.url != url.absoluteString }
        list.append(Backend(kind: .remote, name: host, url: url.absoluteString))
        Store.backends = list; Store.activeIndex = list.count - 1
        (NSApp.delegate as? AppDelegate)?.rebuildWizardMenu()
        begin()
    }

    /// First run on this Mac: where the Wizard keeps its files. The folder is shared into Wizard OS (virtio-fs) as the
    /// apps' user-files folder; app databases stay on the Wizard OS disk.
    func askFilesFolder(sizeNote: String? = nil) {
        let home = WizardShared.defaultFilesFolder
        let title = "Keep your Wizard's files in ~/\(home.lastPathComponent)?"
        showOverlay(title,
                    "Your Wizard and its apps put what they make here: Inbox, Documents, Videos, Meetings and Exports. "
                    + "You can open the folder in Finder any time." + (sizeNote.map { "\n\n" + $0 } ?? ""),
                    spinning: false,
                    actions: [("Use ~/\(home.lastPathComponent)", #selector(useDefaultFilesFolder)),
                              ("Choose Folder…", #selector(chooseFilesFolder)),
                              ("Back", #selector(backToChooser))])
        // Say how much space Wizard OS will take before anything downloads (only on this Mac's first install).
        if sizeNote == nil && !WizardShared.osInstalled {
            installer.fetchSizeNote { [weak self] note in
                guard let self, let note, self.title.stringValue == title, !self.overlay.isHidden else { return }
                self.askFilesFolder(sizeNote: note)
            }
        }
    }

    @objc func useDefaultFilesFolder() { setFilesFolder(WizardShared.defaultFilesFolder) }

    @objc func chooseFilesFolder() {
        let panel = NSOpenPanel()
        panel.message = "Choose the folder for your Wizard's files"
        panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser
        guard panel.runModal() == .OK, let url = panel.url else { return }
        setFilesFolder(url)
    }

    func setFilesFolder(_ url: URL) {
        do {
            try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
            try WizardShared.setFilesFolder(url)
        } catch {
            showOverlay("Couldn't use that folder", error.localizedDescription, spinning: false,
                        actions: [("Choose Folder…", #selector(chooseFilesFolder)), ("Back", #selector(backToChooser))])
            return
        }
        // A running Wizard OS picks the share up on its next start.
        if WizardShared.osInstalled { HostControl.send("restart") }
        begin()
    }

    @objc func backToChooser() { showChooser() }
    @objc func retryInstall() { installOnThisMac() }
    @objc func retry() { begin() }

    func installOnThisMac() {
        showOverlay("Setting up Wizard on this Mac", "Downloading Wizard OS, a small Linux computer just for your Wizard. This happens once.", progress: nil)
        installer.onProgress = { [weak self] msg, p in
            self?.showOverlay("Setting up Wizard on this Mac", msg, progress: p)
        }
        installer.onDone = { [weak self] err in
            guard let self else { return }
            if let err {
                // A bad picked file says so; an unreachable feed just shows the GitHub steps.
                if err.localizedDescription.contains("free space") {
                    self.showOverlay("Not enough space for Wizard OS", err.localizedDescription, spinning: false,
                                     actions: [("Try Again", #selector(self.retryInstall)), ("Back", #selector(self.backToChooser))])
                    return
                }
                let bad = err.localizedDescription.contains("valid Wizard OS")
                self.showGetOS(note: bad ? err.localizedDescription : nil)
            } else {
                HostControl.send("start")
                self.connectLocal()
            }
        }
        installer.install()
    }

    /// When the automatic download fails, the person can download the archive in their browser and choose it here.
    func showGetOS(note: String? = nil) {
        showOverlay("Get Wizard OS",
                    (note.map { $0 + "\n\n" } ?? "") + "1. Click Download Wizard OS and save the wizard-os-….tar.xz file.\n2. Come back here and click Choose Downloaded File.",
                    spinning: false,
                    actions: [("Download Wizard OS", #selector(openReleasePage)),
                              ("Choose Downloaded File…", #selector(chooseOSFile)),
                              ("Back", #selector(backToChooser))])
    }

    /// Opens the archive named by the feed in the browser (every part, if it comes in parts); the try-wizard
    /// releases page if the feed itself can't be read.
    @objc func openReleasePage() {
        var req = URLRequest(url: Store.osFeedURL); req.timeoutInterval = 8
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            let f = data.flatMap { (resp as? HTTPURLResponse)?.statusCode == 200 ? try? JSONDecoder().decode(OSInstaller.Feed.self, from: $0) : nil }
            let names = f.map { $0.parts?.map(\.url) ?? ($0.url.map { [$0] } ?? []) } ?? []
            let urls = names.compactMap { URL(string: $0, relativeTo: Store.osFeedURL)?.absoluteURL }
            DispatchQueue.main.async {
                if urls.isEmpty { NSWorkspace.shared.open(URL(string: "https://github.com/humanitylabs-org/try-wizard/releases/latest")!) }
                else { urls.forEach { NSWorkspace.shared.open($0) } }
            }
        }.resume()
    }

    @objc func chooseOSFile() {
        let panel = NSOpenPanel()
        panel.message = "Choose the wizard-os-….tar.xz file you downloaded (select every part if it came in parts)"
        panel.allowedContentTypes = []; panel.allowsOtherFileTypes = true; panel.allowsMultipleSelection = true
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        guard panel.runModal() == .OK, !panel.urls.isEmpty else { return }
        showOverlay("Setting up Wizard on this Mac", "Checking \(panel.urls.count == 1 ? panel.urls[0].lastPathComponent : "\(panel.urls.count) files")…", progress: nil)
        installer.install(from: panel.urls)
    }

    func connectLocal() {
        startLocalVoice()
        let started = Date()
        HostControl.ensureRunning()
        HostControl.send("start")
        var shown = false
        HostControl.waitForLocalWizard(timeout: 120, tick: { [weak self] elapsed in
            guard let self, Store.active?.kind == .thisMac, !self.voiceBar.isHidden else { return }
            if elapsed > 0.6 && !shown { shown = true; self.showOverlay("Waking up your Wizard…", "Starting Wizard OS on this Mac.") }
        }, done: { [weak self] ok in
            guard let self, Store.active?.kind == .thisMac, !self.voiceBar.isHidden else { return }
            if ok {
                NSLog("Wizard: local back end ready after %.2fs", Date().timeIntervalSince(started))
                self.load(WizardShared.localSetupURL)
            } else {
                self.showOverlay("Wizard OS didn't start", "Open the Wizard menu-bar icon → Show Logs, or try again.", spinning: false,
                                 actions: [("Try again", #selector(self.retry)), ("Back", #selector(self.backToChooser))])
            }
        })
    }

    func load(_ url: URL) {
        loadedAt = nil
        web.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20))
    }

    // MARK: WKNavigationDelegate

    var onNavigate: () -> Void = {}
    /// Origins already checked for Wizard UX this session (so a legacy-only back end isn't probed on every load).
    var resolvedOrigins: Set<String> = []

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // Landed on the legacy UX root (e.g. local onboarding redirects to /wizard/): switch to Wizard UX once if served.
        if homeURL == nil, let u = webView.url, u.path == "/wizard" || u.path == "/wizard/", let h = u.host {
            let key = "\(u.scheme ?? "")://\(h):\(u.port ?? 0)"
            if !resolvedOrigins.contains(key) {
                resolvedOrigins.insert(key)
                resolveHome(u) { [weak self] home in
                    guard let self, home != u else { return }
                    self.homeURL = home; self.load(home)
                }
            }
        }
        onNavigate()
        loadedAt = Date()
        localRetries = 0
        overlay.isHidden = true
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        loadFailed(error)
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { loadFailed(error) }

    private var localRetries = 0

    private func loadFailed(_ error: Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        // Wizard OS on this Mac may still be bringing a service up: retry quietly before showing an error.
        if Store.active?.kind == .thisMac, localRetries < 12 {
            localRetries += 1
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in self?.load(WizardShared.localSetupURL) }
            return
        }
        localRetries = 0
        let name = Store.active?.name ?? "Wizard"
        showOverlay("Can't reach \(name)", error.localizedDescription, spinning: false,
                    actions: [("Try again", #selector(retry)), ("Choose another Wizard", #selector(backToChooser))])
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.allow); return }
        if action.targetFrame == nil || (action.navigationType == .linkActivated && !isWizardOrigin(url)) {
            if ["http", "https", "mailto"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.beginSheetModal(for: window!) { completionHandler($0 == .OK ? panel.urls : nil) }
    }

    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo,
                 type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        var c = URLComponents(); c.scheme = origin.protocol; c.host = origin.host
        if origin.port != 0 { c.port = origin.port }
        decisionHandler(c.url.map(isWizardOrigin) == true ? .grant : .deny)
    }

    private func isWizardOrigin(_ url: URL) -> Bool {
        if url.host == "127.0.0.1" || url.host == "localhost" { return true }
        if let b = Store.active, let h = URL(string: b.url)?.host { return url.host == h }
        return false
    }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var controller: WizardWindowController!
    let wizardsMenu = NSMenu(title: "Wizard")
    let statusMenu = WizardStatusMenu()
    let statusActions = WizardStatusActions()
    var bindingsTimer: Timer?
    var quitDeadline: TimeInterval = 0
    var quitTimer: Timer?
    var quitKeyMonitor: Any?
    lazy var quitHint: NSPanel = {
        let panel = WizStyle.panel(NSRect(x: 0, y: 0, width: 340, height: 58))
        panel.ignoresMouseEvents = true
        let label = WizStyle.label("Press ⌘Q again to quit", size: 17, weight: .semibold)
        label.frame = NSRect(x: 20, y: 17, width: 300, height: 25)
        panel.contentView?.addSubview(label)
        return panel
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        signal(SIGPIPE, SIG_IGN)   // a failed tar must surface as a write error, not kill the app
        NSApp.appearance = NSAppearance(named: .darkAqua)
        buildMenus()
        installQAHooks()
        controller = WizardWindowController()
        controller.window?.delegate = self
        controller.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
        controller.begin()
        installQuitGuard()
        installWizardKey()
        installMeetings()
    }

    // MARK: Mizel: native capture, floating recorder, call prompts, voice keys

    func installMeetings() {
        MeetingBridge.register(origin: { [weak self] in self?.wizardOrigin })
        MeetingSpool.shared.kick()   // deliver anything left from a previous run
        let panel = RecorderPanel.shared
        panel.onExpand = { [weak self] url in
            guard let self, let u = URL(string: url) else { return }
            if let o = self.wizardOrigin, u.host == o.host, let c = URLComponents(url: u, resolvingAgainstBaseURL: false) {
                var p = c.percentEncodedPath; if let q = c.percentEncodedQuery { p += "?" + q }; if let f = c.percentEncodedFragment { p += "#" + f }
                self.openView(p)
            } else { self.showMainWindow(); self.controller.load(u) }
        }
        panel.shouldShow = { [weak self] in
            guard let self, NSApp.isActive, self.controller.window?.isVisible == true, self.controller.window?.isMiniaturized == false,
                  let s = MeetingRecorder.shared.session, let u = self.controller.web.url else { return true }
            // Mizel already shows this recording in the window.
            return !(u.path.contains("/meetings") && (u.fragment ?? "").contains(s.meetingId))
        }
        for n in [NSApplication.didBecomeActiveNotification, NSApplication.didResignActiveNotification, NSWindow.didMiniaturizeNotification,
                  NSWindow.didDeminiaturizeNotification, NSWindow.willCloseNotification] {
            NotificationCenter.default.addObserver(forName: n, object: nil, queue: .main) { _ in DispatchQueue.main.async { panel.sync() } }
        }
        controller.onNavigate = { panel.sync() }

        CallPrompt.shared.onRecord = { [weak self] title, eventId in self?.recordNew(title: title, eventId: eventId) }
        CallDetector.shared.origin = { [weak self] in self?.wizardOrigin }
        CallDetector.shared.install()

        let vk = VoiceKeys.shared
        vk.origin = { [weak self] in self?.wizardOrigin }
        vk.orb = { [weak self] start in self?.orb(start) }
        VoiceKeys.deliverInWizard = { [weak self] text, done in
            guard let self, NSApp.isActive, self.controller.window?.isKeyWindow == true else { done(false); return }
            self.controller.uxSend("wizard:dictation", ["text": text]) { done($0 != nil) }
        }
        vk.install(prompt: false)

        statusActions.isRecording = { MeetingRecorder.shared.isRecording }
        statusActions.recordToggle = { [weak self] in
            if MeetingRecorder.shared.isRecording { MeetingRecorder.shared.stop(finalize: true) { _ in } }
            else { self?.recordNew(title: nil, eventId: CallDetector.shared.currentEvent()?["id"] as? String) }
        }
    }

    func recordNew(title: String?, eventId: String?) {
        guard let o = wizardOrigin else { return }
        let clean = title.map { $0.replacingOccurrences(of: "^(Call: |Starting now: )", with: "", options: .regularExpression) }
        MeetingRecorder.shared.startNew(origin: o, title: eventId == nil ? clean : nil, calendarEventId: eventId) { err in
            if let err {
                let a = NSAlert(); a.messageText = "Couldn't start recording"; a.informativeText = err.localizedDescription; a.runModal()
            }
        }
    }

    /// Right ⌘: talk to your Wizard with its own orb (new thread → voice; tap again → finish and send).
    /// Wizard UX gets a wizard:orb event and answers with its state; the legacy UX is driven through its buttons.
    func orb(_ start: Bool) {
        guard let o = wizardOrigin else { return }
        showMainWindow()
        _ = start
        // One toggle: recording → finish and send; idle → start voice (opening a new thread if no chat is open).
        let legacy = "(() => { const f = document.querySelector('button.voice-fab'); const l = f ? (f.getAttribute('aria-label')||'') : ''; if (f && /Finish and send/.test(l)) { f.click(); return 'sent'; } if (/Opening microphone|Transcribing/.test(l)) return 'busy'; if (f && !f.disabled && /Start voice/.test(l)) { f.click(); return 'voice'; } const n = document.querySelector('button.new-thread-fab'); if (n) { n.click(); return 'new'; } return 'none'; })()"
        var tries = 0
        func retry() {
            guard tries < 25 else { MeetingLog.log("orb: gave up"); return }
            tries += 1
            if tries == 1, start, let u = controller.web.url, u.path.contains("/meetings") || u.path.contains("/files") || u.path.contains("/apps") {
                controller.loadHome()
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: attempt)
        }
        func attempt() {
            controller.uxSend("wizard:orb", ["action": "toggle"]) { [weak self] state in
                guard let self else { return }
                // Wizard UX answered (voice / sent / busy / none): it owns the outcome.
                if let state { MeetingLog.log("orb (bridge): \(state)"); return }
                self.controller.web.evaluateJavaScript(legacy) { r, _ in
                    let res = (r as? String) ?? "none"
                    MeetingLog.log("orb (legacy): \(res)")
                    if res == "none" { retry() }
                }
            }
        }
        _ = o
        attempt()
    }

    // MARK: Wizard key, search, menu bar

    /// Origin of the Wizard this window is showing (the place views like /meetings/ live).
    var wizardOrigin: URL? {
        let base = controller.web.url ?? Store.active.flatMap { URL(string: $0.url) }
        guard let u = base, let scheme = u.scheme, let host = u.host, ["http", "https"].contains(scheme) else { return nil }
        var c = URLComponents(); c.scheme = scheme; c.host = host; c.port = u.port
        return c.url
    }

    func installWizardKey() {
        statusActions.statusLine = { [weak self] in self?.statusLine() ?? "" }
        statusActions.isLocal = { Store.active?.kind == .thisMac }
        statusActions.open = { [weak self] path in self?.openView(path) }
        statusActions.show = { [weak self] in self?.showMainWindow() }
        statusActions.quit = { if Store.active?.kind == .thisMac { HostControl.send("quit") }; NSApp.terminate(nil) }
        statusActions.toggleVoice = { VoiceKeys.enabled.toggle(); VoiceKeys.shared.install(prompt: VoiceKeys.enabled) }
        statusMenu.install(statusActions)

        let search = WizardSearch.shared
        search.origin = { [weak self] in self?.wizardOrigin }
        search.onOpen = { [weak self] path in self?.openView(path) }
        WizardBindings.onChange = { search.rebuildCatalog(apps: []); search.refreshApps() }

        let key = WizardKey.shared
        key.onTap = { WizardSearch.shared.toggle() }
        key.onChord = { [weak self] c in
            if c == " " { WizardSearch.shared.toggle(); return }
            if let b = WizardBindings.current.first(where: { $0.key == String(c) }), let p = b.open { self?.openView(p) }
        }
        key.install()
        if CapsLockRemap.enabled { CapsLockRemap.install() }

        WizardBindings.refresh(origin: wizardOrigin)
        bindingsTimer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { [weak self] _ in
            WizardBindings.refresh(origin: self?.wizardOrigin)
        }
    }

    func statusLine() -> String {
        guard let b = Store.active else { return "Wizard isn't set up yet" }
        if b.kind == .remote { return "Connected to \(b.name)" }
        guard let d = try? Data(contentsOf: WizardShared.statusFile),
              let s = try? JSONSerialization.jsonObject(with: d) as? [String: Any], let state = s["state"] as? String else {
            return "Wizard OS on this Mac"
        }
        switch state {
        case "running": return "Wizard is running on this Mac"
        case "starting": return "Wizard OS is starting…"
        case "stopped": return "Wizard OS is stopped"
        case "notInstalled": return "Wizard OS is not installed"
        case "stopping": return "Wizard OS is shutting down…"
        default: return "Wizard OS hit a problem — see logs"
        }
    }

    func showMainWindow() {
        NSApp.setActivationPolicy(.regular)
        controller.showWindow(nil)
        controller.window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Open a Wizard view (path on the Wizard's own origin) in the main window.
    func openView(_ path: String) {
        guard let origin = wizardOrigin, let url = URL(string: path, relativeTo: origin)?.absoluteURL,
              url.host == origin.host else { return }
        showMainWindow()
        // Wizard UX opens it as a window on its desktop; anything else navigates the page.
        controller.uxSend("wizard:open", ["path": path]) { [weak self] r in
            if r == nil { self?.controller.load(url) }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { showMainWindow() }
        return true
    }

    // Closing the window keeps Wizard in the menu bar (Wizard key, search, meeting detection keep working).
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func windowWillClose(_ notification: Notification) {
        DispatchQueue.main.async { NSApp.setActivationPolicy(.accessory) }
    }
    func applicationWillTerminate(_ notification: Notification) {
        // Leave the keyboard as we found it when Wizard isn't running.
        if CapsLockRemap.active { CapsLockRemap.remove() }
        // Chunks already on disk upload at next launch; flush the current partial chunk now.
        if let s = MeetingRecorder.shared.session { s.me.stop(); s.them?.stop(); MeetingSpool.shared.markDone(s.meetingId) }
    }

    func buildMenus() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Wizard", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Wizard", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Wizard", action: #selector(requestGuardedQuit(_:)), keyEquivalent: "q").target = self
        appItem.submenu = appMenu

        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit

        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "View")
        view.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r").target = self
        view.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        view.items.last?.keyEquivalentModifierMask = [.command, .control]
        viewItem.submenu = view

        let wizItem = NSMenuItem(); main.addItem(wizItem)
        wizItem.submenu = wizardsMenu
        rebuildWizardMenu()

        let winItem = NSMenuItem(); main.addItem(winItem)
        let win = NSMenu(title: "Window")
        win.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "Close App", action: #selector(closeWizardApp(_:)), keyEquivalent: "w").target = self
        winItem.submenu = win
        NSApp.windowsMenu = win
        NSApp.mainMenu = main
    }

    func rebuildWizardMenu() {
        wizardsMenu.removeAllItems()
        for (i, b) in Store.backends.enumerated() {
            let item = NSMenuItem(title: b.name, action: #selector(switchBackend(_:)), keyEquivalent: i < 9 ? "\(i + 1)" : "")
            item.tag = i; item.target = self
            item.state = (i == Store.activeIndex) ? .on : .off
            wizardsMenu.addItem(item)
        }
        if !Store.backends.isEmpty { wizardsMenu.addItem(.separator()) }
        wizardsMenu.addItem(withTitle: "Run Wizard on This Mac", action: #selector(addThisMac), keyEquivalent: "").target = self
        wizardsMenu.addItem(withTitle: "Connect to Another Computer…", action: #selector(addRemote), keyEquivalent: "").target = self
        wizardsMenu.addItem(withTitle: "Install Wizard OS from File…", action: #selector(installFromFile), keyEquivalent: "").target = self
        wizardsMenu.addItem(.separator())
        wizardsMenu.addItem(withTitle: "Show Wizard Files in Finder", action: #selector(showFilesFolder), keyEquivalent: "").target = self
        wizardsMenu.addItem(withTitle: "Restart Wizard OS on This Mac", action: #selector(restartLocal), keyEquivalent: "").target = self
    }

    // QA hooks (only when `defaults write org.humanitylabs.wizard.mvp QAHooks -bool true`).
    func installQAHooks() {
        guard UserDefaults.standard.bool(forKey: "QAHooks") else { return }
        DistributedNotificationCenter.default().addObserver(self, selector: #selector(qa(_:)),
            name: Notification.Name("org.humanitylabs.wizard.mvp.qa"), object: nil, suspensionBehavior: .deliverImmediately)
    }

    @objc func qa(_ n: Notification) {
        guard let cmd = n.object as? String else { return }
        let parts = cmd.split(separator: " ", maxSplits: 1).map(String.init)
        let arg = parts.count > 1 ? parts[1] : ""
        switch parts[0] {
        case "choose-this-mac": addThisMac()
        case "reload": controller.begin()
        case "voice-retry": controller.perform(NSSelectorFromString("retryLocalVoice"))
        case "files-folder": controller.setFilesFolder(arg.isEmpty ? WizardShared.defaultFilesFolder : URL(fileURLWithPath: arg))
        case "choose-this-mac-offline":
            // Simulate a Mac that can't reach the download feed.
            UserDefaults.standard.set("http://127.0.0.1:9/none.json", forKey: "osFeedURL"); addThisMac()
        case "install-file":
            // Same path as "Choose Wizard OS File…" after the user picks a file.
            // Several files (parts) are separated by "|".
            let urls = arg.split(separator: "|").map { URL(fileURLWithPath: String($0)) }
            controller.showOverlay("Setting up Wizard on this Mac", "Checking \(urls.first?.lastPathComponent ?? "")…", progress: nil)
            controller.installer.install(from: urls)
        case "connect":
            var list = Store.backends.filter { $0.url != arg }
            list.append(Backend(kind: .remote, name: URL(string: arg)?.host ?? arg, url: arg))
            Store.backends = list; Store.activeIndex = list.count - 1; rebuildWizardMenu(); controller.begin()
        case "switch": Store.activeIndex = Int(arg) ?? 0; rebuildWizardMenu(); controller.begin()
        case "eval":
            controller.web.evaluateJavaScript(arg) { r, e in
                let s = e.map { "ERROR \($0)" } ?? String(describing: r ?? "nil")
                try? s.write(toFile: "/tmp/wizard-mvp-qa-eval.txt", atomically: true, encoding: .utf8)
            }
        case "snapshot": snapshot(to: arg.isEmpty ? "/tmp/wizard-mvp-qa.png" : arg)
        case "search": WizardSearch.shared.show(); if !arg.isEmpty { WizardSearch.shared.field.stringValue = arg; WizardSearch.shared.filter() }
        case "search-open": WizardSearch.shared.openSelected()
        case "search-snapshot":
            let p = WizardSearch.shared.panel
            if let v = p.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) {
                v.cacheDisplay(in: v.bounds, to: rep)
                try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: arg.isEmpty ? "/tmp/wizard-mvp-qa-search.png" : arg))
            }
        case "wizard-key": // simulate the physical key path: down, optional chord letter, up
            WizardKey.shared.handle(id: 1, pressed: true)
            if let c = arg.first {
                let id = UInt32(100 + (Array(WizardBindings.keyCodes.keys).firstIndex(of: c) ?? 0))
                WizardKey.shared.handle(id: id, pressed: true)
            }
            WizardKey.shared.handle(id: 1, pressed: false)
        case "close-window": controller.window?.performClose(nil)
        case "show-window": showMainWindow()
        case "command-q-repeat": guardedQuit(isRepeat: true)
        case "command-q":
            if let event = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [.command],
                                           timestamp: ProcessInfo.processInfo.systemUptime,
                                           windowNumber: controller.window?.windowNumber ?? 0, context: nil,
                                           characters: "q", charactersIgnoringModifiers: "q", isARepeat: false, keyCode: 12) {
                let handled = NSApp.mainMenu?.performKeyEquivalent(with: event) ?? false
                try? String(handled).write(toFile: "/tmp/wizard-mvp-qa-command-q.txt", atomically: true, encoding: .utf8)
            }
        case "command-w":
            // Exercise the actual AppKit menu equivalent, not a direct call to the handler.
            if let event = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [.command],
                                           timestamp: ProcessInfo.processInfo.systemUptime,
                                           windowNumber: controller.window?.windowNumber ?? 0, context: nil,
                                           characters: "w", charactersIgnoringModifiers: "w", isARepeat: false, keyCode: 13) {
                let handled = NSApp.mainMenu?.performKeyEquivalent(with: event) ?? false
                try? String(handled).write(toFile: "/tmp/wizard-mvp-qa-command-w.txt", atomically: true, encoding: .utf8)
            }
        case "ux-state":
            controller.uxState { ux in
                let s: [String: Any] = ["wizardUX": ux ?? NSNull(), "url": self.controller.web.url?.absoluteString ?? "",
                                        "home": self.controller.homeURL?.absoluteString ?? ""]
                if let d = try? JSONSerialization.data(withJSONObject: s, options: .prettyPrinted) { try? d.write(to: URL(fileURLWithPath: "/tmp/wizard-mvp-qa-ux.json")) }
            }
        case "ux-open": openView(arg)
        case "ux-dictation":
            controller.uxSend("wizard:dictation", ["text": arg]) { r in try? (r ?? "nil").write(toFile: "/tmp/wizard-mvp-qa-dictation.txt", atomically: true, encoding: .utf8) }
        case "meeting-new": recordNew(title: arg.isEmpty ? "QA meeting" : arg, eventId: nil)
        case "meeting-stop": MeetingRecorder.shared.stop(finalize: true) { s in
            if let d = try? JSONSerialization.data(withJSONObject: s, options: .prettyPrinted) { try? d.write(to: URL(fileURLWithPath: "/tmp/wizard-mvp-qa-meeting-stop.json")) } }
        case "meeting-note": MeetingRecorder.shared.addNote(arg)
        case "meeting-expand": RecorderPanel.shared.expand()
        case "meeting-prompt": CallDetector.shared.prompt(arg.isEmpty ? "Call in Zoom" : arg, eventId: nil)
        case "meeting-prompt-record": CallPrompt.shared.record()
        case "voice-tap": VoiceKeys.shared.tap(arg == "cmd" ? VoiceKeys.rightCommand : VoiceKeys.rightOption)
        case "voice-enable": VoiceKeys.enabled = arg != "off"; VoiceKeys.shared.install(prompt: false)
        case "panel-snapshot":
            // panel-snapshot <recorder|prompt|hud> <png>
            let a = arg.split(separator: " ", maxSplits: 1).map(String.init)
            let p: NSPanel = a.first == "quit" ? quitHint : a.first == "prompt" ? CallPrompt.shared.panel : a.first == "hud" ? VoiceHUD.shared.panel : RecorderPanel.shared.panel
            if let v = p.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) {
                v.cacheDisplay(in: v.bounds, to: rep)
                try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: a.count > 1 ? a[1] : "/tmp/wizard-mvp-qa-panel.png"))
            }
        case "meeting-state":
            var s: [String: Any] = MeetingRecorder.shared.status()
            s["recorderVisible"] = RecorderPanel.shared.panel.isVisible
            s["detector"] = CallDetector.shared.state
            s["voice"] = VoiceKeys.shared.state
            s["hudVisible"] = VoiceHUD.shared.panel.isVisible
            s["spoolPending"] = MeetingSpool.shared.pendingTotal
            s["micAuth"] = AVCaptureDevice.authorizationStatus(for: .audio).rawValue
            s["url"] = controller.web.url?.absoluteString ?? ""
            if let d = try? JSONSerialization.data(withJSONObject: s, options: .prettyPrinted) {
                try? d.write(to: URL(fileURLWithPath: "/tmp/wizard-mvp-qa-meeting.json"))
            }
        case "keys-state":
            let s: [String: Any] = [
                "triggerRegistered": WizardKey.shared.registered, "capsRemapActive": CapsLockRemap.active,
                "bindings": WizardBindings.current.map { "\($0.key)=\($0.open ?? "")" },
                "searchVisible": WizardSearch.shared.panel.isVisible,
                "searchResults": WizardSearch.shared.results.prefix(8).map { $0.title },
                "statusMenu": statusMenu.titles(), "statusItemVisible": statusMenu.item.isVisible,
                "activationPolicy": NSApp.activationPolicy().rawValue, "windowVisible": controller.window?.isVisible ?? false,
                "windowKey": controller.window?.isKeyWindow ?? false, "overlayHidden": controller.overlay.isHidden,
                "quitHintVisible": quitHint.isVisible, "quitArmed": quitDeadline > ProcessInfo.processInfo.systemUptime,
                "url": controller.web.url?.absoluteString ?? ""]
            if let d = try? JSONSerialization.data(withJSONObject: s, options: .prettyPrinted) {
                try? d.write(to: URL(fileURLWithPath: "/tmp/wizard-mvp-qa-keys.json"))
            }
        case "state":
            let s: [String: Any] = ["overlayHidden": controller.overlay.isHidden, "title": controller.title.stringValue,
                                    "subtitle": controller.subtitle.stringValue, "url": controller.web.url?.absoluteString ?? "",
                                    "loadedAt": controller.loadedAt?.timeIntervalSince1970 ?? 0,
                                    "frame": NSStringFromRect(controller.window?.frame ?? .zero),
                                    "localVoice": controller.localVoiceQAState,
                                    "backends": Store.backends.map { $0.name }, "active": Store.activeIndex]
            if let d = try? JSONSerialization.data(withJSONObject: s, options: .prettyPrinted) {
                try? d.write(to: URL(fileURLWithPath: "/tmp/wizard-mvp-qa-state.json"))
            }
        default: break
        }
    }

    func snapshot(to path: String) {
        let write: (NSImage) -> Void = { img in
            guard let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                  let png = rep.representation(using: .png, properties: [:]) else { return }
            try? png.write(to: URL(fileURLWithPath: path))
        }
        if controller.overlay.isHidden {
            controller.web.takeSnapshot(with: nil) { img, _ in if let img { write(img) } }
        } else if let v = controller.window?.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) {
            v.cacheDisplay(in: v.bounds, to: rep)
            let img = NSImage(size: v.bounds.size); img.addRepresentation(rep); write(img)
        }
    }

    /// ⌘W closes a window managed inside Wizard UX; the host window stays open at its root.
    /// Other native windows keep their normal Close behavior. The red window button is unchanged.
    @objc func closeWizardApp(_ sender: Any?) {
        if let key = NSApp.keyWindow, key !== controller.window { key.performClose(sender); return }
        guard controller.overlay.isHidden, controller.window?.attachedSheet == nil else { return }
        controller.web.evaluateJavaScript("window.dispatchEvent(new KeyboardEvent('keydown', {key:'w', code:'KeyW', metaKey:true, bubbles:true, cancelable:true}))")
    }

    func installQuitGuard() {
        quitKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            let mods = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            let isQuit = event.charactersIgnoringModifiers?.lowercased() == "q" && mods.contains(.command)
                && !mods.contains(.option) && !mods.contains(.control) && !mods.contains(.shift)
            if isQuit && event.isARepeat { return nil } // Holding Q is never a second press.
            if !isQuit { self?.clearQuitConfirmation() }
            return event
        }
        NotificationCenter.default.addObserver(forName: NSApplication.didResignActiveNotification, object: nil, queue: .main) { [weak self] _ in
            self?.clearQuitConfirmation()
        }
    }

    func clearQuitConfirmation() {
        quitDeadline = 0; quitTimer?.invalidate(); quitTimer = nil; quitHint.orderOut(nil)
    }

    @objc func requestGuardedQuit(_ sender: Any?) {
        // AppKit also invokes menu actions with mouse/KitDefined events, which cannot read isARepeat.
        let repeatKey = NSApp.currentEvent.map { $0.type == .keyDown && $0.isARepeat } ?? false
        guardedQuit(isRepeat: repeatKey)
    }

    func guardedQuit(isRepeat: Bool) {
        guard !isRepeat else { return }
        let now = ProcessInfo.processInfo.systemUptime
        if quitDeadline > now { clearQuitConfirmation(); NSApp.terminate(nil); return }
        quitDeadline = now + 2
        quitTimer?.invalidate()
        let frame = controller.window?.frame ?? NSScreen.main?.visibleFrame ?? .zero
        quitHint.setFrameOrigin(NSPoint(x: frame.midX - 170, y: frame.midY - 29))
        quitHint.orderFrontRegardless()
        quitTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: false) { [weak self] _ in self?.clearQuitConfirmation() }
    }

    @objc func reload() { controller.begin() }
    @objc func switchBackend(_ sender: NSMenuItem) { Store.activeIndex = sender.tag; rebuildWizardMenu(); controller.begin() }
    @objc func installFromFile() {
        var list = Store.backends.filter { $0.kind != .thisMac }
        list.insert(Backend(kind: .thisMac, name: "This Mac", url: WizardShared.localSetupURL.absoluteString), at: 0)
        Store.backends = list; Store.activeIndex = 0; rebuildWizardMenu()
        controller.chooseOSFile()
    }
    @objc func addThisMac() { controller.chooseThisMac(); rebuildWizardMenu() }
    @objc func addRemote() { controller.chooseRemote(); rebuildWizardMenu() }
    @objc func restartLocal() { HostControl.send("restart"); DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.controller.begin() } }
    @objc func showFilesFolder() {
        if let f = WizardShared.filesFolder { NSWorkspace.shared.open(f) } else { controller.askFilesFolder() }
    }
}

let app = NSApplication.shared
let appDelegate = AppDelegate()
app.delegate = appDelegate
app.setActivationPolicy(.regular)
app.run()
