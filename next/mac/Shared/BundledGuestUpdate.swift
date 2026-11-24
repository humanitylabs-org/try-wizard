import Foundation

/// Whether this disk still needs the guest update the running app carries (try-wizard#162).
///
/// The app's guest update (Contents/Resources/GuestUpdate, guestPatch mac-stack-v1) used to run only from a Sparkle
/// transaction, the 0.6.1 legacy cold upgrade or the fresh-install marker. An app dragged in from the DMG over an
/// existing Wizard matches none of them, so its guest files never arrived. On each local start the app now asks this
/// rule, after the legacy and fresh-install checks:
///   - `received`: nothing to do. This release's guest update is on this disk (guest-receipt.json names this
///     releaseID and this disk), or the app carries none.
///   - `applyNow`: apply it once now (the Host is stopped), through the same stopped-disk clone, apply-guest-update,
///     receipt and rollback as an in-app update.
///   - `offer`: it is still missing, but an automatic try for this release already ran (it failed and the old disk
///     is back), so don't loop: start Wizard and offer "Finish updating Wizard (about a minute)".
/// The app also offers instead of applying when the Host is running, something records or Wizard is busy.
enum WizardBundledGuestUpdate {
    enum Decision: Equatable { case received, applyNow, offer }

    /// - receipt: updates/guest-receipt.json; journal: updates/journal.json; marker: updates/hand-install.json
    ///   (written before an automatic try, `releaseID` = the release it tried).
    static func decide(releaseID: String, carriesGuest: Bool, diskIdentity: String?,
                       receipt: [String: Any], journal: [String: Any], marker: [String: Any]) -> Decision {
        guard carriesGuest, !releaseID.isEmpty, let identity = diskIdentity, !identity.isEmpty else { return .received }
        if received(releaseID: releaseID, diskIdentity: identity, receipt: receipt, journal: journal) { return .received }
        if marker["releaseID"] as? String == releaseID { return .offer }
        // An update of this very release already put the old disk back: say so and offer, don't retry by itself.
        if journal["releaseID"] as? String == releaseID, journal["phase"] as? String == "guest-rolled-back" { return .offer }
        return .applyNow
    }

    static func received(releaseID: String, diskIdentity: String, receipt: [String: Any], journal: [String: Any]) -> Bool {
        guard receipt["diskIdentity"] as? String == diskIdentity else { return false }
        if let named = receipt["releaseID"] as? String { return named == releaseID }
        // Receipts written before try-wizard#162 don't name their release: the journal of the same transaction does.
        return journal["releaseID"] as? String == releaseID
            && journal["phase"] as? String == "guest-activated"
            && journal["diskIdentity"] as? String == diskIdentity
            && (journal["nonce"] as? String).map { !$0.isEmpty && receipt["transactionNonce"] as? String == $0 } == true
    }
}
