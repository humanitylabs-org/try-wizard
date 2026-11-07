import Foundation

/// Main-queue batch shared by the native controller and focused XCTest cases.
/// Only the first completion schedules a reveal; later completions join that
/// fixed window without moving its deadline. Draining starts a fresh batch.
struct DownloadRevealBatch {
    private var pending: [URL] = []

    mutating func append(_ target: URL) -> Bool {
        let shouldSchedule = pending.isEmpty
        pending.append(target)
        return shouldSchedule
    }

    mutating func drain() -> [URL] {
        defer { pending.removeAll() }
        return pending
    }
}

/// Used on WebKit's delegate queue. Admission reserves a name before WebKit writes bytes.
struct DownloadDestinations {
    private var targets: [ObjectIdentifier: URL] = [:]

    // Conservative identity for ordinary case-insensitive APFS. Keep the chosen
    // spelling in targets; only comparisons use canonical Unicode + case folding.
    private func identity(_ url: URL) -> String {
        url.path.precomposedStringWithCanonicalMapping
            .folding(options: [.caseInsensitive], locale: Locale(identifier: "en_US_POSIX"))
            .precomposedStringWithCanonicalMapping
    }

    mutating func reserve(for download: ObjectIdentifier, suggestedFilename: String,
                          folder: URL, fileExists: (String) -> Bool) -> URL {
        if let target = targets[download] { return target }
        let clean = suggestedFilename.replacingOccurrences(of: "/", with: "-")
            .replacingOccurrences(of: "\0", with: "-")
        let name = clean.isEmpty || clean == "." || clean == ".." ? "Wizard download" : clean
        let base = (name as NSString).deletingPathExtension, ext = (name as NSString).pathExtension
        var target = folder.appendingPathComponent(name), n = 2
        while targets.values.contains(where: { identity($0) == identity(target) }) || fileExists(target.path) {
            target = folder.appendingPathComponent(ext.isEmpty ? "\(base) \(n)" : "\(base) \(n).\(ext)"); n += 1
        }
        targets[download] = target
        return target
    }

    @discardableResult
    mutating func release(_ download: ObjectIdentifier) -> URL? {
        targets.removeValue(forKey: download)
    }
}
