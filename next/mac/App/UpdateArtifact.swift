import Foundation
import CryptoKit
import Network
import Darwin

/// Verify raw archive SHA-256 and Ed25519 privately before Ready. Sparkle repeats
/// signature validation before extraction. Its public delegate does not expose
/// its download file, so serve the checked bytes over a private
/// token-bound loopback endpoint instead of fetching the large ZIP twice.
final class UpdateArtifact: NSObject, URLSessionDownloadDelegate {
    private let queue = DispatchQueue(label: "Wizard.update-artifact")
    private var session: URLSession?
    private var task: URLSessionDownloadTask?
    private var listener: NWListener?
    private var connections: [NWConnection] = []
    private var directory: URL?
    private var completed = false
    private var lockFD: Int32 = -1
    private var relayFile: URL?
    private var relayReady = false
    var onInvalidated: ((Error) -> Void)?
    private var completion: ((Result<URL, Error>) -> Void)?
    private var progress: ((UInt64, UInt64) -> Void)?
    private var expectedHash = ""
    private var expectedBytes: UInt64 = 0
    private var route = ""
    var signature: String?
    var publicKey: String?
    #if WIZARD_UPDATE_QA
    var skipPrivateSignature = false
    #endif
    static func verifySignature(_ file: URL, signature: String, publicKey: String) throws {
        guard let sig = Data(base64Encoded: signature), let key = Data(base64Encoded: publicKey),
              let verifier = try? Curve25519.Signing.PublicKey(rawRepresentation: key),
              verifier.isValidSignature(sig, for: try Data(contentsOf: file, options: .mappedIfSafe)) else {
            throw WizardUpdate.error("Archive Ed25519 signature is invalid — installed app unchanged")
        }
    }

