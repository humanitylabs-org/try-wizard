import Foundation

/// Music and Podcasts show in the Mac's Now Playing and answer the media keys (try-wizard#142, the Mac part of
/// wizard-ux#1661). Only these two apps, the same fixed list as the Android player (Miguel, 20 Nov: "only Music and
/// Podcasts get the native media player, the same way only Maps gets location"). The app's page reports what it plays
/// (its `navigator.mediaSession` metadata and its audio element); the Mac app shows that in Control Center and sends
/// play/pause, skip back 15 / forward 30 (Podcasts) or next/previous (Music) back to that same page. Pure logic, so
/// Tests/NowPlaying drives it; the AppKit/MediaPlayer side is App/WizardNowPlaying.swift.
enum WizardNowPlayingRule {
    /// Installed app ids that may use Now Playing. Never widened by a page.
    static let apps: Set<String> = ["wizard-music", "wizard-podcasts"]
    static let skipBackSeconds = 15.0
    static let skipForwardSeconds = 30.0

    /// The app a frame belongs to, from its address path: `/apps/<id>/…` (the App Manager's app path) or `/<id>/…`
    /// (the Serve mount the shell uses). Anything else, including the shell's own page, is no app.
    static func appId(path: String) -> String? {
        let parts = path.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
        guard let first = parts.first else { return nil }
        let id = first == "apps" ? (parts.count > 1 ? parts[1] : "") : first
        return apps.contains(id) ? id : nil
    }

    /// The app whose report may be shown: the Wizard's own shell on screen, the frame at one of the Wizard's own
    /// addresses, and its path naming Music or Podcasts.
    static func admit(trustedShell: Bool, wizardAddress: Bool, path: String) -> String? {
        guard trustedShell, wizardAddress else { return nil }
        return appId(path: path)
    }

    enum Command: String, CaseIterable {
        case play, pause, toggle, next, previous, skipBack, skipForward, seek
    }

    /// Podcasts gets skip back 15 / forward 30, Music gets next/previous; both get play/pause and the progress bar.
    static func commands(for appId: String) -> [Command] {
        switch appId {
        case "wizard-podcasts": return [.play, .pause, .toggle, .skipBack, .skipForward, .seek]
        case "wizard-music": return [.play, .pause, .toggle, .next, .previous, .seek]
        default: return []
        }
    }

    /// JavaScript run in the playing app's frame. Only a fixed command name and a finite number reach the page.
    /// It evaluates to a boolean, so WebKit always has a value to hand back.
    static func script(_ command: Command, value: Double? = nil) -> String {
        var v = value ?? 0
        if !v.isFinite { v = 0 }
        if command == .skipBack, value == nil { v = skipBackSeconds }
        if command == .skipForward, value == nil { v = skipForwardSeconds }
        return "(window.__wizardNowPlaying ? window.__wizardNowPlaying.command('\(command.rawValue)', \(v)) : false) === true"
    }

    /// Clicking Now Playing brings Wizard forward on the app that is playing (wizard-ux `window.WizOpenApp`).
    static func openScript(_ appId: String) -> String? {
        guard apps.contains(appId) else { return nil }
        return "(() => { const o = window.WizOpenApp; return typeof o === 'function' ? !!o('\(appId)') : false; })()"
    }

    /// Who owns Now Playing after a report: a page that starts playing takes it; the owner keeps it while paused (so
    /// the play key resumes it); a page that goes away gives it up. A paused page that never played claims nothing.
    static func owner(current: String?, report appId: String, playing: Bool, gone: Bool) -> String? {
        if gone { return current == appId ? nil : current }
        if playing { return appId }
        return current
    }

    /// One report from the page, cleaned: short strings, finite non-negative numbers, an http(s) artwork address.
    struct State: Equatable {
        var playing = false
        var gone = false
        var title = ""
        var artist = ""
        var album = ""
        var artwork: URL?
        var duration = 0.0
        var position = 0.0
        var rate = 1.0

        static let maxText = 300

        init?(_ body: [String: Any]) {
            guard (body["v"] as? NSNumber)?.intValue == 1 else { return nil }
            gone = (body["gone"] as? Bool) ?? false
            playing = !gone && ((body["playing"] as? Bool) ?? false)
            title = State.text(body["title"])
            artist = State.text(body["artist"])
            album = State.text(body["album"])
            if let s = body["artwork"] as? String, s.count <= 4096, let u = URL(string: s),
               let scheme = u.scheme?.lowercased(), scheme == "http" || scheme == "https", u.host?.isEmpty == false {
                artwork = u
            }
            duration = State.number(body["duration"])
            position = State.number(body["position"])
            if duration > 0 { position = min(position, duration) }
            let r = State.number(body["rate"])
            rate = r > 0 && r <= 16 ? r : 1
        }

        init() {}

        private static func text(_ any: Any?) -> String {
            guard let s = any as? String else { return "" }
            return String(s.trimmingCharacters(in: .whitespacesAndNewlines).prefix(maxText))
        }

        private static func number(_ any: Any?) -> Double {
            guard let n = any as? NSNumber else { return 0 }
            let d = n.doubleValue
            return d.isFinite && d > 0 ? d : 0
        }
    }

    /// The name Now Playing shows when the page gave no title.
    static func fallbackTitle(_ appId: String) -> String { appId == "wizard-podcasts" ? "Podcasts" : "Music" }

    /// Largest artwork the Mac app downloads.
    static let maxArtworkBytes = 8 * 1024 * 1024
}
