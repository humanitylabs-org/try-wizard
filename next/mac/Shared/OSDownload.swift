import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
#if canImport(CryptoKit)
import CryptoKit
#else
import Crypto
#endif

/// Downloads a WizardOS archive, or its ordered parts, into a folder on this Mac before anything is unpacked
/// (try-wizard#177). The installer used to write each received chunk straight into `tar -xJf -`: the end of the
/// archive expands into many GB of disk image, tar then takes a minute or more to accept a few MB, the download sat
/// still for longer than URLSession's 60 s request timeout, and a fresh install failed on a slow disk.
///
/// Here the network only ever writes to a file. Each part is checked against its own hash, a part that fails (lost
/// connection, timeout, HTTP error, wrong hash) is fetched again up to `attempts` times, parts already downloaded and
/// checked are kept for the next try, and the whole archive is checked against the feed's hash at the end.
final class WizardOSDownload: NSObject, URLSessionDataDelegate {
    struct Item: Equatable {
        let url: URL
        /// The part's own SHA-256; empty when the feed names one archive (then `wholeSHA256` is its hash).
        let sha256: String
        let bytes: Int64?
    }

    let items: [Item]
    let folder: URL
    let wholeSHA256: String
    let name: String
    var attempts = 3
    var retryDelay: TimeInterval = 2
    var requestTimeout: TimeInterval = 60
    /// Tests swap in a stub URLProtocol here.
    var configuration = URLSessionConfiguration.default
    /// Bytes on disk so far (kept parts included) and the expected total (0 when unknown).
    var onProgress: ((Int64, Int64) -> Void)?
    /// A part failed and is fetched again: (part number from 1, next attempt, reason).
    var onRetry: ((Int, Int, String) -> Void)?
    /// The archive's files in order, every hash checked; or the reason it couldn't be downloaded.
    var onDone: ((Result<[URL], Error>) -> Void)?

    private let queue: OperationQueue = { let q = OperationQueue(); q.maxConcurrentOperationCount = 1; return q }()
    private var session: URLSession?
    private var index = 0
    private var attempt = 1
    private var handle: FileHandle?
    private var hasher = SHA256()
    private var keptBytes: Int64 = 0      // parts finished before the current one
    private var partReceived: Int64 = 0
    private var total: Int64 = 0
    private var failure: String?
    private var finished = false

    init(items: [Item], folder: URL, wholeSHA256: String, name: String = "WizardOS") {
        self.items = items
        self.folder = folder
        self.wholeSHA256 = wholeSHA256.lowercased()
        self.name = name
    }

    /// Where an item lands. Feed URLs end in the archive or part name (…/wizard-os-0.4.0.tar.xz.part03).
    func file(_ i: Int) -> URL {
        let last = items[i].url.lastPathComponent
        let safe = last.isEmpty || last == "/" || last.hasPrefix(".") ? "part\(i)" : last
        return folder.appendingPathComponent(String(format: "%02d-", i) + safe)
    }
    private func partial(_ i: Int) -> URL { file(i).appendingPathExtension("partial") }
    private var label: String { items.count > 1 ? "part \(index + 1) of \(items.count)" : "the archive" }

    static func error(_ s: String) -> NSError { NSError(domain: "Wizard", code: 1, userInfo: [NSLocalizedDescriptionKey: s]) }

