import AVFoundation
import AppKit
import ServiceManagement
import WebKit

// Wizard: the native front end. Opens instantly and connects to a Wizard OS back end,
// either on this Mac (run by the Wizard Host menu-bar service) or on another computer.

// MARK: - Back-end connections

struct Backend: Codable, Equatable {
    enum Kind: String, Codable { case thisMac, remote }
    var kind: Kind
    var name: String
    var url: String   // remote: base URL of that computer's Wizard
}

enum Store {
    static let d = UserDefaults.standard
    static var backends: [Backend] {
        get { (d.data(forKey: "backends")).flatMap { try? JSONDecoder().decode([Backend].self, from: $0) } ?? [] }
        set { d.set(try? JSONEncoder().encode(newValue), forKey: "backends") }
    }
    static var activeIndex: Int {
        get { d.integer(forKey: "activeBackend") }
        set { d.set(newValue, forKey: "activeBackend") }
    }
    static var active: Backend? {
        let b = backends
        return b.indices.contains(activeIndex) ? b[activeIndex] : b.first
    }
    static var osFeedURL: URL {
        URL(string: d.string(forKey: "osFeedURL") ?? "https://private.wizard001.com/reports/wizard-next/os/latest.json")!
    }
}

// MARK: - Wizard OS installer (download on demand)

final class OSInstaller: NSObject, URLSessionDownloadDelegate {
    var onProgress: ((String, Double?) -> Void)?
    var onDone: ((Error?) -> Void)?
    private var expectedSHA = ""
    private var version = ""
    private lazy var session = URLSession(configuration: .default, delegate: self, delegateQueue: .main)

    struct Feed: Decodable { let version: String; let url: String; let sha256: String; let bytes: Int64? }

    /// Install from a local wizard-os-*.tar.xz; integrity comes from the per-file hashes in its manifest.
    func install(from file: URL) {
        onProgress?("Setting up Wizard OS from \(file.lastPathComponent)…", nil)
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try Self.unpack(file, sha256: "") }
            DispatchQueue.main.async {
                if case .failure(let e) = result { self.onDone?(e) } else { self.onDone?(nil) }
            }
        }
    }

    func install() {
        onProgress?("Finding the latest Wizard OS…", nil)
        var req = URLRequest(url: Store.osFeedURL); req.timeoutInterval = 8
        session.dataTask(with: req) { data, resp, err in
            DispatchQueue.main.async {
                guard let data, (resp as? HTTPURLResponse)?.statusCode == 200,
                      let feed = try? JSONDecoder().decode(Feed.self, from: data),
                      let url = URL(string: feed.url, relativeTo: Store.osFeedURL) else {
                    self.onDone?(err ?? Self.error("Couldn't reach the Wizard OS download. Check your connection and try again.")); return
                }
                self.expectedSHA = feed.sha256.lowercased(); self.version = feed.version
                self.onProgress?("Downloading Wizard OS \(feed.version)…", 0)
                self.session.downloadTask(with: url).resume()
            }
        }.resume()
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData _: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        guard totalBytesExpectedToWrite > 0 else { return }
        let mb = Double(totalBytesWritten) / 1_048_576, total = Double(totalBytesExpectedToWrite) / 1_048_576
        onProgress?(String(format: "Downloading Wizard OS %@… %.0f of %.0f MB", version, mb, total),
                    Double(totalBytesWritten) / Double(totalBytesExpectedToWrite))
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        let fm = FileManager.default
        let staged = fm.temporaryDirectory.appendingPathComponent("wizard-os-\(UUID().uuidString).tar.xz")
        do { try fm.moveItem(at: location, to: staged) } catch { onDone?(error); return }
        if let code = (downloadTask.response as? HTTPURLResponse)?.statusCode, code != 200 {
            onDone?(Self.error("Download failed (HTTP \(code)).")); return
        }
        onProgress?("Setting up Wizard OS on this Mac…", nil)
        let sha = expectedSHA
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try Self.unpack(staged, sha256: sha) }
            try? fm.removeItem(at: staged)
            DispatchQueue.main.async {
                if case .failure(let e) = result { self.onDone?(e) } else { self.onDone?(nil) }
            }
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error { onDone?(error) }
    }

    static func error(_ s: String) -> NSError { NSError(domain: "Wizard", code: 1, userInfo: [NSLocalizedDescriptionKey: s]) }

    @discardableResult
    static func run(_ tool: String, _ args: [String]) throws -> String {
        let p = Process(); p.executableURL = URL(fileURLWithPath: tool); p.arguments = args
        let out = Pipe(); p.standardOutput = out; p.standardError = out
        try p.run(); p.waitUntilExit()
        let text = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        if p.terminationStatus != 0 { throw error("\(URL(fileURLWithPath: tool).lastPathComponent) failed: \(text.suffix(300))") }
        return text
    }

    static func verifyManifest(in dir: URL) throws {
        let bad = error("This file isn't a valid Wizard OS image. Download it again from the release page.")
        guard let data = try? Data(contentsOf: dir.appendingPathComponent("manifest.json")),
              let m = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let files = m["files"] as? [String: String], !files.isEmpty else { throw bad }
        for (rel, want) in files {
            guard !rel.contains(".."), FileManager.default.fileExists(atPath: dir.appendingPathComponent(rel).path) else { throw bad }
            let got = try run("/usr/bin/shasum", ["-a", "256", dir.appendingPathComponent(rel).path]).split(separator: " ").first.map(String.init) ?? ""
            guard got == want.lowercased() else { throw bad }
        }
    }

    static func unpack(_ archive: URL, sha256: String) throws {
        let digest = sha256.isEmpty ? "" : (try run("/usr/bin/shasum", ["-a", "256", archive.path]).split(separator: " ").first.map(String.init) ?? "")
        guard sha256.isEmpty || digest == sha256 else { throw error("The Wizard OS download was corrupted. Please try again.") }
        let fm = FileManager.default
        let dest = WizardShared.osDir
        let staging = WizardShared.supportDir.appendingPathComponent("os-staging", isDirectory: true)
        try? fm.removeItem(at: staging)
        try fm.createDirectory(at: staging, withIntermediateDirectories: true)
        try run("/usr/bin/tar", ["-xJf", archive.path, "-C", staging.path])
        try verifyManifest(in: staging)
        let rootfs = staging.appendingPathComponent("rootfs.img")
        let disk = staging.appendingPathComponent("disk.img")
        try fm.moveItem(at: rootfs, to: disk)
        // Sparse 64 GB disk: only blocks Wizard actually writes take space on the Mac.
        let h = try FileHandle(forWritingTo: disk); try h.truncate(atOffset: 64 << 30); try h.close()
        if fm.fileExists(atPath: dest.path) {
            // Keep the existing disk (the Wizard's memory and files); only replace boot files.
            let old = dest.appendingPathComponent("disk.img")
            if fm.fileExists(atPath: old.path) { try fm.removeItem(at: disk); try fm.moveItem(at: old, to: disk) }
            if let mac = try? Data(contentsOf: dest.appendingPathComponent("mac-address")) {
                try mac.write(to: staging.appendingPathComponent("mac-address"))
            }
            try fm.removeItem(at: dest)
        }
        try fm.moveItem(at: staging, to: dest)
    }
}

