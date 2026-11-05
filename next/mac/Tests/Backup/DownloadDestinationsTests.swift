import XCTest
@testable import WizardBackupContract

final class DownloadDestinationsTests: XCTestCase {
    // Allocator tests only: these do not exercise WKDownload gesture/frame metadata.
    func testCaseAndCanonicalUnicodeReserveDistinctDestinations() {
        let folder = URL(fileURLWithPath: "/Downloads", isDirectory: true)
        let downloads = (0..<4).map { _ in NSObject() }
        var destinations = DownloadDestinations()
        let names = ["Report.pdf", "report.pdf", "\u{00e9}.pdf", "e\u{0301}.pdf"]
        let actual = names.enumerated().map { index, name in
            destinations.reserve(for: ObjectIdentifier(downloads[index]), suggestedFilename: name,
                                 folder: folder, fileExists: { _ in false }).lastPathComponent
        }
        XCTAssertEqual(actual, ["Report.pdf", "report 2.pdf", "\u{00e9}.pdf", "e\u{0301} 2.pdf"])
        XCTAssertEqual(Array(actual[3].unicodeScalars), Array("e\u{0301} 2.pdf".unicodeScalars),
                       "Chosen filename spelling is preserved, not normalized for storage")
    }

    func testRapidDuplicatesReserveBeforeBytesExistAndRelease() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let downloads = (0..<4).map { _ in NSObject() }
        var destinations = DownloadDestinations()
        func reserve(_ index: Int) -> URL {
            destinations.reserve(for: ObjectIdentifier(downloads[index]), suggestedFilename: "report.pdf",
                                 folder: folder, fileExists: { FileManager.default.fileExists(atPath: $0) })
        }
        let first = reserve(0), second = reserve(1), third = reserve(2)
        XCTAssertEqual([first, second, third].map(\.lastPathComponent), ["report.pdf", "report 2.pdf", "report 3.pdf"])
        XCTAssertFalse(FileManager.default.fileExists(atPath: first.path))
        XCTAssertEqual(reserve(0), first, "Repeated admission keeps its existing reservation")
        // Failure: release without a file. The freed slot can be admitted immediately.
        XCTAssertEqual(destinations.release(ObjectIdentifier(downloads[1])), second)
        XCTAssertEqual(reserve(3), second)
        destinations.release(ObjectIdentifier(downloads[3]))
        // Finish: release after bytes exist; sequential duplicates must still skip the file.
        try Data("done".utf8).write(to: first)
        XCTAssertEqual(destinations.release(ObjectIdentifier(downloads[0])), first)
        XCTAssertEqual(reserve(1), second)
        destinations.release(ObjectIdentifier(downloads[0])) // Unknown/duplicate completion is harmless.
    }

    func testExistingFilesSuffixesAndExtensionlessNames() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let downloads = (0..<6).map { _ in NSObject() }
        var destinations = DownloadDestinations()
        for name in ["archive.tar.gz", "archive.tar 2.gz", "notes", "notes 2"] {
            try Data().write(to: folder.appendingPathComponent(name))
        }
        let names = ["archive.tar.gz", "archive.tar.gz", "notes", "notes", "report 2.pdf", "report 2.pdf"]
        let actual = names.enumerated().map { index, name in
            destinations.reserve(for: ObjectIdentifier(downloads[index]), suggestedFilename: name,
                                 folder: folder, fileExists: { FileManager.default.fileExists(atPath: $0) }).lastPathComponent
        }
        XCTAssertEqual(actual, ["archive.tar 3.gz", "archive.tar 4.gz", "notes 3", "notes 4", "report 2.pdf", "report 2 2.pdf"])
    }

    func testFilenameStaysOneConfinedComponent() {
        let folder = URL(fileURLWithPath: "/Downloads", isDirectory: true)
        let downloads = (0..<8).map { _ in NSObject() }
        var destinations = DownloadDestinations()
        for (index, name) in ["", ".", "..", "../outside.txt", "/absolute.txt", "a/b.txt", "a\0b", "☃.txt"].enumerated() {
            let target = destinations.reserve(for: ObjectIdentifier(downloads[index]), suggestedFilename: name,
                                              folder: folder, fileExists: { _ in false })
            XCTAssertEqual(target.standardizedFileURL.deletingLastPathComponent(), folder)
            XCTAssertFalse(target.lastPathComponent.contains("\0"))
        }
    }
}
