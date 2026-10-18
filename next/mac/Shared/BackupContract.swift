import Foundation

// Shared by the native transport and its unit tests. No secrets in URLs or descriptions.
enum WizardBackupContract {
    static let header = "X-Wizard-Backup"
    static let headerValue = "wizardbackup-v1"
    static let prefix = "api/backup/"

    static func request(base: URL, path: String, method: String = "GET", body: [String: Any]? = nil) throws -> URLRequest {
        guard base.scheme == "http", base.host == "127.0.0.1", base.user == nil, base.password == nil,
              base.query == nil, base.fragment == nil, !path.contains("?"), !path.contains(".."),
              !path.contains("://"), !path.hasPrefix("/") else { throw BackupFailure("Backup transport requires the local Wizard front door.") }
        var request = URLRequest(url: base.appendingPathComponent(prefix + path))
        request.httpMethod = method
        request.setValue(headerValue, forHTTPHeaderField: header)
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        request.timeoutInterval = 3600
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        return request
    }

    static func filename(name: String, date: Date = Date()) -> String {
        let safe = name.map { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" ? $0 : "-" }
        let slug = String(safe.prefix(60)).trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.dateFormat = "yyyyMMdd-HHmmss"
        return "\(slug.isEmpty ? "Wizard" : slug)-\(formatter.string(from: date)).wizardbackup"
    }

    static func summary(_ result: [String: Any]) -> String {
        let agents = result["agents"] as? [String] ?? []
        let apps = result["apps"] as? [String] ?? []
        let files = result["files"] as? [String: Any] ?? [:]
        let bytes = (files["bytes"] as? NSNumber)?.int64Value ?? 0
        let count = (files["count"] as? NSNumber)?.intValue ?? 0
        let size = ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
        let plan = result["plan"] as? [String: Any] ?? [:]
        var lines = ["Verified: \(agents.count) agents, \(apps.count) apps, \(count) files (\(size))."]
        if !agents.isEmpty { lines.append("Agents: " + agents.joined(separator: ", ")) }
        for (key, label) in [("install", "Restore apps (install if needed)"), ("replace", "Replace app data"), ("leave", "Leave unchanged")] {
            if let values = plan[key] as? [String], !values.isEmpty { lines.append(label + ": " + values.joined(separator: ", ")) }
        }
        if let warnings = result["warnings_count"] as? Int, warnings > 0 {
            lines.append("\(warnings) compatibility or omitted-file warnings. Review with wam backup verify before relying on this copy.")
        }
        lines.append("The current Wizard is set aside so you can undo. Messaging and scheduled jobs stay paused until you switch over.")
        return lines.joined(separator: "\n\n")
    }
}

struct BackupFailure: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}
