import Foundation

/// Every Wizard app as its own Dock icon on the Mac (try-wizard#147): the Mac answer to the shell's existing Add to
/// home screen request, the way the Android app answers it with a pinned shortcut. One Mac app, many icons: each icon is
/// a tiny launcher bundle in ~/Applications/Wizard Apps/ (no copy of the app, just a name, an icon and the app id) that
/// opens `wizard://app/<id>`, and WizardOS shows that app alone in its own window, on the same one-app page the Android
/// home-screen icons open (`/wizard-os-home/?app-session=<id>`). Names and icons always come from the shell, so every
/// shell load refreshes them. Pure logic, so Tests/DockApps drives it; the AppKit side is App/WizardDockApps.swift.
enum WizardDockAppsRule {
    static let scheme = "wizard"
    static let host = "app"
    static let folderName = "Wizard Apps"
    /// The Mac app that answers every launcher (`open -b`), so another app claiming `wizard://` can't take them.
    static let wizardBundleID = "org.humanitylabs.wizard.mvp"
    static let launcherBundlePrefix = "org.humanitylabs.wizard.app."
    /// Info.plist keys a launcher carries: which app it opens, and which shell icon it was drawn from.
    static let appIdKey = "WizardAppId"
    static let iconKey = "WizardIconSHA256"
    static let maxCandidates = 128
    static let maxMessage = 100_000
    static let maxIconDataURL = 90_000

    /// The shell's own app-id rule (wizard-ux core/home-screen-policy.js `validId`).
    static func validId(_ id: String) -> Bool {
        id.range(of: "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$", options: .regularExpression) != nil
    }

    /// A request id from the shell's port (wizard-ux core/home-screen-apps.js counts 1, 2, 3…).
    static func validRequestId(_ id: String) -> Bool {
        id.range(of: "^[0-9]{1,12}$", options: .regularExpression) != nil
    }

    /// `wizard://app/<id>`, optionally with a page inside that app (`?path=/apps/<id>/…`).
    static func launchURL(appId: String, path: String = "") -> URL? {
        guard validId(appId) else { return nil }
        var c = URLComponents(); c.scheme = scheme; c.host = host; c.path = "/" + appId
        if !path.isEmpty { c.queryItems = [URLQueryItem(name: "path", value: path)] }
        return c.url
    }

    /// The app (and page) a `wizard://app/<id>` link names. Anything else, `wizard://connect` included, is not ours.
    static func parse(_ url: URL) -> (appId: String, path: String)? {
        guard url.scheme?.lowercased() == scheme, url.host?.lowercased() == host,
              let c = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        let parts = c.path.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
        guard parts.count == 1, validId(parts[0]) else { return nil }
        let path = c.queryItems?.first(where: { $0.name == "path" })?.value ?? ""
        return (parts[0], path.hasPrefix("/") && !path.hasPrefix("//") ? path : "")
    }

    /// The one-app page for `appId` under the shell's home (`…/wizard-os-home/`); a page inside the app rides along as
    /// `app-path` (wizard-ux core/single-app-session.js follows it only when it lies inside that app).
    static func sessionURL(home: URL, appId: String, path: String = "") -> URL? {
        guard validId(appId), var c = URLComponents(url: home, resolvingAgainstBaseURL: true) else { return nil }
        c.path = root(of: c.path)
        if c.path.isEmpty { c.path = "/" }
        var items = [URLQueryItem(name: "app-session", value: appId)]
        if !path.isEmpty, path.hasPrefix("/"), !path.hasPrefix("//") { items.append(URLQueryItem(name: "app-path", value: path)) }
        c.queryItems = items; c.fragment = nil
        return c.url
    }

    /// The name the shell sent, made safe as a file name (it is the name the Dock, Launchpad and Spotlight show).
    static func cleanName(_ raw: String, appId: String) -> String? {
        var s = String(raw.unicodeScalars.filter { !CharacterSet.controlCharacters.contains($0) })
        s = s.replacingOccurrences(of: "/", with: "-").replacingOccurrences(of: ":", with: "-")
        s = s.trimmingCharacters(in: .whitespacesAndNewlines)
        while s.hasPrefix(".") { s.removeFirst() }
        s = s.trimmingCharacters(in: .whitespacesAndNewlines)
        guard validId(appId), !s.isEmpty, raw.count <= 80 else { return nil }
        return String(s.prefix(80))
    }

    /// `<name>.app`, or `<name> (<id>).app` when another app's launcher already has that name.
    static func bundleName(name: String, appId: String, takenByOthers: Set<String>) -> String {
        let plain = name + ".app"
        return takenByOthers.contains(plain.lowercased()) ? "\(name) (\(appId)).app" : plain
    }

    /// The launcher's Info.plist: no Dock icon of its own while it runs (it only hands the link over and quits).
    static func infoPlist(appId: String, name: String, version: String, iconSHA: String) -> [String: Any] {
        ["CFBundleName": name, "CFBundleDisplayName": name, "CFBundleIdentifier": launcherBundlePrefix + appId,
         "CFBundleExecutable": "launch", "CFBundlePackageType": "APPL", "CFBundleIconFile": "AppIcon",
         "CFBundleShortVersionString": version, "CFBundleVersion": version, "LSUIElement": true,
         "LSMinimumSystemVersion": "14.0", "NSHighResolutionCapable": true, appIdKey: appId, iconKey: iconSHA]
    }

    /// The launcher's executable: hand `wizard://app/<id>` to WizardOS and quit. The id is checked, so it can't break out.
    static func launchScript(appId: String) -> String? {
        guard validId(appId), let url = launchURL(appId: appId) else { return nil }
        return """
        #!/bin/sh
        # Opens one Wizard app in WizardOS (try-wizard#147). Made by WizardOS; it is refreshed from the shell.
        exec /usr/bin/open -b \(wizardBundleID) '\(url.absoluteString)'

        """
    }