// MARK: - Wizard Host (back-end service) control

enum HostControl {
    static var embeddedHostURL: URL {
        Bundle.main.bundleURL.appendingPathComponent("Contents/Library/LoginItems/Wizard Host.app")
    }

    static var isRunning: Bool {
        !NSRunningApplication.runningApplications(withBundleIdentifier: WizardShared.hostBundleID).isEmpty
    }

    /// Start the menu-bar service now and at every login.
    static func ensureRunning() {
        let service = SMAppService.loginItem(identifier: WizardShared.hostBundleID)
        if service.status != .enabled {
            do { try service.register() } catch { NSLog("Wizard: login item registration failed: \(error)") }
        }
        if !isRunning {
            let cfg = NSWorkspace.OpenConfiguration(); cfg.activates = false; cfg.addsToRecentItems = false
            NSWorkspace.shared.openApplication(at: embeddedHostURL, configuration: cfg) { _, err in
                if let err { NSLog("Wizard: couldn't launch Wizard Host: \(err)") }
            }
        }
    }

    static func send(_ command: String) {
        DistributedNotificationCenter.default().postNotificationName(
            Notification.Name("org.humanitylabs.wizard.host.command"), object: command, userInfo: nil, deliverImmediately: true)
    }

    static func waitForLocalWizard(timeout: TimeInterval, tick: @escaping (TimeInterval) -> Void, done: @escaping (Bool) -> Void) {
        let start = Date()
        func poll() {
            WizardShared.probeReady { ok in
                DispatchQueue.main.async {
                    if ok { done(true); return }
                    let elapsed = Date().timeIntervalSince(start)
                    if elapsed > timeout { done(false); return }
                    tick(elapsed)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15, execute: poll)
                }
            }
        }
        poll()
    }
}

// MARK: - Native bridge (window.webkit.messageHandlers.wizardNative)

/// One namespaced page→native channel. Capabilities register a handler under a prefix
/// (e.g. "app.", later "meeting."). Message: {id, method, params}; reply via window.wizardNativeReply(id, result).
final class NativeBridge: NSObject, WKScriptMessageHandler {
    static let name = "wizardNative"
    static let shared = NativeBridge()
    typealias Handler = (_ method: String, _ params: [String: Any], _ reply: @escaping (Any?) -> Void) -> Void
    private var handlers: [String: Handler] = [:]

    override init() {
        super.init()
        register("app.") { method, _, reply in
            switch method {
            case "app.info":
                reply(["version": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") ?? "",
                       "backend": Store.active?.kind.rawValue ?? "", "capabilities": Array(NativeBridge.shared.handlers.keys)])
            default: reply(nil)
            }
        }
    }

    func register(_ prefix: String, _ handler: @escaping Handler) { handlers[prefix] = handler }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let web = message.webView, let body = message.body as? [String: Any],
              let method = body["method"] as? String,
              let origin = URL(string: "\(message.frameInfo.securityOrigin.protocol)://\(message.frameInfo.securityOrigin.host)"),
              ["127.0.0.1", "localhost", Store.active.flatMap { URL(string: $0.url)?.host }].contains(origin.host)
        else { return }
        let id = body["id"] ?? NSNull()
        var params = body["params"] as? [String: Any] ?? [:]
        let so = message.frameInfo.securityOrigin
        params["_origin"] = "\(so.protocol)://\(so.host)\(so.port != 0 ? ":\(so.port)" : "")"
        guard let handler = handlers.first(where: { method.hasPrefix($0.key) })?.value else { return }
        handler(method, params) { result in
            let payload = (try? JSONSerialization.data(withJSONObject: ["id": id, "result": result ?? NSNull()], options: [.fragmentsAllowed]))
                .flatMap { String(data: $0, encoding: .utf8) } ?? "null"
            DispatchQueue.main.async {
                web.evaluateJavaScript("window.wizardNativeReply && window.wizardNativeReply(\(payload))")
            }
        }
    }
}

// MARK: - Window

final class WizardWindowController: NSWindowController, WKNavigationDelegate, WKUIDelegate {
    let web: WKWebView
    let overlay = NSView()
    let title = NSTextField(labelWithString: "")
    let subtitle = NSTextField(labelWithString: "")
    let progress = NSProgressIndicator()
    let stack = NSStackView()
    var buttons: [NSButton] = []
    var loadedAt: Date?
    let installer = OSInstaller()

