import XCTest
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
#if canImport(CryptoKit)
import CryptoKit
#else
import Crypto
#endif
@testable import WizardOSDownload

/// try-wizard#177: a fresh Mac install downloads the WizardOS archive to files first (each part hash-checked and
/// retried), and only then unpacks it, so a slow unpack can no longer time out the download.
final class PartsProtocol: URLProtocol {
    /// Per request: (status, body) or an error to fail the request with.
    static var answer: (URLRequest) -> Result<(Int, Data), Error> = { _ in .success((404, Data())) }
    static var seen: [String] = []
    static let lock = NSLock()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); Self.seen.append(request.url?.lastPathComponent ?? ""); Self.lock.unlock()
        switch Self.answer(request) {
        case .failure(let error):
            client?.urlProtocol(self, didFailWithError: error)
        case .success(let (status, body)):
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1",
                                           headerFields: ["Content-Length": "\(body.count)"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: body)
            client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {}
}

func hex(_ d: Data) -> String { SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined() }

final class OSDownloadTests: XCTestCase {
    let parts: [Data] = [Data(repeating: 1, count: 70_000), Data(repeating: 2, count: 50_000), Data("tail".utf8)]
    var folder: URL!

    override func setUp() {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent("os-download-\(UUID().uuidString)/0.4.0")
        PartsProtocol.seen = []
        PartsProtocol.answer = { [parts] req in
            let name = req.url!.lastPathComponent
            guard let i = Int(name.suffix(2)), parts.indices.contains(i) else { return .success((404, Data())) }
            return .success((200, parts[i]))
        }
    }
    override func tearDown() { try? FileManager.default.removeItem(at: folder.deletingLastPathComponent()) }

    func items(_ hashes: [String]? = nil) -> [WizardOSDownload.Item] {
        parts.indices.map { i in
            WizardOSDownload.Item(url: URL(string: "https://downloads.example/os/0.4.0/wizard-os-0.4.0.tar.xz.part0\(i)")!,
                                  sha256: hashes?[i] ?? hex(parts[i]), bytes: Int64(parts[i].count))
        }
    }

    func run(_ items: [WizardOSDownload.Item], whole: String? = nil,
             retries: UnsafeMutablePointer<[String]>? = nil) -> Result<[URL], Error> {
        let dl = WizardOSDownload(items: items, folder: folder, wholeSHA256: whole ?? hex(parts.reduce(Data(), +)))
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [PartsProtocol.self]
        dl.configuration = config
        dl.retryDelay = 0.01
        var result: Result<[URL], Error>?
        var retried: [String] = []
        let done = expectation(description: "download finished")
        dl.onRetry = { part, attempt, why in retried.append("\(part):\(attempt):\(why)") }
        dl.onDone = { result = $0; done.fulfill() }
        dl.start()
        wait(for: [done], timeout: 20)
        retries?.pointee = retried
        return result!
    }

    func testDownloadsEveryPartToFilesInOrderAndChecksTheWhole() throws {
        let files = try run(items()).get()
        XCTAssertEqual(files.count, 3)
        XCTAssertEqual(files.map { try! Data(contentsOf: $0) }, parts)
        XCTAssertEqual(files.map(\.lastPathComponent), files.map(\.lastPathComponent).sorted(), "unpack order is file order")
        XCTAssertEqual(PartsProtocol.seen.count, 3)
        let left = try FileManager.default.contentsOfDirectory(atPath: folder.path).filter { $0.hasSuffix(".partial") }
        XCTAssertEqual(left, [])
    }

    func testAnInterruptedPartIsFetchedAgain() throws {
        var failures = 1
        PartsProtocol.answer = { [parts] req in
            let i = Int(req.url!.lastPathComponent.suffix(2))!
            if i == 1, failures > 0 { failures -= 1; return .failure(URLError(.timedOut)) }
            return .success((200, parts[i]))
        }
        var retried: [String] = []
        let files = try run(items(), retries: &retried).get()
        XCTAssertEqual(files.map { try! Data(contentsOf: $0) }, parts)
        XCTAssertEqual(retried.count, 1)
        XCTAssertTrue(retried[0].hasPrefix("2:2:"), retried[0])
    }

    func testADamagedPartIsFetchedAgainThenGivesUpWithTheReason() {
        PartsProtocol.answer = { [parts] req in
            let i = Int(req.url!.lastPathComponent.suffix(2))!
            return .success((200, i == 1 ? Data("garbage".utf8) : parts[i]))
        }
        var retried: [String] = []
        guard case .failure(let error) = run(items(), retries: &retried) else { return XCTFail("damaged part accepted") }
        XCTAssertEqual(retried.count, 2)
        XCTAssertEqual(PartsProtocol.seen.filter { $0.hasSuffix("part01") }.count, 3)
        XCTAssertTrue(error.localizedDescription.contains("part 2 of 3"), error.localizedDescription)
        XCTAssertTrue(error.localizedDescription.contains("damaged"), error.localizedDescription)
    }

    func testAnHTTPErrorSaysSo() {
        PartsProtocol.answer = { _ in .success((403, Data())) }
        guard case .failure(let error) = run(items()) else { return XCTFail("403 accepted") }
        XCTAssertTrue(error.localizedDescription.contains("HTTP 403"), error.localizedDescription)
    }

    func testPartsAlreadyDownloadedAreKeptForTheNextTry() throws {
        PartsProtocol.answer = { [parts] req in
            let i = Int(req.url!.lastPathComponent.suffix(2))!
            return i == 2 ? .failure(URLError(.networkConnectionLost)) : .success((200, parts[i]))
        }
        guard case .failure = run(items()) else { return XCTFail("lost part accepted") }
        PartsProtocol.seen = []
        PartsProtocol.answer = { [parts] req in .success((200, parts[Int(req.url!.lastPathComponent.suffix(2))!])) }
        let files = try run(items()).get()
        XCTAssertEqual(PartsProtocol.seen, ["wizard-os-0.4.0.tar.xz.part02"], "parts 1 and 2 were not fetched again")
        XCTAssertEqual(files.map { try! Data(contentsOf: $0) }, parts)
    }

    func testAWholeArchiveThatDoesNotMatchTheFeedIsRejectedAndRemoved() {
        guard case .failure(let error) = run(items(), whole: String(repeating: "0", count: 64)) else {
            return XCTFail("wrong whole hash accepted")
        }
        XCTAssertTrue(error.localizedDescription.contains("corrupted"), error.localizedDescription)
        XCTAssertFalse(FileManager.default.fileExists(atPath: folder.path))
    }

    func testOneArchiveIsCheckedAgainstTheFeedHash() throws {
        let one = [WizardOSDownload.Item(url: URL(string: "https://downloads.example/os/wizard-os-0.4.0.tar.xz.part00")!,
                                         sha256: "", bytes: nil)]
        let files = try run(one, whole: hex(parts[0])).get()
        XCTAssertEqual(try Data(contentsOf: files[0]), parts[0])
        guard case .failure = run(one, whole: hex(parts[1])) else { return XCTFail("wrong archive accepted") }
    }
}
