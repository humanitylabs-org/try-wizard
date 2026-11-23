import Foundation

/// Whether a standard-install guest (the os.sh install with Host-run updates, try-wizard#98) is quiet enough for the
/// Host to stop it for a Wizard.app update or a guest patch (try-wizard#154).
///
/// A standard guest's Agent Service has no Mac-line `/wizard/v1/maintenance` lease route (it answers 404), so the
/// Host asks the guest what is running instead, the way a Host-run WizardOS update does:
///   - `work`: the guest's `wizard-ctl work` (`wam work`: chat replies, agent turns, scheduled runs, kanban cards,
///     background tasks, App Manager jobs). Stopping the VM stops all of it. An older guest answers `unknown`; that
///     reader is then skipped, never read as idle.
///   - `status`: `wizard-ctl update-status` (`wam updates`). Its `waiting_for` lists what a pending WizardOS update
///     would stop. It must answer: a guest that can't say counts as busy.
///   - `health`: the Agent Service `/wizard/health` queue (the chat replies running or waiting), as `WizardUpdate.idle`.
/// nil means quiet. Anything unreadable or running gives the reason the owner sees, naming the work.
enum WizardStandardAdmission {
    static let unknownText = "Wizard couldn't check what is running on this Mac — it updates when it can"

    static func reason(work: Data?, status: Data?, health: Data?) -> String? {
        var names: [String] = []
        func add(_ name: String) {
            let n = name.trimmingCharacters(in: .whitespacesAndNewlines)
            if !n.isEmpty && !names.contains(where: { $0.caseInsensitiveCompare(n) == .orderedSame }) { names.append(n) }
        }
        // The guest's own list of running work (newer guests only).
        if let work, let any = try? JSONSerialization.jsonObject(with: work) {
            if let items = any as? [[String: Any]] {
                for item in items {
                    if item["kind"] as? String == "unknown" { return unknownText }   // a reader that failed is never idle
                    add(item["name"] as? String ?? "something")
                }
            } else if let o = any as? [String: Any], o["error"] != nil {
                return unknownText
            }
        }
        // The App Manager must answer; what a pending WizardOS update would stop counts too.
        guard let status, let st = (try? JSONSerialization.jsonObject(with: status)) as? [String: Any], st["error"] == nil else {
            return unknownText
        }
        for item in (st["waiting_for"] as? [[String: Any]]) ?? [] {
            if item["kind"] as? String == "unknown" { return unknownText }
            add(item["name"] as? String ?? "something")
        }
        // The Agent Service queue: chat replies running or waiting.
        guard let health, let h = (try? JSONSerialization.jsonObject(with: health)) as? [String: Any],
              let q = h["queue"] as? [String: Any], q["liveness_available"] as? Bool == true,
              let active = q["active"] as? Int, let queued = q["queued"] as? Int else {
            return unknownText
        }
        if active + queued > 0 { add("A chat reply") }
        return names.isEmpty ? nil : busyText(names)
    }

    /// "Wizard is working on a chat reply — updates when it finishes". Names come from WAM `work` (wam/work.py).
    static func busyText(_ names: [String]) -> String {
        var shown: [String] = []
        for n in names {
            let phrase = spoken(n)
            if !shown.contains(phrase) { shown.append(phrase) }
        }
        let list: String
        if shown.count > 3 { list = shown.prefix(3).joined(separator: ", ") + " and \(shown.count - 3) more" }
        else if shown.count > 1 { list = shown.dropLast().joined(separator: ", ") + " and " + shown[shown.count - 1] }
        else { list = shown.joined() }
        return "Wizard is working on \(list) — updates when it finishes"
    }

    /// WAM's item names read as a sentence: "A chat reply" -> "a chat reply", "Hermes is working" -> "an agent task".
    static func spoken(_ name: String) -> String {
        if name == "Hermes is working" { return "an agent task" }
        if name == "Replying in a chat" { return "a chat reply" }
        if name.hasPrefix("Replying in ") { return "a reply in " + name.dropFirst("Replying in ".count) }
        for lead in ["A ", "Scheduled job ", "Task "] where name.hasPrefix(lead) {
            return lead.lowercased() + name.dropFirst(lead.count)
        }
        return name
    }
}
