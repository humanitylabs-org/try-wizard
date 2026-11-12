import Foundation

/// Fresh-install onboarding ends with the local front door (127.0.0.1:48030) sending the
/// window to Wizard (127.0.0.1:48023) with `location.replace`. Same host, different port:
/// WebKit marks that page-initiated load `Sec-Fetch-Site: same-site`, and the Agent Service
/// in the shipped guest refuses same-site entry loads with `same_origin_required`
/// (wizard-agent-service issue 95). The window cancels that hand-off and loads the same URL
/// itself, the way a reload or a fresh app start does, which every guest admits.
enum FrontDoorHandoff {
    /// True for a main-frame GET from the local front door to the local Wizard UX origin.
    static func needsNativeLoad(from current: URL?, to target: URL, method: String?, mainFrame: Bool,
                                setup: URL, ux: URL) -> Bool {
        guard mainFrame, let current else { return false }
        guard (method ?? "GET").uppercased() == "GET" else { return false }
        return sameOrigin(current, setup) && sameOrigin(target, ux)
    }

    static func sameOrigin(_ a: URL, _ b: URL) -> Bool {
        guard let schemeA = a.scheme?.lowercased(), let hostA = a.host?.lowercased(),
              let schemeB = b.scheme?.lowercased(), let hostB = b.host?.lowercased() else { return false }
        return schemeA == schemeB && hostA == hostB && port(a) == port(b)
    }

    private static func port(_ url: URL) -> Int {
        if let port = url.port { return port }
        return url.scheme?.lowercased() == "https" ? 443 : 80
    }
}
