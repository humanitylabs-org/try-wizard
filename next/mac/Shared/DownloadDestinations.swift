import Foundation

/// Used on WebKit's delegate queue. Admission reserves a name before WebKit writes bytes.
struct DownloadDestinations {
    private var targets: [ObjectIdentifier: URL] = [:]

    mutating func reserve(for download: ObjectIdentifier, suggestedFilename: String,
                          folder: URL, fileExists: (String) -> Bool) -> URL {
        if let target = targets[download] { return target }
        let clean = suggestedFilename.replacingOccurrences(of: "/", with: "-")
            .replacingOccurrences(of: "\0", with: "-")
        let name = clean.isEmpty || clean == "." || clean == ".." ? "Wizard download" : clean
        let base = (name as NSString).deletingPathExtension, ext = (name as NSString).pathExtension
        var target = folder.appendingPathComponent(name), n = 2
        while targets.values.contains(target) || fileExists(target.path) {
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