    static func allowed(_ url: URL) -> Bool {
        guard url.user == nil, url.password == nil, url.fragment == nil else { return false }
        if url.scheme == "https" { return true }
        #if WIZARD_UPDATE_QA
        return url.scheme == "http" && ["127.0.0.1", "::1", "localhost"].contains(url.host ?? "")
        #else
        return false
        #endif
    }
    static func sweepStaleDownloads() throws {
        guard FileManager.default.fileExists(atPath: WizardUpdate.dir.path) else { return }
        for url in try FileManager.default.contentsOfDirectory(at: WizardUpdate.dir, includingPropertiesForKeys: nil)
            where url.lastPathComponent.hasPrefix("download-") {
            let fd = open(url.appendingPathComponent("lock").path, O_CREAT | O_RDWR, 0o600)
            guard fd >= 0 else { continue }
            if flock(fd, LOCK_EX | LOCK_NB) == 0 {
                try? FileManager.default.removeItem(at: url)
                flock(fd, LOCK_UN)
            }
            close(fd)
        }
    }
    static func requireCapacity(_ available: UInt64?, bytes: UInt64) throws {
        guard bytes > 0, bytes <= UInt64.max / 3, let available, available >= bytes * 3 else {
            throw WizardUpdate.error("Insufficient or unknown free disk space — update needs at least 3× the archive size; installed app unchanged")
        }
    }
    static func availableCapacity(_ url: URL) throws -> UInt64? {
        let value = try url.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]).volumeAvailableCapacityForImportantUsage
        return value.flatMap { $0 >= 0 ? UInt64($0) : nil }
    }
    static func requireAdmissionCapacity(_ app: URL, archive: URL) throws {
        // Count the installed app for the rollback copy and the incoming ZIP
        // directory sizes for extraction/replacement, without extracting it.
        var size: UInt64 = 0
        if let entries = FileManager.default.enumerator(at: app, includingPropertiesForKeys: [.fileSizeKey, .isRegularFileKey]) {
            for case let file as URL in entries {
                let values = try file.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
                if values.isRegularFile == true { size += UInt64(values.fileSize ?? 0) }
            }
        }
        // Read ZIP metadata only; never extract before explicit restart admission.
        let process = Process(), pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/zipinfo")
        process.arguments = ["-t", archive.path]; process.standardOutput = pipe
        try process.run()
        let output = pipe.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit()
        let text = String(data: output, encoding: .utf8) ?? ""
        let regex = try NSRegularExpression(pattern: "([0-9]+) bytes uncompressed")
        guard process.terminationStatus == 0,
              let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
              let range = Range(match.range(at: 1), in: text), let expanded = UInt64(text[range]),
              expanded > 0, expanded <= (UInt64.max - size) / 2,
              let available = try availableCapacity(WizardUpdate.dir), available >= size + expanded * 2 else {
            throw WizardUpdate.error("Insufficient or unknown free disk space for rollback copy and expanded update")
        }
    }
    func requireAdmissionCapacity(_ app: URL) throws {
        try queue.sync {
            guard relayReady, let relayFile else { throw WizardUpdate.error("Verified update relay is unavailable") }
            try Self.requireAdmissionCapacity(app, archive: relayFile)
        }
    }
    func requireLive() throws {
        try queue.sync {
            guard relayReady, let relayFile, FileManager.default.fileExists(atPath: relayFile.path) else {
                throw WizardUpdate.error("Verified update relay is no longer available — check for updates again")
            }
        }
    }
    static func verify(_ file: URL, hash: String, bytes: UInt64) throws {
        guard hash.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil, bytes > 0 else {
            throw WizardUpdate.error("Missing or invalid archive SHA-256/size")
        }
        let input = try FileHandle(forReadingFrom: file); defer { try? input.close() }
        var digest = SHA256(), count: UInt64 = 0
        while let data = try input.read(upToCount: 1024 * 1024), !data.isEmpty {
            digest.update(data: data); count += UInt64(data.count)
        }
        let actual = digest.finalize().map { String(format: "%02x", $0) }.joined()
        guard count == bytes, actual == hash else { throw WizardUpdate.error("Archive SHA-256 or size mismatch — installed app unchanged") }
    }
    func fetch(_ url: URL, hash: String, bytes: UInt64,
               progress: @escaping (UInt64, UInt64) -> Void,
               completion: @escaping (Result<URL, Error>) -> Void) throws {
        guard Self.allowed(url), hash.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil, bytes > 0 else {
            throw WizardUpdate.error("Update requires an HTTPS archive with SHA-256 and size")
        }
        try FileManager.default.createDirectory(at: WizardUpdate.dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        var capacity = try Self.availableCapacity(WizardUpdate.dir)
        #if WIZARD_UPDATE_QA
        if UserDefaults.standard.bool(forKey: "QAHooks"), UserDefaults.standard.bool(forKey: "QAUpdateNoSpace") { capacity = 0 }
        #endif
        try Self.requireCapacity(capacity, bytes: bytes)
        expectedHash = hash; expectedBytes = bytes; self.progress = progress; self.completion = completion
        let dir = WizardUpdate.dir.appendingPathComponent("download-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        directory = dir
        lockFD = open(dir.appendingPathComponent("lock").path, O_CREAT | O_RDWR, 0o600)
        guard lockFD >= 0, flock(lockFD, LOCK_EX | LOCK_NB) == 0 else { throw WizardUpdate.error("Cannot lock private update directory") }
        let config = URLSessionConfiguration.ephemeral
        // Bound inactivity, not total transfer time: slow progressing downloads
        // must not fail at one hour. The signed byte count bounds the body.
        config.timeoutIntervalForRequest = 60
        // No app-imposed absolute deadline; retain URLSession's platform
        // resource default and reset its 60-second request timer on progress.
        let session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        self.session = session
        var request = URLRequest(url: url); request.cachePolicy = .reloadIgnoringLocalCacheData
        task = session.downloadTask(with: request); task?.resume()
    }
    func cancel() { queue.async { self.cleanup() } }
    private func cleanup() {
        completed = true; relayReady = false; relayFile = nil; completion = nil; progress = nil
        task?.cancel(); task = nil; session?.invalidateAndCancel(); session = nil
        listener?.cancel(); listener = nil
        for connection in connections { connection.cancel() }; connections.removeAll()
        if let directory { try? FileManager.default.removeItem(at: directory) }; directory = nil
        if lockFD >= 0 { flock(lockFD, LOCK_UN); close(lockFD); lockFD = -1 }
    }
    private func finish(_ result: Result<URL, Error>) {
        guard !completed else { return }
        let callback = completion; completion = nil
        if case .failure(let error) = result {
            let invalidated = relayReady ? onInvalidated : nil
            cleanup()
            DispatchQueue.main.async { invalidated?(error) }
        }
        DispatchQueue.main.async { callback?(result) }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        // Never permit a TLS downgrade (including in QA's loopback lane).
        let allowed = request.url.map(Self.allowed) == true && request.url?.scheme == "https"
        if !allowed { queue.async { self.finish(.failure(WizardUpdate.error("Insecure update archive redirect refused"))) } }
        completionHandler(allowed ? request : nil)
    }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        let received = UInt64(max(0, totalBytesWritten))
        queue.async {
            guard !self.completed else { return }
            if received > self.expectedBytes { self.finish(.failure(WizardUpdate.error("Archive exceeds signed size"))); return }
            let callback = self.progress, expected = self.expectedBytes
            DispatchQueue.main.async { callback?(received, expected) }
        }
    }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        // URLSession removes location when this callback returns. Keep it privately
        // before scheduling verification; no app/VM replacement occurs here.
        queue.sync {
            guard !completed, let directory else { return }
            do {
                guard (downloadTask.response as? HTTPURLResponse)?.statusCode == 200 else { throw WizardUpdate.error("Update archive is unavailable") }
                let file = directory.appendingPathComponent("Wizard.zip")
                try FileManager.default.moveItem(at: location, to: file)
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
                try Self.verify(file, hash: expectedHash, bytes: expectedBytes)
                #if WIZARD_UPDATE_QA
                let verifyPrivate = !skipPrivateSignature
                #else
                let verifyPrivate = true
                #endif
                if verifyPrivate, let signature, let publicKey {
                    try Self.verifySignature(file, signature: signature, publicKey: publicKey)
                }
                relayFile = file
                try serve(file)
            } catch { finish(.failure(error)) }
        }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error { queue.async { self.finish(.failure(error)) } }
    }
    private func serve(_ file: URL) throws {
        let params = NWParameters.tcp
        params.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        let listener = try NWListener(using: params); self.listener = listener
        route = "/" + UUID().uuidString + "/Wizard.zip"
        listener.stateUpdateHandler = { [weak self] state in
            guard let self, !self.completed else { return }
            switch state {
            case .ready:
                guard let port = self.listener?.port else { return }
                self.relayReady = true
                self.finish(.success(URL(string: "http://127.0.0.1:\(port.rawValue)\(self.route)")!))
            case .failed(let error): self.finish(.failure(error))
            default: break
            }
        }
        listener.newConnectionHandler = { [weak self] connection in
            guard let self, !self.completed, self.connections.count < 4 else { connection.cancel(); return }
            self.connections.append(connection)
            connection.stateUpdateHandler = { [weak self, weak connection] state in
                guard let self, let connection else { return }
                switch state {
                case .cancelled, .failed: self.connections.removeAll { $0 === connection }
                default: break
                }
            }
            connection.start(queue: self.queue)
            let deadline = DispatchWorkItem { connection.cancel() }
            self.queue.asyncAfter(deadline: .now() + 10, execute: deadline)
            self.receive(connection, file: file, header: Data(), deadline: deadline)
        }
        listener.start(queue: queue)
    }
    private func receive(_ connection: NWConnection, file: URL, header: Data, deadline: DispatchWorkItem) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 8192) { [weak self] data, _, closed, error in
            guard let self, !self.completed, error == nil else { connection.cancel(); return }
            var buffer = header; buffer.append(data ?? Data())
            guard buffer.count <= 8192 else { connection.cancel(); return }
            if let text = String(data: buffer, encoding: .utf8), text.contains("\r\n\r\n") {
                deadline.cancel()
                guard text.hasPrefix("GET \(self.route) HTTP/1.1\r\n"),
                      let input = try? FileHandle(forReadingFrom: file) else { connection.cancel(); return }
                let response = "HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: \(self.expectedBytes)\r\nConnection: close\r\n\r\n"
                connection.send(content: Data(response.utf8), completion: .contentProcessed { error in
                    if error != nil { try? input.close(); connection.cancel() }
                    else { self.send(connection, input: input) }
                })
            } else if closed { connection.cancel() }
            else { self.receive(connection, file: file, header: buffer, deadline: deadline) }
        }
    }
    private func send(_ connection: NWConnection, input: FileHandle) {
        guard !completed, let data = try? input.read(upToCount: 1024 * 1024), !data.isEmpty else {
            try? input.close(); connection.cancel(); return
        }
        connection.send(content: data, completion: .contentProcessed { [weak self] error in
            guard let self, error == nil else { try? input.close(); connection.cancel(); return }
            self.send(connection, input: input)
        })
    }
}
