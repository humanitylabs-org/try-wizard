import Foundation

/// When the stopped-disk rollback clone (`updates/previous-disk.img`) may be retired after a guest update.
/// The clone is APFS copy-on-write, so every block the running Wizard changes afterwards is stored twice.
/// This is a pure decision with no I/O, so the SwiftPM tests can check every phase. The app does the delete.
enum WizardRollbackRetirement {
    /// Grace period after activation, so a problem reported the same day can still be rolled back.
    static let grace: TimeInterval = 24 * 60 * 60

    enum Verdict: Equatable {
        case retire
        /// Everything matches, but the local Wizard is not running normally yet.
        case waitForRunning
        /// Everything matches; look again after this many seconds.
        case waitForGrace(TimeInterval)
        /// The clone must stay for now (an update is in flight, rolled back, or the disk does not match).
        case keep(String)
    }

    static func verdict(journal: [String: Any], dataHome: String, diskIdentity: String?,
                        legacyComplete: [String: Any], activatedAt: Date?, runningNormally: Bool,
                        now: Date) -> Verdict {
        guard journal["dataHome"] as? String == dataHome else { return .keep("transaction belongs to another data home") }
        // Never while prepared, installing, guest-activating, rolled back or failed: only a completed activation.
        let phase = journal["phase"] as? String ?? ""
        guard phase == "guest-activated" else { return .keep("update phase is \(phase.isEmpty ? "unknown" : phase)") }
        guard let diskIdentity, journal["diskIdentity"] as? String == diskIdentity else {
            return .keep("live disk is not the activated disk")
        }
        if journal["kind"] as? String == "legacy-cold", legacyComplete["diskIdentity"] as? String != diskIdentity {
            return .keep("legacy completion receipt does not match the live disk")
        }
        guard let activatedAt else { return .keep("activation time unknown") }
        let age = now.timeIntervalSince(activatedAt)
        guard age >= grace else { return .waitForGrace(grace - max(age, 0)) }
        guard runningNormally else { return .waitForRunning }
        return .retire
    }
}
