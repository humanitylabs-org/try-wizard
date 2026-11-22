import Foundation

/// Maps may use the Mac's location, after the owner says yes in macOS's own prompt (try-wizard#135, part of
/// wizard-ux#1629). The shell already decides which app frame may even ask (switch `wizard/app-location`: only an app
/// that declared `permissions: [geolocation]` gets `allow="geolocation"`). This decides what the Mac app answers when
/// WebKit asks for location: never for a page that is not the Wizard's own shell, never for an address that is not the
/// Wizard's own, never without the Mac switch, and never before macOS's prompt was accepted. Denied in macOS stays
/// denied (no second prompt); the owner can change it in System Settings. Pure logic, so Tests/AppLocation drives it.
enum WizardAppLocationRule {
    /// The app's macOS location permission, as CoreLocation reports it.
    enum Access: Equatable {
        case notAsked, allowed, refused

        /// `CLAuthorizationStatus.rawValue`: 0 not determined, 1 restricted, 2 denied, 3 always, 4 when in use.
        init(rawStatus: Int32) {
            switch rawStatus {
            case 0: self = .notAsked
            case 3, 4: self = .allowed
            default: self = .refused
            }
        }
    }

    enum Decision: Equatable {
        /// Tell WebKit no; the page's `navigator.geolocation` gets PERMISSION_DENIED and nothing is shown.
        case deny
        /// Tell WebKit yes; macOS already has the owner's yes.
        case grant
        /// Show macOS's own prompt first, then grant only if the owner accepts.
        case askMacOS
    }

    static func decide(switchOn: Bool, trustedShell: Bool, wizardAddress: Bool, access: Access) -> Decision {
        guard switchOn, trustedShell, wizardAddress else { return .deny }
        switch access {
        case .allowed: return .grant
        case .refused: return .deny
        case .notAsked: return .askMacOS
        }
    }

    /// After macOS's prompt: grant only on an explicit yes. Still undecided (prompt dismissed, timed out) is a no.
    static func afterPrompt(_ access: Access) -> Decision { access == .allowed ? .grant : .deny }
}