    init() {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        cfg.userContentController.add(NativeBridge.shared, name: NativeBridge.name)
        // window.wizardNative.meetings etc. — present only inside Wizard.app; pages fall back to web APIs elsewhere.
        cfg.userContentController.addUserScript(WKUserScript(source: MeetingBridge.adapterJS, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = WKWebView(frame: .zero, configuration: cfg)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 780),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                              backing: .buffered, defer: false)
        window.title = "Wizard"
        window.titlebarAppearsTransparent = true
        window.minSize = NSSize(width: 380, height: 560)
        window.backgroundColor = NSColor(calibratedRed: 0.06, green: 0.06, blue: 0.08, alpha: 1)
        window.appearance = NSAppearance(named: .darkAqua)
        window.setFrameAutosaveName("WizardMainWindow")
        if !window.setFrameUsingName("WizardMainWindow") { window.center() }
        super.init(window: window)

        web.navigationDelegate = self
        web.uiDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        web.customUserAgent = nil
        web.allowsBackForwardNavigationGestures = false

        let root = NSView()
        root.wantsLayer = true
        root.layer?.backgroundColor = window.backgroundColor.cgColor
        window.contentView = root
        for v in [web, overlay] {
            v.translatesAutoresizingMaskIntoConstraints = false
            root.addSubview(v)
            NSLayoutConstraint.activate([v.leadingAnchor.constraint(equalTo: root.leadingAnchor),
                                         v.trailingAnchor.constraint(equalTo: root.trailingAnchor),
                                         v.topAnchor.constraint(equalTo: root.topAnchor),
                                         v.bottomAnchor.constraint(equalTo: root.bottomAnchor)])
        }
        overlay.wantsLayer = true
        overlay.layer?.backgroundColor = window.backgroundColor.cgColor
        buildOverlay()
    }
    required init?(coder: NSCoder) { fatalError() }

    private func buildOverlay() {
        let mark = NSTextField(labelWithString: "✦")
        mark.font = .systemFont(ofSize: 44, weight: .light)
        mark.textColor = NSColor(calibratedRed: 0.72, green: 0.62, blue: 1, alpha: 1)
        title.font = .systemFont(ofSize: 24, weight: .semibold)
        title.textColor = .white
        title.alignment = .center
        subtitle.font = .systemFont(ofSize: 14)
        subtitle.textColor = NSColor(white: 0.72, alpha: 1)
        subtitle.alignment = .center
        subtitle.maximumNumberOfLines = 4
        subtitle.preferredMaxLayoutWidth = 420
        subtitle.lineBreakMode = .byWordWrapping
        progress.style = .bar
        progress.isIndeterminate = true
        progress.controlSize = .small
        progress.widthAnchor.constraint(equalToConstant: 280).isActive = true
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        [mark, title, subtitle, progress].forEach { stack.addArrangedSubview($0) }
        stack.setCustomSpacing(6, after: title)
        overlay.addSubview(stack)
        NSLayoutConstraint.activate([stack.centerXAnchor.constraint(equalTo: overlay.centerXAnchor),
                                     stack.centerYAnchor.constraint(equalTo: overlay.centerYAnchor),
                                     stack.widthAnchor.constraint(lessThanOrEqualToConstant: 460)])
    }

    func showOverlay(_ t: String, _ s: String, progress p: Double? = nil, spinning: Bool = true, actions: [(String, Selector)] = []) {
        overlay.isHidden = false
        title.stringValue = t
        subtitle.stringValue = s
        progress.isHidden = !spinning
        if let p { progress.isIndeterminate = false; progress.doubleValue = p * 100 }
        else { progress.isIndeterminate = true; progress.startAnimation(nil) }
        buttons.forEach { $0.removeFromSuperview() }
        buttons = actions.enumerated().map { i, a in
            let b = NSButton(title: a.0, target: self, action: a.1)
            b.bezelStyle = .rounded
            b.controlSize = .large
            if i == 0 { b.keyEquivalent = "\r" }
            b.widthAnchor.constraint(greaterThanOrEqualToConstant: 300).isActive = true
            stack.addArrangedSubview(b)
            return b
        }
    }

    // MARK: Flow

    func begin() {
        homeURL = nil; resolvedOrigins = []
        guard let backend = Store.active else { showChooser(); return }
        switch backend.kind {
        case .thisMac:
            guard WizardShared.osInstalled else { installOnThisMac(); return }
            connectLocal()
        case .remote:
            showOverlay("Connecting…", backend.name, spinning: true)
            if let url = URL(string: backend.url) { resolveHome(url) { [weak self] home in self?.homeURL = home; self?.load(home) } }
        }
    }

    // MARK: Wizard UX (wizard-ux) and the native bridge (wizard-os spec/NATIVE_BRIDGE.md)

    /// Where this window's Wizard lives right now: Wizard UX when the back end serves it, else the address as given.
    var homeURL: URL?
    func loadHome() {
        if let homeURL { load(homeURL); return }
        if let b = Store.active, let u = URL(string: b.url) { load(u) }
    }

