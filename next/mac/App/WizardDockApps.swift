import AppKit
import CoreServices
import CryptoKit
import WebKit

/// Every Wizard app as its own Dock icon (try-wizard#147), the Mac side of the shell's existing Add to home screen.
///
/// The shell (wizard-ux core/home-screen-apps.js) talks to `window.wizardHomeScreenPort`, the port the Android app
/// gives it. `portJS` below gives the Mac's main window the same port; its messages reach `answer` through the one
/// native bridge (`dock.message`), which admits only the trusted shell's main document. The ops are the Android ones:
/// status, pin (a fresh click only), pinned (which of these apps have an icon) and refresh (new name/icon from the
/// shell, sent on every shell load, so a WizardOS update redraws every icon by itself). A pin writes a launcher bundle
/// in ~/Applications/Wizard Apps/ and puts it in the Dock; clicking it opens `wizard://app/<id>`, which WizardAppWindows
/// shows on the shell's one-app page in its own window. Pure rules: Shared/DockApps.swift.
@MainActor final class WizardDockApps {
    static let shared = WizardDockApps()
    typealias Rule = WizardDockAppsRule

    /// Main window only, at document start, after the meeting adapter (it chains `wizardNativeReply`). Tested in
    /// Tests/test_dock_apps.py under Node: the port, its replies, Add to Dock wording and right-click.
    static let portJS = #"""
    (() => {
      'use strict';
      const mac = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.wizardNative;
      if (!mac || window.wizardHomeScreenPort) return;
      // A one-app window never offers Add to Dock (the Android port refuses pinned-session callers too).
      try { if (new URLSearchParams(location.search).has('app-session')) return; } catch (_) { return; }
      let seq = 0; const waiting = new Set();
      const port = {
        onmessage: null,
        postMessage(data) {
          if (typeof data !== 'string' || data.length > 100000) return;
          const id = 'dock-' + (++seq); waiting.add(id);
          try { mac.postMessage({ id, method: 'dock.message', params: { data } }); } catch (_) { waiting.delete(id); }
        }
      };
      const prevReply = window.wizardNativeReply;
      window.wizardNativeReply = msg => {
        let m = msg; try { if (typeof m === 'string') m = JSON.parse(m); } catch (_) {}
        if (m && typeof m.id === 'string' && m.id.startsWith('dock-')) {
          if (waiting.delete(m.id) && typeof m.result === 'string' && typeof port.onmessage === 'function') { try { port.onmessage({ data: m.result }); } catch (_) {} }
          return;
        }
        if (typeof prevReply === 'function') return prevReply(msg);
      };
      Object.defineProperty(window, 'wizardHomeScreenPort', { value: port, configurable: false, writable: false });
      // The shell's sheet says "home screen"; on a Mac the icon goes in the Dock.
      const WORDS = { 'Add to home screen': 'Add to Dock', 'Already on home screen': 'Already in the Dock', 'Added to home screen': 'Added to the Dock' };
      function dockWords(sheet) {
        const fix = () => {
          for (const b of sheet.querySelectorAll('button')) { const to = WORDS[b.textContent]; if (to) b.textContent = to; }
          const label = sheet.getAttribute('aria-label') || '';
          if (label.endsWith(' home screen')) sheet.setAttribute('aria-label', label.slice(0, -' home screen'.length) + ' Dock');
        };
        fix();
        new MutationObserver(fix).observe(sheet, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['aria-label'] });
      }
      function watch() {
        if (!document.body) return;
        new MutationObserver(list => {
          for (const r of list) for (const n of r.addedNodes) {
            const sheet = n && n.nodeType === 1 && n.classList && n.classList.contains('home-pin-backdrop') ? n.querySelector('.home-pin-sheet') : null;
            if (sheet) dockWords(sheet);
          }
        }).observe(document.body, { childList: true });
      }
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', watch, { once: true }); else watch();
      // Right-click an app in the launcher (the Home apps row, ⌘O's app tiles, ⌘K's app results): the shell's own
      // Add to home screen sheet, answered here with a Dock icon. Anything else keeps its normal right-click.
      function appAt(target) {
        const reg = window.WizCore && window.WizCore.apps && window.WizCore.apps('mobile');
        if (!reg || !target || typeof target.closest !== 'function') return null;
        const tile = target.closest('.home [data-app], #launcher [data-app], .new-desk [data-app], .app-chip[data-app]');
        if (tile) return (reg.APP || {})[tile.dataset.app] || null;
        const pal = target.closest('#palList .pal-app, #palList .pal-it');
        const name = pal ? (pal.getAttribute('title') || '').split(' · ')[0].trim() : '';
        if (!name) return null;
        const hits = Object.values(reg.APP || {}).filter(a => a && a.name === name);
        return hits.length === 1 ? hits[0] : null;
      }
      document.addEventListener('contextmenu', e => {
        const H = window.WizHomeScreenApps;
        if (!e.isTrusted || !H || typeof H.offer !== 'function') return;
        const a = appAt(e.target);
        if (!a || !H.canOffer(a)) return;
        e.preventDefault(); e.stopPropagation();
        H.offer(a);
      }, true);
    })();
    """#

    /// ~/Applications/Wizard Apps (Launchpad and Spotlight list ~/Applications).
    var folder: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications", isDirectory: true)
            .appendingPathComponent(Rule.folderName, isDirectory: true)
    }
    /// Apps ticked in Add Apps to Dock… that wait for their icon from the shell's next refresh.
    private var wanted: Set<String> = []
    private var lastUserAction = Date.distantPast
    private var monitor: Any?
    private weak var mainWindow: NSWindow?

    /// A pin needs a click or key press in the main window just before it (the shell also checks the page's own
    /// user activation), so a page can never add icons by itself.
    func install(window: NSWindow) {
        mainWindow = window
        guard monitor == nil else { return }
        monitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseUp, .keyDown]) { [weak self] event in
            if let self, event.window != nil, event.window === self.mainWindow { self.lastUserAction = Date() }
            return event
        }
    }

    // MARK: The port (dock.message from the trusted shell's main document)

    func answer(_ raw: String, reply: @escaping (Any?) -> Void) {
        guard raw.utf8.count <= Rule.maxMessage, let data = raw.data(using: .utf8),
              let msg = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let request = msg["requestId"] as? String, Rule.validRequestId(request),
              let op = msg["op"] as? String else { reply(nil); return }
        func send(_ status: String, _ extra: [String: Any] = [:]) {
            var out: [String: Any] = ["requestId": request, "status": status]
            extra.forEach { out[$0.key] = $0.value }
            let json = (try? JSONSerialization.data(withJSONObject: out)).flatMap { String(data: $0, encoding: .utf8) }
            reply(json)
        }
        if op == "pinned" {
            guard let candidates = msg["candidates"] as? [String], candidates.count <= Rule.maxCandidates,
                  candidates.allSatisfy(Rule.validId) else { reply(nil); return }
            let have = Set(launchers().keys).union(wanted)
            var seen = Set<String>()
            send("pinned-list", ["appIds": candidates.filter { have.contains($0) && seen.insert($0).inserted }])
            return
        }
        guard let app = msg["appId"] as? String, Rule.validId(app) else { reply(nil); return }
        switch op {
        case "status":
            send(launchers()[app].map { self.inDock($0) } == true ? "pinned" : "ready")
        case "refresh":
            let exists = launchers()[app] != nil
            guard exists || wanted.contains(app) else { send("ready"); return }
            guard let result = write(app, name: msg["name"] as? String ?? "", icon: msg["icon"] as? String ?? "") else {
                wanted.remove(app); send("error"); return
            }
            if wanted.remove(app) != nil { addToDock(result.url) }
            send(result.changed ? "updated" : "unchanged")
        case "pin":
            guard Date().timeIntervalSince(lastUserAction) < 3, mainWindow?.isKeyWindow == true,
                  let result = write(app, name: msg["name"] as? String ?? "", icon: msg["icon"] as? String ?? "") else {
                send("error"); return
            }
            addToDock(result.url)
            send("confirmed")
        case "pin-widget":
            send("unsupported")
        default:
            reply(nil)
        }
    }

    // MARK: Launcher bundles

    /// Every launcher WizardOS made, by app id (read from each bundle's own Info.plist).
    func launchers() -> [String: URL] {
        var out: [String: URL] = [:]
        let items = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
        for url in items where url.pathExtension == "app" {
            guard let plist = NSDictionary(contentsOf: url.appendingPathComponent("Contents/Info.plist")),
                  let id = plist[Rule.appIdKey] as? String, Rule.validId(id) else { continue }
            out[id] = url
        }
        return out
    }

    func launcherName(_ appId: String) -> String? {
        launchers()[appId].map { $0.deletingPathExtension().lastPathComponent }
    }

    /// Writes (or refreshes) the launcher for `appId`. Changed is false when name and icon were already the same.
    private func write(_ appId: String, name raw: String, icon: String) -> (url: URL, changed: Bool)? {
        guard let name = Rule.cleanName(raw, appId: appId), let png = Rule.iconPNG(icon),
              let entries = Self.iconEntries(png), let script = Rule.launchScript(appId: appId) else { return nil }
        let sha = png.sha256Hex
        let fm = FileManager.default
        let all = launchers()
        let taken = Set(all.filter { $0.key != appId }.map { $0.value.lastPathComponent.lowercased() })
        let target = folder.appendingPathComponent(Rule.bundleName(name: name, appId: appId, takenByOthers: taken), isDirectory: true)
        let old = all[appId]
        if let old, old.lastPathComponent == target.lastPathComponent,
           (NSDictionary(contentsOf: old.appendingPathComponent("Contents/Info.plist"))?[Rule.iconKey] as? String) == sha {
            return (old, false)
        }
        do {
            try fm.createDirectory(at: folder, withIntermediateDirectories: true)
            if let old, old.lastPathComponent != target.lastPathComponent {
                // Renamed in the shell: move the launcher and keep its place in the Dock.
                if fm.fileExists(atPath: target.path) { try fm.removeItem(at: target) }
                try fm.moveItem(at: old, to: target)
                replaceInDock(old, with: target)
            }
            let contents = target.appendingPathComponent("Contents", isDirectory: true)
            let macos = contents.appendingPathComponent("MacOS", isDirectory: true)
            let resources = contents.appendingPathComponent("Resources", isDirectory: true)
            try fm.createDirectory(at: macos, withIntermediateDirectories: true)
            try fm.createDirectory(at: resources, withIntermediateDirectories: true)
            let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1"
            let plist = try PropertyListSerialization.data(fromPropertyList: Rule.infoPlist(appId: appId, name: name, version: version, iconSHA: sha),
                                                           format: .xml, options: 0)
            try plist.write(to: contents.appendingPathComponent("Info.plist"), options: .atomic)
            let launch = macos.appendingPathComponent("launch")
            try Data(script.utf8).write(to: launch, options: .atomic)
            try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: launch.path)
            let icns = Rule.icns(entries)
            try icns.write(to: resources.appendingPathComponent("AppIcon.icns"), options: .atomic)
            // Finder, the Dock and Launchpad keep icons cached: a custom icon and a fresh registration show the new one.
            if let image = NSImage(data: icns) { NSWorkspace.shared.setIcon(image, forFile: target.path, options: []) }
            try? fm.setAttributes([.modificationDate: Date()], ofItemAtPath: target.path)
            LSRegisterURL(target as CFURL, true)
            NSWorkspace.shared.noteFileSystemChanged(target.path)
            return (target, true)
        } catch {
            NSLog("Wizard: Dock app %@ not written: %@", appId, error.localizedDescription)
            return nil
        }
    }

    func remove(_ appId: String) {
        wanted.remove(appId)
        guard let url = launchers()[appId] else { return }
        removeFromDock(url)
        try? FileManager.default.removeItem(at: url)
    }

    /// The shell's square icon as a Mac icon (rounded tile on the standard grid), at every size the .icns carries.
    static func iconEntries(_ png: Data) -> [(type: String, png: Data)]? {
        guard let source = NSBitmapImageRep(data: png), (48...256).contains(source.pixelsWide),
              (48...256).contains(source.pixelsHigh) else { return nil }
        let image = NSImage(size: NSSize(width: source.pixelsWide, height: source.pixelsHigh))
        image.addRepresentation(source)
        var out: [(type: String, png: Data)] = []
        for (type, px) in WizardDockAppsRule.iconSizes {
            guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                                             samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                             bytesPerRow: 0, bitsPerPixel: 0) else { return nil }
            rep.size = NSSize(width: px, height: px)
            guard let context = NSGraphicsContext(bitmapImageRep: rep) else { return nil }
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = context
            context.imageInterpolation = .high
            let side = CGFloat(px), inset = side * WizardDockAppsRule.iconInset
            let rect = NSRect(x: inset, y: inset, width: side - 2 * inset, height: side - 2 * inset)
            let radius = rect.width * WizardDockAppsRule.iconCorner
            NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius).addClip()
            image.draw(in: rect, from: .zero, operation: .copy, fraction: 1)
            NSGraphicsContext.restoreGraphicsState()
            guard let data = rep.representation(using: .png, properties: [:]) else { return nil }
            out.append((type, data))
        }
        return out
    }

    // MARK: The Dock

    private let dockDomain = "com.apple.dock" as CFString
    private let dockKey = "persistent-apps" as CFString
    private var dockRestart: DispatchWorkItem?

    private func dockApps() -> [[String: Any]] {
        CFPreferencesAppSynchronize(dockDomain)
        return (CFPreferencesCopyAppValue(dockKey, dockDomain) as? [[String: Any]]) ?? []
    }
    private func saveDock(_ apps: [[String: Any]]) {
        CFPreferencesSetAppValue(dockKey, apps as CFArray, dockDomain)
        CFPreferencesAppSynchronize(dockDomain)
        restartDockSoon()
    }
    func inDock(_ bundle: URL) -> Bool { Rule.dockIndex(of: bundle, in: dockApps()) != nil }
    func addToDock(_ bundle: URL) {
        var apps = dockApps()
        guard Rule.dockIndex(of: bundle, in: apps) == nil else { return }
        apps.append(Rule.dockEntry(for: bundle))
        saveDock(apps)
    }
    func removeFromDock(_ bundle: URL) {
        var apps = dockApps()
        guard let i = Rule.dockIndex(of: bundle, in: apps) else { return }
        apps.remove(at: i)
        saveDock(apps)
    }
    private func replaceInDock(_ old: URL, with new: URL) {
        var apps = dockApps()
        guard let i = Rule.dockIndex(of: old, in: apps) else { return }
        apps[i] = Rule.dockEntry(for: new)
        saveDock(apps)
    }
    /// The Dock reads its icons when it starts: one restart after a batch of changes (Add all adds many at once).
    private func restartDockSoon() {
        dockRestart?.cancel()
        let work = DispatchWorkItem {
            let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/killall"); p.arguments = ["Dock"]
            try? p.run()
        }
        dockRestart = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2, execute: work)
    }

    // MARK: Add Apps to Dock… (every installed app, ticked; one button adds them all)

    func chooseApps(from controller: WizardWindowController) {
        let js = """
        try { await (window.WizCore && window.WizCore.appsLoaded && window.WizCore.appsLoaded()); } catch (_) {}
        const H = window.WizHomeScreenApps, P = window.WizHomeScreenPolicy, reg = window.WizCore && window.WizCore.apps && window.WizCore.apps('mobile');
        if (!H || !P || !reg || !window.wizardHomeScreenPort) return '';
        const seen = new Set();
        return JSON.stringify(Object.values(reg.APP || {}).filter(a => a && H.canOffer(a) && !seen.has(a.id) && seen.add(a.id))
          .map(a => ({ id: String(a.id), name: String(P.displayName(a) || a.name || a.id) })));
        """
        guard controller.isTrustedDocument else { notReady(controller.window); return }
        controller.web.callAsyncJavaScript(js, arguments: [:], in: nil, in: .page) { [weak self, weak controller] result in
            guard let self, let controller else { return }
            guard case .success(let value) = result, let text = value as? String, !text.isEmpty,
                  let list = (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [[String: String]] else {
                self.notReady(controller.window); return
            }
            let apps = list.compactMap { d -> (id: String, name: String)? in
                guard let id = d["id"], Rule.validId(id), let name = d["name"] else { return nil }
                return (id, name)
            }.prefix(Rule.maxCandidates)
            self.showChooser(Array(apps), controller: controller)
        }
    }

    private func notReady(_ window: NSWindow?) {
        let a = NSAlert()
        a.messageText = "Your Wizard isn't open yet"
        a.informativeText = "Open WizardOS and wait for your apps to show, then try Add Apps to Dock again."
        if let window { a.beginSheetModal(for: window) } else { a.runModal() }
    }

    private func showChooser(_ apps: [(id: String, name: String)], controller: WizardWindowController) {
        guard !apps.isEmpty else { notReady(controller.window); return }
        let alert = NSAlert()
        alert.messageText = "Add Apps to Dock"
        alert.informativeText = "Each ticked app gets its own icon in the Dock and in Launchpad › Wizard Apps. Untick an app to leave it out (or take its icon away)."
        alert.addButton(withTitle: "Add to Dock")
        alert.addButton(withTitle: "Cancel")
        let rowHeight: CGFloat = 24, width: CGFloat = 300
        let list = NSView(frame: NSRect(x: 0, y: 0, width: width, height: rowHeight * CGFloat(apps.count)))
        var boxes: [(String, NSButton)] = []
        for (i, app) in apps.enumerated() {
            let box = NSButton(checkboxWithTitle: app.name, target: nil, action: nil)
            box.state = .on
            box.frame = NSRect(x: 4, y: list.frame.height - rowHeight * CGFloat(i + 1), width: width - 8, height: rowHeight)
            list.addSubview(box)
            boxes.append((app.id, box))
        }
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: width, height: min(list.frame.height, 320)))
        scroll.hasVerticalScroller = list.frame.height > 320
        scroll.drawsBackground = false
        scroll.documentView = list
        list.scroll(NSPoint(x: 0, y: list.frame.height))
        alert.accessoryView = scroll
        let run: (NSApplication.ModalResponse) -> Void = { [weak self, weak controller] answer in
            guard let self, let controller, answer == .alertFirstButtonReturn else { return }
            let existing = self.launchers()
            for (id, box) in boxes {
                if box.state == .on { self.wanted.insert(id) } else if existing[id] != nil { self.remove(id) }
            }
            // Icons and names are the shell's: its refresh (the Android resume pass) hands them over for every app.
            controller.web.evaluateJavaScript("window.dispatchEvent(new Event('wos-native-resume'))")
        }
        if let window = controller.window { alert.beginSheetModal(for: window, completionHandler: run) } else { run(alert.runModal()) }
    }
}

private extension Data {
    var sha256Hex: String { SHA256.hash(data: self).map { String(format: "%02x", $0) }.joined() }
}

// MARK: - One app in its own window

/// The window a Dock icon (or a link from another app's window) opens: the shell's one-app page for that app, signed in
/// with the main window's own website data. Links to another app open (or bring forward) that app's window; links to
/// Wizard's own pages go to the main window; other addresses open in the Mac's browser.
@MainActor final class WizardAppWindows {
    static let shared = WizardAppWindows()
    /// Where the one-app page lives (`…/wizard-os-home/`), nil while no Wizard is chosen.
    var home: () -> URL? = { nil }
    /// This Wizard's own `scheme://host:port` addresses (the shell, and on This Mac the installed apps' address).
    var boxOrigins: () -> Set<String> = { [] }
    var dataStore: () -> WKWebsiteDataStore = { .default() }
    var openShell: (String) -> Void = { _ in }
    var windowsChanged: () -> Void = {}
    private(set) var windows: [String: WizardAppWindow] = [:]
    /// The installed apps' address roots (id → path), read from a one-app page's own app list.
    var appRoots: [String: String] = [:]

    var anyVisible: Bool { windows.values.contains { $0.window?.isVisible == true } }

    func open(_ appId: String, path: String = "") {
        guard WizardDockAppsRule.validId(appId) else { return }
        NSApp.setActivationPolicy(.regular)
        if let w = windows[appId] {
            w.showWindow(nil); w.window?.makeKeyAndOrderFront(nil)
            if !path.isEmpty { w.go(path) }
        } else {
            let w = WizardAppWindow(appId: appId, name: WizardDockApps.shared.launcherName(appId) ?? appId)
            windows[appId] = w
            w.showWindow(nil); w.window?.makeKeyAndOrderFront(nil)
            w.start(path: path)
        }
        NSApp.activate(ignoringOtherApps: true)
        windowsChanged()
    }

    func closed(_ appId: String) {
        windows[appId] = nil
        windowsChanged()
    }

    var keyWindow: WizardAppWindow? { windows.values.first { $0.window?.isKeyWindow == true } }
}

@MainActor final class WizardAppWindow: NSWindowController, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    let appId: String
    let web: WKWebView
    private let overlay = NSView()
    private let message = NSTextField(labelWithString: "")
    private let spinner = NSProgressIndicator()
    private let retryButton = NSButton(title: "Try Again", target: nil, action: nil)
    private var session: URL?
    private var tries = 0
    private var probe: URLSessionDataTask?
    private var downloads = DownloadDestinations()

    init(appId: String, name: String) {
        self.appId = appId
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = WizardAppWindows.shared.dataStore()
        web = WKWebView(frame: .zero, configuration: cfg)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 740),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = name
        window.minSize = NSSize(width: 360, height: 480)
        window.backgroundColor = NSColor(calibratedRed: 0.06, green: 0.06, blue: 0.08, alpha: 1)
        window.appearance = NSAppearance(named: .darkAqua)
        window.isReleasedWhenClosed = false
        window.tabbingMode = .disallowed
        window.setFrameAutosaveName("WizardAppWindow-\(appId)")
        if !window.setFrameUsingName("WizardAppWindow-\(appId)") { window.center() }
        super.init(window: window)
        window.delegate = self
        web.navigationDelegate = self
        web.uiDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        web.allowsBackForwardNavigationGestures = false
        let root = NSView(); root.wantsLayer = true; root.layer?.backgroundColor = window.backgroundColor.cgColor
        window.contentView = root
        for v in [web, overlay] {
            v.translatesAutoresizingMaskIntoConstraints = false; root.addSubview(v)
            NSLayoutConstraint.activate([v.leadingAnchor.constraint(equalTo: root.leadingAnchor), v.trailingAnchor.constraint(equalTo: root.trailingAnchor),
                                         v.topAnchor.constraint(equalTo: root.topAnchor), v.bottomAnchor.constraint(equalTo: root.bottomAnchor)])
        }
        overlay.wantsLayer = true; overlay.layer?.backgroundColor = window.backgroundColor.cgColor
        spinner.style = .spinning; spinner.controlSize = .regular
        message.textColor = NSColor(calibratedWhite: 0.85, alpha: 1); message.alignment = .center
        retryButton.target = self; retryButton.action = #selector(retry); retryButton.bezelStyle = .rounded; retryButton.isHidden = true
        let stack = NSStackView(views: [spinner, message, retryButton]); stack.orientation = .vertical; stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false; overlay.addSubview(stack)
        NSLayoutConstraint.activate([stack.centerXAnchor.constraint(equalTo: overlay.centerXAnchor), stack.centerYAnchor.constraint(equalTo: overlay.centerYAnchor),
                                     stack.widthAnchor.constraint(lessThanOrEqualTo: overlay.widthAnchor, constant: -40)])
    }
    required init?(coder: NSCoder) { fatalError() }

    private func showState(_ text: String, spinning: Bool, retry: Bool = false) {
        overlay.isHidden = false; message.stringValue = text; retryButton.isHidden = !retry
        if spinning { spinner.isHidden = false; spinner.startAnimation(nil) } else { spinner.stopAnimation(nil); spinner.isHidden = true }
    }

    /// Shows Starting… until this Wizard answers (the VM may still be booting), then the app.
    func start(path: String) {
        guard let home = WizardAppWindows.shared.home(),
              let url = WizardDockAppsRule.sessionURL(home: home, appId: appId, path: path) else {
            showState("Set up WizardOS first, then open this app again.", spinning: false)
            WizardAppWindows.shared.openShell("")
            return
        }
        session = url; tries = 0
        showState("Starting \(window?.title ?? appId)…", spinning: true)
        waitThenLoad(url)
    }

    private func waitThenLoad(_ url: URL) {
        probe?.cancel()
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 4)
        req.httpMethod = "GET"
        probe = URLSession.shared.dataTask(with: req) { [weak self] _, resp, _ in
            let ok = (resp as? HTTPURLResponse).map { (200..<400).contains($0.statusCode) } ?? false
            DispatchQueue.main.async {
                guard let self, self.session == url else { return }
                if ok { self.web.load(URLRequest(url: url)); return }
                self.tries += 1
                if self.tries > 180 {
                    self.showState("Your Wizard didn't answer.", spinning: false, retry: true); return
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in
                    guard let self, self.session == url else { return }
                    self.waitThenLoad(url)
                }
            }
        }
        probe?.resume()
    }

    @objc func retry() { start(path: "") }
    func reload() { if session != nil { start(path: "") } }

    /// A link to a page of this app while its window is open: the page goes there (wizard-ux `__wosSessionGo`).
    func go(_ path: String) {
        let js = "(typeof window.__wosSessionGo === 'function' ? window.__wosSessionGo(\(Self.jsString(path))) : false) === true"
        web.evaluateJavaScript(js) { [weak self] value, _ in
            if (value as? Bool) != true { self?.start(path: path) }
        }
    }

    static func jsString(_ s: String) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: [s])) ?? Data("[\"\"]".utf8)
        let arr = String(data: data, encoding: .utf8) ?? "[\"\"]"
        return String(arr.dropFirst().dropLast())
    }

    private func readAppRoots() {
        let js = """
        (() => { const reg = window.WizCore && window.WizCore.apps && window.WizCore.apps('mobile'), P = window.WizHomeScreenPolicy;
          if (!reg || !P) return '';
          const out = {};
          for (const a of reg.APPS || []) if (a && a.kind === 'wizard' && typeof a.url === 'string' && a.url && !P.isShell(a.url)) {
            try { out[a.id] = new URL(a.url, location.origin).pathname; } catch (_) {}
          }
          return JSON.stringify(out); })()
        """
        web.evaluateJavaScript(js) { value, _ in
            guard let s = value as? String, !s.isEmpty,
                  let roots = (try? JSONSerialization.jsonObject(with: Data(s.utf8))) as? [String: String], !roots.isEmpty else { return }
            WizardAppWindows.shared.appRoots = roots
        }
    }

    private func route(_ url: URL) -> WizardDockAppsRule.LinkRoute {
        WizardDockAppsRule.route(url, currentApp: appId, boxOrigins: WizardAppWindows.shared.boxOrigins(),
                                 appRoots: WizardAppWindows.shared.appRoots)
    }

    private func follow(_ r: WizardDockAppsRule.LinkRoute, _ url: URL) {
        switch r {
        case .otherApp(let id, let path): WizardAppWindows.shared.open(id, path: path)
        case .shell(let path): WizardAppWindows.shared.openShell(path)
        case .external: if ["http", "https", "mailto"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        case .stay: break
        }
    }

    // MARK: WKNavigationDelegate / WKUIDelegate

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.shouldPerformDownload { decisionHandler(.download); return }
        guard let url = action.request.url else { decisionHandler(.allow); return }
        let r = route(url)
        if action.targetFrame?.isMainFrame == true {
            // The window keeps its one app: only its own one-app page loads here.
            if let session, url.path == session.path,
               URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "app-session" })?.value == appId {
                decisionHandler(.allow); return
            }
            // A redirect or the app's own page stays; another app, Wizard's own pages and other sites go where they belong.
            if r == .stay { decisionHandler(.allow); return }
            decisionHandler(.cancel)
            follow(r, url)
            return
        }
        switch r {
        case .otherApp:
            decisionHandler(.cancel)
            follow(r, url)
            // A link sheet that started to open the other app closes again.
            web.evaluateJavaScript("(() => { try { const l = window.__wos && window.__wos.links; if (l && l.back) l.back(); } catch (_) {} return true; })()")
        case .external where action.navigationType == .linkActivated:
            decisionHandler(.cancel)
            follow(r, url)
        default:
            decisionHandler(.allow)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let disposition = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition") ?? ""
        decisionHandler(!response.canShowMIMEType || disposition.lowercased().hasPrefix("attachment") ? .download : .allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            let r = route(url)
            follow(r == .stay ? .external : r, url)
        }
        return nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        overlay.isHidden = true
        readAppRoots()
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in self?.readAppRoots() }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { failed(error) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { failed(error) }
    private func failed(_ error: Error) {
        let e = error as NSError
        if e.code == NSURLErrorCancelled || (e.domain == "WebKitErrorDomain" && e.code == 102) { return }
        showState("Couldn't open \(window?.title ?? appId): \(error.localizedDescription)", spinning: false, retry: true)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { reload() }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        guard let window else { completionHandler(nil); return }
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) }
    }

    // MARK: Downloads (to ~/Downloads, like the main window)

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let folder = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Downloads")
        completionHandler(downloads.reserve(for: ObjectIdentifier(download), suggestedFilename: suggestedFilename, folder: folder,
                                            fileExists: { (try? FileManager.default.attributesOfItem(atPath: $0)) != nil }))
    }

    // MARK: NSWindowDelegate

    func windowWillClose(_ notification: Notification) {
        probe?.cancel(); session = nil
        web.load(URLRequest(url: URL(string: "about:blank")!))
        WizardAppWindows.shared.closed(appId)
    }
}
