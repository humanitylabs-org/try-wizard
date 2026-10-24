import Foundation
import CryptoKit
import Network

/// Verify the whole archive named by the signed feed before Sparkle sees it.
/// Sparkle's public delegate does not expose its download file. Hand it our verified
/// bytes through a token-bound loopback URL instead of fetching a large ZIP twice.
final class UpdateArtifact: NSObject, URLSessionDownloadDelegate {
    private let queue = DispatchQueue(label: "Wizard.update-artifact")
    private var session: URLSession?
    private var task: URLSessionDownloadTask?
    private var listener: NWListener?
    private var connections: [NWConnection] = []
    private var directory: URL?
    private var completed = false
    private var completion: ((Result<URL, Error>) -> Void)?
    private var progress: ((UInt64, UInt64) -> Void)?
    private var expectedHash = ""
    private var expectedBytes: UInt64 = 0
    private var route = ""

    static func allowed(_ url: URL) -> Bool {
        guard url.user == nil, url.password == nil, url.fragment == nil else { return false }
        return url.scheme == "https" || (url.scheme == "http" && ["127.0.0.1", "::1", "localhost"].contains(url.host ?? ""))
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
        expectedHash = hash; expectedBytes = bytes; self.progress = progress; self.completion = completion
        let dir = WizardUpdate.dir.appendingPathComponent("download-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        directory = dir
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 60; config.timeoutIntervalForResource = 3600
        let session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        self.session = session
        var request = URLRequest(url: url); request.cachePolicy = .reloadIgnoringLocalCacheData
        task = session.downloadTask(with: request); task?.resume()
    }
    func cancel() { queue.async { self.cleanup() } }
    private func cleanup() {
        completed = true; completion = nil; progress = nil
        task?.cancel(); task = nil; session?.invalidateAndCancel(); session = nil
        listener?.cancel(); listener = nil
        for connection in connections { connection.cancel() }; connections.removeAll()
        if let directory { try? FileManager.default.removeItem(at: directory) }; directory = nil
    }
    private func finish(_ result: Result<URL, Error>) {
        guard !completed else { return }
        let callback = completion; completion = nil
        if case .failure = result { cleanup() }
        DispatchQueue.main.async { callback?(result) }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(request.url.map(Self.allowed) == true ? request : nil)
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
                self.finish(.success(URL(string: "http://127.0.0.1:\(port.rawValue)\(self.route)")!))
            case .failed(let error): self.finish(.failure(error))
            default: break
            }
        }
        listener.newConnectionHandler = { [weak self] connection in
            guard let self, !self.completed, self.connections.count < 4 else { connection.cancel(); return }
            self.connections.append(connection); connection.start(queue: self.queue)
            self.receive(connection, file: file, header: Data())
        }
        listener.start(queue: queue)
    }
    private func receive(_ connection: NWConnection, file: URL, header: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 8192) { [weak self] data, _, closed, error in
            guard let self, !self.completed, error == nil else { connection.cancel(); return }
            var buffer = header; buffer.append(data ?? Data())
            guard buffer.count <= 8192 else { connection.cancel(); return }
            if let text = String(data: buffer, encoding: .utf8), text.contains("\r\n\r\n") {
                guard text.hasPrefix("GET \(self.route) HTTP/1.1\r\n"),
                      let input = try? FileHandle(forReadingFrom: file) else { connection.cancel(); return }
                let response = "HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: \(self.expectedBytes)\r\nConnection: close\r\n\r\n"
                connection.send(content: Data(response.utf8), completion: .contentProcessed { error in
                    if error != nil { try? input.close(); connection.cancel() }
                    else { self.send(connection, input: input) }
                })
            } else if closed { connection.cancel() }
            else { self.receive(connection, file: file, header: buffer) }
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