    /// Wizard UX is served at /wizard-os-home/ on a Wizard's origin and picks its desktop shell inside this app.
    /// A root or legacy /wizard/ address is upgraded to it when the back end answers there; a deeper address stays as typed.
    /// `defaults write org.humanitylabs.wizard LegacyUX -bool true` keeps the old UX.
    func resolveHome(_ base: URL, done: @escaping (URL) -> Void) {
        let p = base.path.isEmpty ? "/" : base.path
        guard !UserDefaults.standard.bool(forKey: "LegacyUX"), p == "/" || p == "/wizard" || p.hasPrefix("/wizard/"),
              let scheme = base.scheme, let host = base.host else { done(base); return }
        var c = URLComponents(); c.scheme = scheme; c.host = host; c.port = base.port
        guard let origin = c.url, let entry = URL(string: "/wizard-os-home/", relativeTo: origin)?.absoluteURL,
              let probe = URL(string: "desktop.html", relativeTo: entry)?.absoluteURL else { done(base); return }
        var req = URLRequest(url: probe, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 4)
        req.httpMethod = "GET"
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200 && (data.map { String(decoding: $0.prefix(4096), as: UTF8.self) }?.contains("data-shell") ?? false)
            NSLog("Wizard: Wizard UX %@ at %@", ok ? "found" : "not found", entry.absoluteString)
            DispatchQueue.main.async { done(ok ? entry : base) }
        }.resume()
    }

    /// Native → page: dispatch a bridge event when the page is Wizard UX and handles it.
    /// Calls back nil when it isn't (legacy UX, onboarding, still loading) so callers can fall back.
    /// For wizard:orb it waits for the page's wizard:orb-state answer.
    func uxSend(_ event: String, _ detail: [String: Any], done: @escaping (String?) -> Void) {
        let js = """
        const ux = window.wizardUX;
        if (!ux || !Array.isArray(ux.events) || !ux.events.includes(name)) return null;
        if (name !== 'wizard:orb') { window.dispatchEvent(new CustomEvent(name, { detail })); return 'sent'; }
        return await new Promise(res => {
          const t = setTimeout(() => res('pending'), 2000);
          window.addEventListener('wizard:orb-state', e => { clearTimeout(t); res((e.detail && e.detail.state) || 'none'); }, { once: true });
          window.dispatchEvent(new CustomEvent(name, { detail }));
        });
        """
        web.callAsyncJavaScript(js, arguments: ["name": event, "detail": detail], in: nil, in: .page) { r in
            switch r {
            case .success(let v): done(v as? String)
            case .failure(let e): NSLog("Wizard: bridge %@ failed: %@", event, e.localizedDescription); done(nil)
            }
        }
    }

    /// Is the page in the window Wizard UX (bridge ready)?
    func uxState(_ done: @escaping ([String: Any]?) -> Void) {
        web.evaluateJavaScript("window.wizardUX ? JSON.stringify(window.wizardUX) : ''") { r, _ in
            let s = (r as? String) ?? ""
            done(s.isEmpty ? nil : (try? JSONSerialization.jsonObject(with: Data(s.utf8))) as? [String: Any])
        }
    }

    func showChooser() {
        showOverlay("Where should Wizard live?",
                    "Wizard is your own AI with its own computer. Run it on this Mac, or connect to a Wizard you already have on another computer.",
                    spinning: false,
                    actions: [("On this Mac", #selector(chooseThisMac)),
                              ("On another computer…", #selector(chooseRemote))])
    }

    @objc func chooseThisMac() {
        var list = Store.backends.filter { $0.kind != .thisMac }
        list.insert(Backend(kind: .thisMac, name: "This Mac", url: WizardShared.localSetupURL.absoluteString), at: 0)
        Store.backends = list; Store.activeIndex = 0
        begin()
    }

    @objc func chooseRemote() {
        let alert = NSAlert()
        alert.messageText = "Connect to a Wizard on another computer"
        alert.informativeText = "Paste the address of that computer's Wizard (for example https://wizard.your-tailnet.ts.net or http://192.168.1.20:8923)."
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 360, height: 24))
        field.placeholderString = "https://…"
        alert.accessoryView = field
        alert.addButton(withTitle: "Connect"); alert.addButton(withTitle: "Cancel")
        alert.window.initialFirstResponder = field
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        var text = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.contains("://") { text = "https://" + text }
        guard let url = URL(string: text), let host = url.host, ["http", "https"].contains(url.scheme ?? "") else {
            showOverlay("That address doesn't look right", text, spinning: false,
                        actions: [("Try again", #selector(chooseRemote)), ("Back", #selector(backToChooser))]); return
        }
        var list = Store.backends.filter { $0.url != url.absoluteString }
        list.append(Backend(kind: .remote, name: host, url: url.absoluteString))
        Store.backends = list; Store.activeIndex = list.count - 1
        (NSApp.delegate as? AppDelegate)?.rebuildWizardMenu()
        begin()
    }

    @objc func backToChooser() { showChooser() }
    @objc func retry() { begin() }

    func installOnThisMac() {
        showOverlay("Setting up Wizard on this Mac", "Downloading Wizard OS, a small Linux computer just for your Wizard. This happens once.", progress: nil)
        installer.onProgress = { [weak self] msg, p in
            self?.showOverlay("Setting up Wizard on this Mac", msg, progress: p)
        }
        installer.onDone = { [weak self] err in
            guard let self else { return }
            if let err {
                // A bad picked file says so; an unreachable feed just shows the GitHub steps.
                let bad = err.localizedDescription.contains("valid Wizard OS")
                self.showGetOS(note: bad ? err.localizedDescription : nil)
            } else {
                HostControl.send("start")
                self.connectLocal()
            }
        }
        installer.install()
    }

    /// Off the Wizard team network the automatic download isn't reachable: get the file from GitHub instead.
    func showGetOS(note: String? = nil) {
        showOverlay("Get Wizard OS",
                    (note.map { $0 + "\n\n" } ?? "") + "1. Click Download from GitHub and download wizard-os-0.1.0.tar.xz (about 270 MB).\n2. Come back here and click Choose Downloaded File.",
                    spinning: false,
                    actions: [("Download from GitHub", #selector(openReleasePage)),
                              ("Choose Downloaded File…", #selector(chooseOSFile)),
                              ("Back", #selector(backToChooser))])
    }

    @objc func openReleasePage() {
        NSWorkspace.shared.open(URL(string: "https://github.com/humanitylabs-org/try-wizard/releases/latest")!)
    }

    @objc func chooseOSFile() {
        let panel = NSOpenPanel()
        panel.message = "Choose the wizard-os-….tar.xz file you downloaded"
        panel.allowedContentTypes = []; panel.allowsOtherFileTypes = true
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        guard panel.runModal() == .OK, let file = panel.url else { return }
        showOverlay("Setting up Wizard on this Mac", "Checking \(file.lastPathComponent)…", progress: nil)
        installer.install(from: file)
    }

    func connectLocal() {
        let started = Date()
        HostControl.ensureRunning()
        HostControl.send("start")
        var shown = false
        HostControl.waitForLocalWizard(timeout: 120, tick: { [weak self] elapsed in
            if elapsed > 0.6 && !shown { shown = true; self?.showOverlay("Waking up your Wizard…", "Starting Wizard OS on this Mac.") }
        }, done: { [weak self] ok in
            guard let self else { return }
            if ok {
                NSLog("Wizard: local back end ready after %.2fs", Date().timeIntervalSince(started))
                self.load(WizardShared.localSetupURL)
            } else {
                self.showOverlay("Wizard OS didn't start", "Open the Wizard menu-bar icon → Show Logs, or try again.", spinning: false,
                                 actions: [("Try again", #selector(self.retry)), ("Back", #selector(self.backToChooser))])
            }
        })
    }

    func load(_ url: URL) {
        loadedAt = nil
        web.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20))
    }

    // MARK: WKNavigationDelegate

    var onNavigate: () -> Void = {}
    /// Origins already checked for Wizard UX this session (so a legacy-only back end isn't probed on every load).
    var resolvedOrigins: Set<String> = []

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // Landed on the legacy UX root (e.g. local onboarding redirects to /wizard/): switch to Wizard UX once if served.
        if homeURL == nil, let u = webView.url, u.path == "/wizard" || u.path == "/wizard/", let h = u.host {
            let key = "\(u.scheme ?? "")://\(h):\(u.port ?? 0)"
            if !resolvedOrigins.contains(key) {
                resolvedOrigins.insert(key)
                resolveHome(u) { [weak self] home in
                    guard let self, home != u else { return }
                    self.homeURL = home; self.load(home)
                }
            }
        }
        onNavigate()
        loadedAt = Date()
        localRetries = 0
        overlay.isHidden = true
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        loadFailed(error)
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { loadFailed(error) }

    private var localRetries = 0

    private func loadFailed(_ error: Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        // Wizard OS on this Mac may still be bringing a service up: retry quietly before showing an error.
        if Store.active?.kind == .thisMac, localRetries < 12 {
            localRetries += 1
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in self?.load(WizardShared.localSetupURL) }
            return
        }
        localRetries = 0
        let name = Store.active?.name ?? "Wizard"
        showOverlay("Can't reach \(name)", error.localizedDescription, spinning: false,
                    actions: [("Try again", #selector(retry)), ("Choose another Wizard", #selector(backToChooser))])
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.allow); return }
        if action.targetFrame == nil || (action.navigationType == .linkActivated && !isWizardOrigin(url)) {
            if ["http", "https", "mailto"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.beginSheetModal(for: window!) { completionHandler($0 == .OK ? panel.urls : nil) }
    }

    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo,
                 type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        var c = URLComponents(); c.scheme = origin.protocol; c.host = origin.host
        if origin.port != 0 { c.port = origin.port }
        decisionHandler(c.url.map(isWizardOrigin) == true ? .grant : .deny)
    }

    private func isWizardOrigin(_ url: URL) -> Bool {
        if url.host == "127.0.0.1" || url.host == "localhost" { return true }
        if let b = Store.active, let h = URL(string: b.url)?.host { return url.host == h }
        return false
    }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var controller: WizardWindowController!
    let wizardsMenu = NSMenu(title: "Wizard")
    let statusMenu = WizardStatusMenu()
    let statusActions = WizardStatusActions()
    var bindingsTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.appearance = NSAppearance(named: .darkAqua)
        buildMenus()
        installQAHooks()
        controller = WizardWindowController()
        controller.window?.delegate = self
        controller.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
        controller.begin()
        installWizardKey()
        installMeetings()
    }

    // MARK: Mizel: native capture, floating recorder, call prompts, voice keys

    func installMeetings() {
        MeetingBridge.register(origin: { [weak self] in self?.wizardOrigin })
        MeetingSpool.shared.kick()   // deliver anything left from a previous run
        let panel = RecorderPanel.shared
        panel.onExpand = { [weak self] url in
            guard let self, let u = URL(string: url) else { return }
            if let o = self.wizardOrigin, u.host == o.host, let c = URLComponents(url: u, resolvingAgainstBaseURL: false) {
                var p = c.percentEncodedPath; if let q = c.percentEncodedQuery { p += "?" + q }; if let f = c.percentEncodedFragment { p += "#" + f }
                self.openView(p)
            } else { self.showMainWindow(); self.controller.load(u) }
        }
        panel.shouldShow = { [weak self] in
            guard let self, NSApp.isActive, self.controller.window?.isVisible == true, self.controller.window?.isMiniaturized == false,
                  let s = MeetingRecorder.shared.session, let u = self.controller.web.url else { return true }
            // Mizel already shows this recording in the window.
            return !(u.path.contains("/meetings") && (u.fragment ?? "").contains(s.meetingId))
        }
        for n in [NSApplication.didBecomeActiveNotification, NSApplication.didResignActiveNotification, NSWindow.didMiniaturizeNotification,
                  NSWindow.didDeminiaturizeNotification, NSWindow.willCloseNotification] {
            NotificationCenter.default.addObserver(forName: n, object: nil, queue: .main) { _ in DispatchQueue.main.async { panel.sync() } }
        }
        controller.onNavigate = { panel.sync() }

        CallPrompt.shared.onRecord = { [weak self] title, eventId in self?.recordNew(title: title, eventId: eventId) }
        CallDetector.shared.origin = { [weak self] in self?.wizardOrigin }
        CallDetector.shared.install()

        let vk = VoiceKeys.shared
        vk.origin = { [weak self] in self?.wizardOrigin }
        vk.orb = { [weak self] start in self?.orb(start) }
        VoiceKeys.deliverInWizard = { [weak self] text, done in
            guard let self, NSApp.isActive, self.controller.window?.isKeyWindow == true else { done(false); return }
            self.controller.uxSend("wizard:dictation", ["text": text]) { done($0 != nil) }
        }
        vk.install(prompt: false)

        statusActions.isRecording = { MeetingRecorder.shared.isRecording }
        statusActions.recordToggle = { [weak self] in
            if MeetingRecorder.shared.isRecording { MeetingRecorder.shared.stop(finalize: true) { _ in } }
            else { self?.recordNew(title: nil, eventId: CallDetector.shared.currentEvent()?["id"] as? String) }
        }
    }

    func recordNew(title: String?, eventId: String?) {
        guard let o = wizardOrigin else { return }
        let clean = title.map { $0.replacingOccurrences(of: "^(Call: |Starting now: )", with: "", options: .regularExpression) }
        MeetingRecorder.shared.startNew(origin: o, title: eventId == nil ? clean : nil, calendarEventId: eventId) { err in
            if let err {
                let a = NSAlert(); a.messageText = "Couldn't start recording"; a.informativeText = err.localizedDescription; a.runModal()
            }
        }
    }

    /// Right ⌘: talk to your Wizard with its own orb (new thread → voice; tap again → finish and send).
    /// Wizard UX gets a wizard:orb event and answers with its state; the legacy UX is driven through its buttons.
    func orb(_ start: Bool) {
        guard let o = wizardOrigin else { return }
        showMainWindow()
        _ = start
        // One toggle: recording → finish and send; idle → start voice (opening a new thread if no chat is open).
        let legacy = "(() => { const f = document.querySelector('button.voice-fab'); const l = f ? (f.getAttribute('aria-label')||'') : ''; if (f && /Finish and send/.test(l)) { f.click(); return 'sent'; } if (/Opening microphone|Transcribing/.test(l)) return 'busy'; if (f && !f.disabled && /Start voice/.test(l)) { f.click(); return 'voice'; } const n = document.querySelector('button.new-thread-fab'); if (n) { n.click(); return 'new'; } return 'none'; })()"
        var tries = 0
        func retry() {
            guard tries < 25 else { MeetingLog.log("orb: gave up"); return }
            tries += 1
            if tries == 1, start, let u = controller.web.url, u.path.contains("/meetings") || u.path.contains("/files") || u.path.contains("/apps") {
                controller.loadHome()
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: attempt)
        }
        func attempt() {
            controller.uxSend("wizard:orb", ["action": "toggle"]) { [weak self] state in
                guard let self else { return }
                // Wizard UX answered (voice / sent / busy / none): it owns the outcome.
                if let state { MeetingLog.log("orb (bridge): \(state)"); return }
                self.controller.web.evaluateJavaScript(legacy) { r, _ in
                    let res = (r as? String) ?? "none"
                    MeetingLog.log("orb (legacy): \(res)")
                    if res == "none" { retry() }
                }
            }
        }
        _ = o
        attempt()
    }

    // MARK: Wizard key, search, menu bar

    /// Origin of the Wizard this window is showing (the place views like /meetings/ live).
    var wizardOrigin: URL? {
        let base = controller.web.url ?? Store.active.flatMap { URL(string: $0.url) }
        guard let u = base, let scheme = u.scheme, let host = u.host, ["http", "https"].contains(scheme) else { return nil }
        var c = URLComponents(); c.scheme = scheme; c.host = host; c.port = u.port
        return c.url
    }

    func installWizardKey() {
        statusActions.statusLine = { [weak self] in self?.statusLine() ?? "" }
        statusActions.isLocal = { Store.active?.kind == .thisMac }
        statusActions.open = { [weak self] path in self?.openView(path) }
        statusActions.show = { [weak self] in self?.showMainWindow() }
        statusActions.quit = { if Store.active?.kind == .thisMac { HostControl.send("quit") }; NSApp.terminate(nil) }
        statusActions.toggleVoice = { VoiceKeys.enabled.toggle(); VoiceKeys.shared.install(prompt: VoiceKeys.enabled) }
        statusMenu.install(statusActions)

        let search = WizardSearch.shared
        search.origin = { [weak self] in self?.wizardOrigin }
        search.onOpen = { [weak self] path in self?.openView(path) }
        WizardBindings.onChange = { search.rebuildCatalog(apps: []); search.refreshApps() }

        let key = WizardKey.shared
        key.onTap = { WizardSearch.shared.toggle() }
        key.onChord = { [weak self] c in
            if c == " " { WizardSearch.shared.toggle(); return }
            if let b = WizardBindings.current.first(where: { $0.key == String(c) }), let p = b.open { self?.openView(p) }
        }
        key.install()
        if CapsLockRemap.enabled { CapsLockRemap.install() }

        WizardBindings.refresh(origin: wizardOrigin)
        bindingsTimer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { [weak self] _ in
            WizardBindings.refresh(origin: self?.wizardOrigin)
        }
    }

    func statusLine() -> String {
        guard let b = Store.active else { return "Wizard isn't set up yet" }
        if b.kind == .remote { return "Connected to \(b.name)" }
        guard let d = try? Data(contentsOf: WizardShared.statusFile),
              let s = try? JSONSerialization.jsonObject(with: d) as? [String: Any], let state = s["state"] as? String else {
            return "Wizard OS on this Mac"
        }
        switch state {
        case "running": return "Wizard is running on this Mac"
        case "starting": return "Wizard OS is starting…"
        case "stopped": return "Wizard OS is stopped"
        case "notInstalled": return "Wizard OS is not installed"
        case "stopping": return "Wizard OS is shutting down…"
        default: return "Wizard OS hit a problem — see logs"
        }
    }

    func showMainWindow() {
        NSApp.setActivationPolicy(.regular)
        controller.showWindow(nil)
        controller.window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Open a Wizard view (path on the Wizard's own origin) in the main window.
    func openView(_ path: String) {
        guard let origin = wizardOrigin, let url = URL(string: path, relativeTo: origin)?.absoluteURL,
              url.host == origin.host else { return }
        showMainWindow()
        // Wizard UX opens it as a window on its desktop; anything else navigates the page.
        controller.uxSend("wizard:open", ["path": path]) { [weak self] r in
            if r == nil { self?.controller.load(url) }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { showMainWindow() }
        return true
    }

    // Closing the window keeps Wizard in the menu bar (Wizard key, search, meeting detection keep working).
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func windowWillClose(_ notification: Notification) {
        DispatchQueue.main.async { NSApp.setActivationPolicy(.accessory) }
    }
    func applicationWillTerminate(_ notification: Notification) {
        // Leave the keyboard as we found it when Wizard isn't running.
        if CapsLockRemap.active { CapsLockRemap.remove() }
        // Chunks already on disk upload at next launch; flush the current partial chunk now.
        if let s = MeetingRecorder.shared.session { s.me.stop(); s.them?.stop(); MeetingSpool.shared.markDone(s.meetingId) }
    }

    func buildMenus() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Wizard", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Wizard", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Wizard", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu

        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit

        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "View")
        view.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r").target = self
        view.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        view.items.last?.keyEquivalentModifierMask = [.command, .control]
        viewItem.submenu = view

        let wizItem = NSMenuItem(); main.addItem(wizItem)
        wizItem.submenu = wizardsMenu
        rebuildWizardMenu()

        let winItem = NSMenuItem(); main.addItem(winItem)
        let win = NSMenu(title: "Window")
        win.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        winItem.submenu = win
        NSApp.windowsMenu = win
        NSApp.mainMenu = main
    }

    func rebuildWizardMenu() {
        wizardsMenu.removeAllItems()
        for (i, b) in Store.backends.enumerated() {
            let item = NSMenuItem(title: b.name, action: #selector(switchBackend(_:)), keyEquivalent: i < 9 ? "\(i + 1)" : "")
            item.tag = i; item.target = self
            item.state = (i == Store.activeIndex) ? .on : .off
            wizardsMenu.addItem(item)
        }
        if !Store.backends.isEmpty { wizardsMenu.addItem(.separator()) }
        wizardsMenu.addItem(withTitle: "Run Wizard on This Mac", action: #selector(addThisMac), keyEquivalent: "").target = self
        wizardsMenu.addItem(withTitle: "Connect to Another Computer…", action: #selector(addRemote), keyEquivalent: "").target = self
        wizardsMenu.addItem(withTitle: "Install Wizard OS from File…", action: #selector(installFromFile), keyEquivalent: "").target = self
        wizardsMenu.addItem(.separator())
        wizardsMenu.addItem(withTitle: "Restart Wizard OS on This Mac", action: #selector(restartLocal), keyEquivalent: "").target = self
    }

    // QA hooks (only when `defaults write org.humanitylabs.wizard QAHooks -bool true`).
    func installQAHooks() {
        guard UserDefaults.standard.bool(forKey: "QAHooks") else { return }
        DistributedNotificationCenter.default().addObserver(self, selector: #selector(qa(_:)),
            name: Notification.Name("org.humanitylabs.wizard.qa"), object: nil, suspensionBehavior: .deliverImmediately)
    }

    @objc func qa(_ n: Notification) {
        guard let cmd = n.object as? String else { return }
        let parts = cmd.split(separator: " ", maxSplits: 1).map(String.init)
        let arg = parts.count > 1 ? parts[1] : ""
        switch parts[0] {
        case "choose-this-mac": addThisMac()
        case "choose-this-mac-offline":
            // Simulate a Mac that can't reach the download feed.
            UserDefaults.standard.set("http://127.0.0.1:9/none.json", forKey: "osFeedURL"); addThisMac()
        case "install-file":
            // Same path as "Choose Wizard OS File…" after the user picks a file.
            controller.showOverlay("Setting up Wizard on this Mac", "Checking \(URL(fileURLWithPath: arg).lastPathComponent)…", progress: nil)
            controller.installer.install(from: URL(fileURLWithPath: arg))
        case "connect":
            var list = Store.backends.filter { $0.url != arg }
            list.append(Backend(kind: .remote, name: URL(string: arg)?.host ?? arg, url: arg))
            Store.backends = list; Store.activeIndex = list.count - 1; rebuildWizardMenu(); controller.begin()
        case "switch": Store.activeIndex = Int(arg) ?? 0; rebuildWizardMenu(); controller.begin()
        case "eval":
            controller.web.evaluateJavaScript(arg) { r, e in
                let s = e.map { "ERROR \($0)" } ?? String(describing: r ?? "nil")
                try? s.write(toFile: "/tmp/wizard-qa-eval.txt", atomically: true, encoding: .utf8)
            }
        case "snapshot": snapshot(to: arg.isEmpty ? "/tmp/wizard-qa.png" : arg)
        case "search": WizardSearch.shared.show(); if !arg.isEmpty { WizardSearch.shared.field.stringValue = arg; WizardSearch.shared.filter() }
        case "search-open": WizardSearch.shared.openSelected()
        case "search-snapshot":
            let p = WizardSearch.shared.panel
            if let v = p.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) {
                v.cacheDisplay(in: v.bounds, to: rep)
                try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: arg.isEmpty ? "/tmp/wizard-qa-search.png" : arg))
            }
        case "wizard-key": // simulate the physical key path: down, optional chord letter, up
            WizardKey.shared.handle(id: 1, pressed: true)
            if let c = arg.first {
                let id = UInt32(100 + (Array(WizardBindings.keyCodes.keys).firstIndex(of: c) ?? 0))
                WizardKey.shared.handle(id: id, pressed: true)
            }
            WizardKey.shared.handle(id: 1, pressed: false)
        case "close-window": controller.window?.performClose(nil)
        case "ux-state":
            controller.uxState { ux in
                let s: [String: Any] = ["wizardUX": ux ?? NSNull(), "url": self.controller.web.url?.absoluteString ?? "",
                                        "home": self.controller.homeURL?.absoluteString ?? ""]
                if let d = try? JSONSerialization.data(withJSONObject: s, options: .prettyPrinted) { try? d.write(to: URL(fileURLWithPath: "/tmp/wizard-qa-ux.json")) }
            }
        case "ux-open": openView(arg)
        case "ux-dictation":
            controller.uxSend("wizard:dictation", ["text": arg]) { r in try? (r ?? "nil").write(toFile: "/tmp/wizard-qa-dictation.txt", atomically: true, encoding: .utf8) }
        case "meeting-new": recordNew(title: arg.isEmpty ? "QA meeting" : arg, eventId: nil)
        case "meeting-stop": MeetingRecorder.shared.stop(finalize: true) { s in
            if let d = try? JSONSerialization.data(withJSONObject: s, options: .prettyPrinted) { try? d.write(to: URL(fileURLWithPath: "/tmp/wizard-qa-meeting-stop.json")) } }
        case "meeting-note": MeetingRecorder.shared.addNote(arg)
        case "meeting-expand": RecorderPanel.shared.expand()
        case "meeting-prompt": CallDetector.shared.prompt(arg.isEmpty ? "Call in Zoom" : arg, eventId: nil)
        case "meeting-prompt-record": CallPrompt.shared.record()
        case "voice-tap": VoiceKeys.shared.tap(arg == "cmd" ? VoiceKeys.rightCommand : VoiceKeys.rightOption)
        case "voice-enable": VoiceKeys.enabled = arg != "off"; VoiceKeys.shared.install(prompt: false)
        case "panel-snapshot":
            // panel-snapshot <recorder|prompt|hud> <png>
            let a = arg.split(separator: " ", maxSplits: 1).map(String.init)
            let p: NSPanel = a.first == "prompt" ? CallPrompt.shared.panel : a.first == "hud" ? VoiceHUD.shared.panel : RecorderPanel.shared.panel
            if let v = p.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) {
                v.cacheDisplay(in: v.bounds, to: rep)
                try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: a.count > 1 ? a[1] : "/tmp/wizard-qa-panel.png"))
            }
        case "meeting-state":
            var s: [String: Any] = MeetingRecorder.shared.status()
            s["recorderVisible"] = RecorderPanel.shared.panel.isVisible
            s["detector"] = CallDetector.shared.state
            s["voice"] = VoiceKeys.shared.state
            s["hudVisible"] = VoiceHUD.shared.panel.isVisible
            s["spoolPending"] = MeetingSpool.shared.pendingTotal
            s["micAuth"] = AVCaptureDevice.authorizationStatus(for: .audio).rawValue
            s["url"] = controller.web.url?.absoluteString ?? ""
            if let d = try? JSONSerialization.data(withJSONObject: s, options: .prettyPrinted) {
                try? d.write(to: URL(fileURLWithPath: "/tmp/wizard-qa-meeting.json"))
            }
        case "keys-state":
            let s: [String: Any] = [
                "triggerRegistered": WizardKey.shared.registered, "capsRemapActive": CapsLockRemap.active,
                "bindings": WizardBindings.current.map { "\($0.key)=\($0.open ?? "")" },
                "searchVisible": WizardSearch.shared.panel.isVisible,
                "searchResults": WizardSearch.shared.results.prefix(8).map { $0.title },
                "statusMenu": statusMenu.titles(), "statusItemVisible": statusMenu.item.isVisible,
                "activationPolicy": NSApp.activationPolicy().rawValue, "windowVisible": controller.window?.isVisible ?? false,
                "url": controller.web.url?.absoluteString ?? ""]
            if let d = try? JSONSerialization.data(withJSONObject: s, options: .prettyPrinted) {
                try? d.write(to: URL(fileURLWithPath: "/tmp/wizard-qa-keys.json"))
            }
        case "state":
            let s: [String: Any] = ["overlayHidden": controller.overlay.isHidden, "title": controller.title.stringValue,
                                    "subtitle": controller.subtitle.stringValue, "url": controller.web.url?.absoluteString ?? "",
                                    "loadedAt": controller.loadedAt?.timeIntervalSince1970 ?? 0,
                                    "frame": NSStringFromRect(controller.window?.frame ?? .zero),
                                    "backends": Store.backends.map { $0.name }, "active": Store.activeIndex]
            if let d = try? JSONSerialization.data(withJSONObject: s, options: .prettyPrinted) {
                try? d.write(to: URL(fileURLWithPath: "/tmp/wizard-qa-state.json"))
            }
        default: break
        }
    }

    func snapshot(to path: String) {
        let write: (NSImage) -> Void = { img in
            guard let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                  let png = rep.representation(using: .png, properties: [:]) else { return }
            try? png.write(to: URL(fileURLWithPath: path))
        }
        if controller.overlay.isHidden {
            controller.web.takeSnapshot(with: nil) { img, _ in if let img { write(img) } }
        } else if let v = controller.window?.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) {
            v.cacheDisplay(in: v.bounds, to: rep)
            let img = NSImage(size: v.bounds.size); img.addRepresentation(rep); write(img)
        }
    }

    @objc func reload() { controller.begin() }
    @objc func switchBackend(_ sender: NSMenuItem) { Store.activeIndex = sender.tag; rebuildWizardMenu(); controller.begin() }
    @objc func installFromFile() {
        var list = Store.backends.filter { $0.kind != .thisMac }
        list.insert(Backend(kind: .thisMac, name: "This Mac", url: WizardShared.localSetupURL.absoluteString), at: 0)
        Store.backends = list; Store.activeIndex = 0; rebuildWizardMenu()
        controller.chooseOSFile()
    }
    @objc func addThisMac() { controller.chooseThisMac(); rebuildWizardMenu() }
    @objc func addRemote() { controller.chooseRemote(); rebuildWizardMenu() }
    @objc func restartLocal() { HostControl.send("restart"); DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.controller.begin() } }
}

let app = NSApplication.shared
let appDelegate = AppDelegate()
app.delegate = appDelegate
app.setActivationPolicy(.regular)
app.run()
