import Foundation

/// How long a downloaded Wizard for Mac update may wait (try-wizard#128, switch `UpdateDeadlines`).
///
/// Before this, an update that was ready to install could wait forever: Later hid the bar with no deadline and a quit
/// cancelled the prepared install. With the switch on:
///   - Later hides the bar until tomorrow (`laterFor`); then it shows once more, and Later starts another day.
///   - After `offerOnQuitAfter` (3 days) ready, quitting Wizard asks "Install it while quitting?".
///   - A critical release (`<sparkle:criticalUpdate>`) has no Later at all.
/// The ready record lives in updates/ready.json, so the 3 days survive relaunches; a newer ready build starts over.
enum WizardReadyUpdate {
    /// The one place the 3 days are set.
    static let offerOnQuitAfter: TimeInterval = 3 * 24 * 3600
    /// Later means until tomorrow.
    static let laterFor: TimeInterval = 24 * 3600
    /// Phases of the window's notice bar in which a critical update shows no Later.
    static let urgentPhases: Set<String> = ["available", "downloading", "verifying", "ready", "busy", "stopping"]

    struct Record: Equatable {
        var build: String
        var readySince: Double
        var laterUntil: Double?
        var critical: Bool

        var json: [String: Any] {
            var j: [String: Any] = ["build": build, "readySince": readySince, "critical": critical]
            if let laterUntil { j["laterUntil"] = laterUntil }
            return j
        }
        static func read(_ j: [String: Any]) -> Record? {
            guard let build = j["build"] as? String, !build.isEmpty, let since = number(j["readySince"]) else { return nil }
            return Record(build: build, readySince: since, laterUntil: number(j["laterUntil"]), critical: j["critical"] as? Bool ?? false)
        }
        private static func number(_ value: Any?) -> Double? {
            if let d = value as? Double { return d }
            if let i = value as? Int { return Double(i) }
            if let n = value as? NSNumber { return n.doubleValue }
            return nil
        }
    }

    /// Update `build` is ready now. The same build keeps its stored record (and its ready-since time, also across
    /// relaunches); a different build replaces it and starts the clock again.
    static func ready(_ stored: Record?, build: String, critical: Bool, now: Date) -> Record {
        if var same = stored, same.build == build {
            same.critical = critical
            if critical { same.laterUntil = nil }
            return same
        }
        return Record(build: build, readySince: now.timeIntervalSince1970, laterUntil: nil, critical: critical)
    }

    /// The owner pressed Later. A critical update has no Later, so nothing changes for it.
    static func later(_ record: Record, now: Date) -> Record {
        guard !record.critical else { return record }
        var r = record
        r.laterUntil = now.timeIntervalSince1970 + laterFor
        return r
    }

    /// Whether the bar stays hidden for this ready update right now (a Later that hasn't run out).
    static func staysHidden(_ record: Record, now: Date) -> Bool {
        guard !record.critical, let until = record.laterUntil else { return false }
        return now.timeIntervalSince1970 < until
    }

    /// Whether the bar should come back now: a Later ran out and the bar is still hidden. Once shown, call `shown`,
    /// so it shows only once a day (not on every check).
    static func showAgain(_ record: Record, now: Date, barHidden: Bool) -> Bool {
        guard barHidden, let until = record.laterUntil else { return false }
        return now.timeIntervalSince1970 >= until
    }
    static func shown(_ record: Record) -> Record {
        var r = record
        r.laterUntil = nil
        return r
    }

    /// Whether quitting asks to install: the ready build has waited `offerOnQuitAfter` or longer.
    static func offerOnQuit(_ record: Record?, readyBuild: String, now: Date) -> Bool {
        guard let record, !readyBuild.isEmpty, record.build == readyBuild else { return false }
        return now.timeIntervalSince1970 - record.readySince >= offerOnQuitAfter
    }

    /// Whether the bar shows Later.
    static func showsLater(critical: Bool, phase: String) -> Bool {
        !(critical && urgentPhases.contains(phase))
    }

    // The quit sheet's words.
    static let installAndQuit = "Install and quit"
    static let quitWithoutUpdating = "Quit without updating"
    static func quitTitle(_ version: String) -> String {
        "Wizard for Mac \(version) is ready. Install it while quitting?"
    }
    static let quitText = "Wizard first stops WizardOS on this Mac safely, then installs the update and quits. "
        + "It doesn't reopen by itself; the next time you open Wizard, it is up to date."
    static let cannotTitle = "Wizard can't update now"
    static func cannotText(_ reason: String) -> String {
        let r = reason.trimmingCharacters(in: .whitespacesAndNewlines)
        let sentence = r.isEmpty ? "Something is still running" : r
        let end = sentence.hasSuffix(".") || sentence.hasSuffix("…") ? "" : "."
        return "\(sentence)\(end) Wizard quits without updating and offers it again next time."
    }
}