    /// Icon sizes a launcher's AppIcon.icns carries (all PNG), drawn from the shell's 192 px app icon.
    static let iconSizes: [(type: String, pixels: Int)] = [
        ("icp4", 16), ("icp5", 32), ("ic11", 32), ("icp6", 64), ("ic12", 64), ("ic07", 128),
        ("ic13", 256), ("ic08", 256), ("ic14", 512), ("ic09", 512)]
    /// A Mac app icon's shape: the tile sits inside the 1024 grid with 100 px margins and rounded corners.
    static let iconInset = 100.0 / 1024.0
    static let iconCorner = 185.4 / 824.0

    /// An .icns file: `icns` + total length, then each entry as its type + length + PNG bytes.
    static func icns(_ entries: [(type: String, png: Data)]) -> Data {
        func be32(_ v: Int) -> Data { withUnsafeBytes(of: UInt32(v).bigEndian) { Data($0) } }
        var body = Data()
        for e in entries where e.type.utf8.count == 4 {
            body.append(Data(e.type.utf8)); body.append(be32(e.png.count + 8)); body.append(e.png)
        }
        var out = Data("icns".utf8); out.append(be32(body.count + 8)); out.append(body)
        return out
    }

    /// The shell's icon as PNG bytes: only `data:image/png;base64,…` within the same size bound the Android app uses.
    static func iconPNG(_ dataURL: String) -> Data? {
        let prefix = "data:image/png;base64,"
        guard dataURL.hasPrefix(prefix), dataURL.count <= maxIconDataURL,
              let data = Data(base64Encoded: String(dataURL.dropFirst(prefix.count))),
              data.starts(with: [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) else { return nil }
        return data
    }

    // MARK: Dock (com.apple.dock persistent-apps)

    static func dockEntry(for bundle: URL) -> [String: Any] {
        ["tile-data": ["file-data": ["_CFURLString": dockURLString(bundle), "_CFURLStringType": 15],
                       "file-label": bundle.deletingPathExtension().lastPathComponent],
         "tile-type": "file-tile"]
    }

    static func dockURLString(_ bundle: URL) -> String {
        let s = bundle.standardizedFileURL.absoluteString
        return s.hasSuffix("/") ? s : s + "/"
    }

    static func dockIndex(of bundle: URL, in apps: [[String: Any]]) -> Int? {
        let want = dockURLString(bundle)
        return apps.firstIndex { entry in
            guard let tile = entry["tile-data"] as? [String: Any], let file = tile["file-data"] as? [String: Any],
                  let s = file["_CFURLString"] as? String else { return false }
            let have = s.hasSuffix("/") ? s : s + "/"
            return have == want || URL(string: have)?.standardizedFileURL.absoluteString == want
        }
    }

    // MARK: Links between app windows

    enum LinkRoute: Equatable {
        /// Stays where it is (this app's own pages, a thread the app hosts, anything not another app's).
        case stay
        /// Another Wizard app: open (or bring forward) that app's own window at this page ("" = where it was).
        case otherApp(id: String, path: String)
        /// One of Wizard's own pages (home, chats, threads): the main window.
        case shell(path: String)
        /// Not this Wizard: the Mac's browser.
        case external
    }

    /// The directory an app's registered address lives under (`/apps/notes/index.html` → `/apps/notes/`).
    static func root(of path: String) -> String {
        path.hasSuffix("/") ? path : String(path[..<(path.lastIndex(of: "/").map { path.index(after: $0) } ?? path.endIndex)])
    }

    /// Where a link from the window of `currentApp` goes. `boxOrigins` are this Wizard's own `scheme://host:port`
    /// addresses; `appRoots` the installed apps' address roots from the shell's own app list (id → path root).
    static func route(_ url: URL, currentApp: String, boxOrigins: Set<String>, appRoots: [String: String]) -> LinkRoute {
        guard let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme), let host = url.host?.lowercased() else {
            return url.scheme == "about" || url.scheme == "blob" || url.scheme == "data" ? .stay : .external
        }
        let port = url.port ?? (scheme == "https" ? 443 : 80)
        guard boxOrigins.contains("\(scheme)://\(host):\(port)") else { return .external }
        let path = url.path.isEmpty ? "/" : url.path
        let c = URLComponents(url: url, resolvingAgainstBaseURL: false)
        var rest = c?.percentEncodedPath ?? path
        if rest.isEmpty { rest = "/" }
        if let q = c?.percentEncodedQuery { rest += "?" + q }
        if let f = c?.percentEncodedFragment { rest += "#" + f }
        if path == "/wizard-os-home" || path.hasPrefix("/wizard-os-home/") || path.hasPrefix("/wizard-os-home-") {
            let items = c?.queryItems ?? []
            if items.contains(where: { $0.name == "app-session" }) { return .stay }
            if let open = items.first(where: { $0.name == "open" })?.value, open != currentApp, appRoots[open] != nil {
                return .otherApp(id: open, path: "")
            }
            return .shell(path: rest)
        }
        // Encoded separators or dots never name another app (the shell's `within` refuses them the same way).
        if (c?.percentEncodedPath ?? "").range(of: "%(2f|5c|2e|25)", options: [.regularExpression, .caseInsensitive]) != nil { return .stay }
        var best: (id: String, root: String)?
        for (id, raw) in appRoots where validId(id) {
            let r = root(of: raw)
            guard r != "/", r.hasPrefix("/"), path.hasPrefix(r) || path + "/" == r else { continue }
            if best == nil || r.count > best!.root.count { best = (id, r) }
        }
        guard let best, best.id != currentApp else { return .stay }
        return .otherApp(id: best.id, path: rest)
    }
}