    static func sha256(of url: URL) throws -> String {
        let h = try FileHandle(forReadingFrom: url); defer { try? h.close() }
        var hasher = SHA256()
        while let chunk = try h.read(upToCount: 8 << 20), !chunk.isEmpty { hasher.update(data: chunk) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    func start() {
        let config = configuration
        config.timeoutIntervalForRequest = requestTimeout
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        session = URLSession(configuration: config, delegate: self, delegateQueue: queue)
        queue.addOperation { [self] in
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                // Anything in the folder that isn't one of this download's files is left over from another try.
                let mine = Set(items.indices.map { file($0).lastPathComponent })
                for f in (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
                where !mine.contains(f.lastPathComponent) { try? FileManager.default.removeItem(at: f) }
            } catch { return done(.failure(Self.error("Couldn't save the \(name) download on this Mac: \(error.localizedDescription)"))) }
            total = items.contains { $0.bytes == nil } ? 0 : items.reduce(0) { $0 + ($1.bytes ?? 0) }
            next()
        }
    }

    /// Runs on the delegate queue: skip parts already downloaded and checked, fetch the first one that isn't.
    private func next() {
        while index < items.count {
            let want = items[index].sha256.isEmpty ? (items.count == 1 ? wholeSHA256 : "") : items[index].sha256.lowercased()
            let f = file(index)
            if FileManager.default.fileExists(atPath: f.path) {
                if !want.isEmpty, (try? Self.sha256(of: f)) == want {
                    keptBytes += Int64((try? f.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
                    onProgress?(keptBytes, total); index += 1; attempt = 1; continue
                }
                try? FileManager.default.removeItem(at: f)
            }
            fetch(); return
        }
        checkWhole()
    }

    private func fetch() {
        let p = partial(index)
        try? FileManager.default.removeItem(at: p)
        guard FileManager.default.createFile(atPath: p.path, contents: nil),
              let h = try? FileHandle(forWritingTo: p) else {
            return done(.failure(Self.error("Couldn't save the \(name) download on this Mac.")))
        }
        handle = h; hasher = SHA256(); partReceived = 0; failure = nil
        session?.dataTask(with: items[index].url).resume()
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard code == 200 else { failure = "the server answered HTTP \(code)"; completionHandler(.cancel); return }
        if total == 0, items.count == 1, response.expectedContentLength > 0 { total = response.expectedContentLength }
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        do { try handle?.write(contentsOf: data) } catch {
            failure = "couldn't save it on this Mac (\(error.localizedDescription))"; dataTask.cancel(); return
        }
        hasher.update(data: data)
        partReceived += Int64(data.count)
        onProgress?(keptBytes + partReceived, total)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        try? handle?.close(); handle = nil
        var problem = failure ?? error?.localizedDescription
        let want = items[index].sha256.isEmpty ? (items.count == 1 ? wholeSHA256 : "") : items[index].sha256.lowercased()
        if problem == nil, !want.isEmpty, hasher.finalize().map({ String(format: "%02x", $0) }).joined() != want {
            problem = "it arrived damaged"
        }
        if let problem {
            try? FileManager.default.removeItem(at: partial(index))
            // Saving on this Mac failed: fetching again won't help.
            guard attempt < attempts, failure?.hasPrefix("couldn't save") != true else {
                return done(.failure(Self.error("Couldn't download \(name) (\(label)): \(problem). Check your connection and try again.")))
            }
            attempt += 1
            onRetry?(index + 1, attempt, problem)
            DispatchQueue.global().asyncAfter(deadline: .now() + retryDelay) { [self] in queue.addOperation { fetch() } }
            return
        }
        do {
            try? FileManager.default.removeItem(at: file(index))
            try FileManager.default.moveItem(at: partial(index), to: file(index))
        } catch { return done(.failure(Self.error("Couldn't save the \(name) download on this Mac: \(error.localizedDescription)"))) }
        keptBytes += partReceived; partReceived = 0
        index += 1; attempt = 1
        next()
    }

    /// Every part matched its own hash; the archive as a whole must match the feed too.
    private func checkWhole() {
        let files = items.indices.map(file)
        if items.count > 1 || items.first?.sha256.isEmpty == false {
            var whole = SHA256()
            do {
                for f in files {
                    let h = try FileHandle(forReadingFrom: f); defer { try? h.close() }
                    while let chunk = try h.read(upToCount: 8 << 20), !chunk.isEmpty { whole.update(data: chunk) }
                }
            } catch { return done(.failure(Self.error("Couldn't read the \(name) download: \(error.localizedDescription)"))) }
            guard whole.finalize().map({ String(format: "%02x", $0) }).joined() == wholeSHA256 else {
                try? FileManager.default.removeItem(at: folder)
                return done(.failure(Self.error("The \(name) download was corrupted. Try again.")))
            }
        }
        done(.success(files))
    }

    private func done(_ result: Result<[URL], Error>) {
        guard !finished else { return }
        finished = true
        session?.finishTasksAndInvalidate(); session = nil
        onDone?(result)
    }
}
