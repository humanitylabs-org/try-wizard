import AppKit
import Carbon

// Wizard key (Caps Lock as a Hyper key), Wizard search, and the bindings the Wizard can edit.
//
// Caps Lock is remapped to F18 with `hidutil` (user level, no admin, no Accessibility or
// Input Monitoring permission). Holding F18 temporarily registers Carbon hot keys for
// Space/letters/digits, so the chord only exists while the Wizard key is down. A tap with
// no chord opens Wizard search.

// MARK: - Bindings (defaults → the Wizard's file → this Mac's override)

struct WizardBinding: Codable, Equatable {
    var key: String
    var title: String
    var open: String?
}

private struct BindingsFile: Codable { var schema: Int?; var bindings: [WizardBinding] }

enum WizardBindings {
    static let defaults: [WizardBinding] = [
        WizardBinding(key: "c", title: "Chat", open: "/wizard/"),
        WizardBinding(key: "m", title: "Mizel — Meeting recorder", open: "/meetings/"),
        WizardBinding(key: "f", title: "Files", open: "/files/#/apps"),
    ]
    private(set) static var current: [WizardBinding] = defaults
    static var onChange: () -> Void = {}

    static var localFile: URL { WizardShared.supportDir.appendingPathComponent("keybindings.json") }
    static func remoteFile(_ origin: URL) -> URL { origin.appendingPathComponent("wizard-os/keybindings.json") }

    static func valid(_ b: WizardBinding) -> Bool {
        guard b.key.count == 1, let c = b.key.lowercased().first, keyCodes[c] != nil, c != " " else { return false }
        guard let open = b.open, open.hasPrefix("/"), !open.hasPrefix("//"), !open.contains("..") else { return false }
        return !b.title.isEmpty
    }

    static func merge(_ layers: [[WizardBinding]]) -> [WizardBinding] {
        var order: [String] = []; var byKey: [String: WizardBinding] = [:]
        for layer in layers {
            for var b in layer where valid(b) {
                b.key = b.key.lowercased()
                if byKey[b.key] == nil { order.append(b.key) }
                byKey[b.key] = b
            }
        }
        return order.compactMap { byKey[$0] }
    }

    static func decode(_ data: Data?) -> [WizardBinding] {
        guard let data, let f = try? JSONDecoder().decode(BindingsFile.self, from: data) else { return [] }
        return f.bindings
    }

    /// Refetch the Wizard's bindings. The local file is read synchronously so the Mac override always applies.
    private static var refreshGeneration: UInt64 = 0
    private static var selectedOrigin: URL?
    static func refresh(origin: URL?) {
        refreshGeneration &+= 1
        let generation = refreshGeneration
        let local = decode(try? Data(contentsOf: localFile))
        if selectedOrigin != origin {
            selectedOrigin = origin
            apply(merge([defaults, local])) // Never show the previous Wizard's bindings.
        }
        guard let origin else { apply(merge([defaults, local])); return }
        var req = URLRequest(url: remoteFile(origin), cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 5)
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200
            let remote = ok ? decode(data) : []
            DispatchQueue.main.async {
                guard generation == refreshGeneration else { return }
                apply(merge([defaults, remote, local]))
            }
        }.resume()
    }

    private static func apply(_ list: [WizardBinding]) {
        guard list != current else { return }
        current = list; onChange()
    }

    static let keyCodes: [Character: Int] = [
        "a": kVK_ANSI_A, "b": kVK_ANSI_B, "c": kVK_ANSI_C, "d": kVK_ANSI_D, "e": kVK_ANSI_E, "f": kVK_ANSI_F,
        "g": kVK_ANSI_G, "h": kVK_ANSI_H, "i": kVK_ANSI_I, "j": kVK_ANSI_J, "k": kVK_ANSI_K, "l": kVK_ANSI_L,
        "m": kVK_ANSI_M, "n": kVK_ANSI_N, "o": kVK_ANSI_O, "p": kVK_ANSI_P, "q": kVK_ANSI_Q, "r": kVK_ANSI_R,
        "s": kVK_ANSI_S, "t": kVK_ANSI_T, "u": kVK_ANSI_U, "v": kVK_ANSI_V, "w": kVK_ANSI_W, "x": kVK_ANSI_X,
        "y": kVK_ANSI_Y, "z": kVK_ANSI_Z, "0": kVK_ANSI_0, "1": kVK_ANSI_1, "2": kVK_ANSI_2, "3": kVK_ANSI_3,
        "4": kVK_ANSI_4, "5": kVK_ANSI_5, "6": kVK_ANSI_6, "7": kVK_ANSI_7, "8": kVK_ANSI_8, "9": kVK_ANSI_9,
        " ": kVK_Space,
    ]
}

// MARK: - Caps Lock → F18

enum CapsLockRemap {
    static let capsLock: UInt64 = 0x700000039
    static let f18: UInt64 = 0x70000006D
    static var enabled: Bool {
        get { UserDefaults.standard.object(forKey: "wizardKeyEnabled") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "wizardKeyEnabled"); newValue ? install() : remove() }
    }

    private static func run(_ args: [String]) -> String {
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/hidutil"); p.arguments = args
        let out = Pipe(); p.standardOutput = out; p.standardError = Pipe()
        do { try p.run() } catch { return "" }
        p.waitUntilExit()
        return String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    }

    /// Current user mappings as (src, dst) pairs. hidutil prints a plist-ish dictionary list.
    static func mappings() -> [(UInt64, UInt64)] {
        // hidutil prints an old-style plist: `HIDKeyboardModifierMappingDst = 30064771181;` on separate lines.
        let text = run(["property", "--get", "UserKeyMapping"])
        var pairs: [(UInt64, UInt64)] = []; var src: UInt64?; var dst: UInt64?
        func flush() { if let s = src, let d = dst { pairs.append((s, d)) }; src = nil; dst = nil }
        for raw in text.split(separator: "\n") {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("}") { flush(); continue }
            let parts = line.split(separator: "=", maxSplits: 1)
                .map { $0.trimmingCharacters(in: .whitespaces.union(CharacterSet(charactersIn: ";\""))) }
            guard parts.count == 2, let v = UInt64(parts[1]) else { continue }
            if parts[0].hasSuffix("MappingSrc") { src = v }
            if parts[0].hasSuffix("MappingDst") { dst = v }
        }
        flush()
        return pairs
    }

    private static func set(_ pairs: [(UInt64, UInt64)]) {
        let items = pairs.map { "{\"HIDKeyboardModifierMappingSrc\":\($0.0),\"HIDKeyboardModifierMappingDst\":\($0.1)}" }
        _ = run(["property", "--set", "{\"UserKeyMapping\":[\(items.joined(separator: ","))]}"])
    }

    static var active: Bool { mappings().contains { $0.0 == capsLock && $0.1 == f18 } }

    static func install() {
        var pairs = mappings().filter { $0.0 != capsLock }
        pairs.append((capsLock, f18)); set(pairs)
    }

    static func remove() { set(mappings().filter { !($0.0 == capsLock && $0.1 == f18) }) }
}

// MARK: - Wizard key chords (Carbon hot keys, no permissions)

final class WizardKey {
    static let shared = WizardKey()
    private let signature = OSType(0x57495A4B) // 'WIZK'
    private var triggerRef: EventHotKeyRef?
    private var chordRefs: [EventHotKeyRef] = []
    private var chordKeys: [UInt32: Character] = [:]
    private(set) var held = false
    private var usedChord = false
    private(set) var registered = false
    var onTap: () -> Void = {}
    var onChord: (Character) -> Void = { _ in }

    func install() {
        var specs = [EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
                     EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased))]
        InstallEventHandler(GetApplicationEventTarget(), { _, event, _ in
            var hk = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                              MemoryLayout<EventHotKeyID>.size, nil, &hk)
            let pressed = GetEventKind(event) == UInt32(kEventHotKeyPressed)
            WizardKey.shared.handle(id: hk.id, pressed: pressed)
            return noErr
        }, 2, &specs, nil, nil)
        let status = RegisterEventHotKey(UInt32(kVK_F18), 0, EventHotKeyID(signature: signature, id: 1),
                                         GetApplicationEventTarget(), 0, &triggerRef)
        registered = status == noErr
        NSLog("Wizard key: F18 trigger registered=%d", registered ? 1 : 0)
    }

    func handle(id: UInt32, pressed: Bool) {
        if id == 1 { pressed ? down() : up(); return }
        if pressed, let c = chordKeys[id] { usedChord = true; onChord(c) }
    }

    private var watchdog: Timer?

    func down() {
        guard !held else { return } // key repeat
        held = true; usedChord = false
        // Safety: if the release is ever missed, give the letters back after 10 s.
        watchdog?.invalidate()
        watchdog = Timer.scheduledTimer(withTimeInterval: 10, repeats: false) { [weak self] _ in self?.up() }
        var next: UInt32 = 100
        for (c, code) in WizardBindings.keyCodes {
            var ref: EventHotKeyRef?
            if RegisterEventHotKey(UInt32(code), 0, EventHotKeyID(signature: signature, id: next), GetApplicationEventTarget(), 0, &ref) == noErr,
               let ref { chordRefs.append(ref); chordKeys[next] = c }
            next += 1
        }
    }

    func up() {
        guard held else { return }
        held = false
        watchdog?.invalidate(); watchdog = nil
        chordRefs.forEach { UnregisterEventHotKey($0) }; chordRefs.removeAll(); chordKeys.removeAll()
        if !usedChord { onTap() }
    }
}

// MARK: - Wizard search (Spotlight-style panel)

struct SearchItem {
    var title: String
    var subtitle: String
    var key: String?
    var open: String
}

private final class KeyPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) { orderOut(nil) }
}

final class WizardSearch: NSObject, NSTextFieldDelegate, NSTableViewDataSource, NSTableViewDelegate {
    static let shared = WizardSearch()
    static let bg = NSColor(calibratedRed: 0.059, green: 0.063, blue: 0.078, alpha: 0.97)   // --bg #0f1014
    static let raised = NSColor(calibratedRed: 0.086, green: 0.090, blue: 0.114, alpha: 1)  // --bg-raised #16171d
    static let line = NSColor(calibratedRed: 0.137, green: 0.141, blue: 0.176, alpha: 1)    // --line #23242d
    static let text = NSColor(calibratedRed: 0.922, green: 0.925, blue: 0.949, alpha: 1)    // --text #ebecf2
    static let text2 = NSColor(calibratedRed: 0.651, green: 0.663, blue: 0.714, alpha: 1)   // --text-2 #a6a9b6
    static let wiz = NSColor(calibratedRed: 0.643, green: 0.545, blue: 0.980, alpha: 1)     // --wiz #a48bfa

    let panel: NSPanel
    let field = NSTextField()
    let table = NSTableView()
    private var catalog: [SearchItem] = []
    private(set) var results: [SearchItem] = []
    var onOpen: (String) -> Void = { _ in }
    var origin: () -> URL? = { nil }

    override init() {
        panel = KeyPanel(contentRect: NSRect(x: 0, y: 0, width: 640, height: 420),
                         styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        super.init()
        panel.isFloatingPanel = true
        panel.level = .modalPanel
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.isMovableByWindowBackground = true

        let root = NSView(); root.wantsLayer = true
        root.layer?.backgroundColor = WizardSearch.bg.cgColor
        root.layer?.cornerRadius = 16
        root.layer?.borderWidth = 1
        root.layer?.borderColor = WizardSearch.line.cgColor
        root.layer?.masksToBounds = true
        panel.contentView = root

        let badge = NSTextField(labelWithString: "⇪")
        badge.font = .systemFont(ofSize: 15, weight: .semibold); badge.textColor = WizardSearch.wiz
        field.placeholderAttributedString = NSAttributedString(string: "Search your Wizard",
            attributes: [.foregroundColor: WizardSearch.text2, .font: NSFont.systemFont(ofSize: 22, weight: .regular)])
        field.font = .systemFont(ofSize: 22, weight: .regular)
        field.textColor = WizardSearch.text
        field.isBordered = false; field.drawsBackground = false; field.focusRingType = .none
        field.delegate = self

        let sep = NSBox(); sep.boxType = .custom; sep.borderWidth = 0; sep.fillColor = WizardSearch.line

        let col = NSTableColumn(identifier: .init("item")); col.width = 600
        table.addTableColumn(col); table.headerView = nil
        table.backgroundColor = .clear; table.rowHeight = 46; table.intercellSpacing = NSSize(width: 0, height: 2)
        table.selectionHighlightStyle = .regular; table.style = .plain
        table.dataSource = self; table.delegate = self
        table.target = self; table.doubleAction = #selector(openSelected)
        let scroll = NSScrollView(); scroll.documentView = table; scroll.drawsBackground = false
        scroll.hasVerticalScroller = true; scroll.scrollerStyle = .overlay

        let hint = NSTextField(labelWithString: "↵ open    ⇪ + letter jumps straight there    esc close")
        hint.font = .systemFont(ofSize: 11); hint.textColor = WizardSearch.text2

        for v in [badge, field, sep, scroll, hint] as [NSView] { v.translatesAutoresizingMaskIntoConstraints = false; root.addSubview(v) }
        NSLayoutConstraint.activate([
            badge.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 20),
            badge.centerYAnchor.constraint(equalTo: field.centerYAnchor),
            field.leadingAnchor.constraint(equalTo: badge.trailingAnchor, constant: 10),
            field.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -20),
            field.topAnchor.constraint(equalTo: root.topAnchor, constant: 18),
            sep.leadingAnchor.constraint(equalTo: root.leadingAnchor), sep.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            sep.topAnchor.constraint(equalTo: field.bottomAnchor, constant: 14), sep.heightAnchor.constraint(equalToConstant: 1),
            scroll.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 8),
            scroll.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -8),
            scroll.topAnchor.constraint(equalTo: sep.bottomAnchor, constant: 6),
            scroll.bottomAnchor.constraint(equalTo: hint.topAnchor, constant: -6),
            hint.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 20),
            hint.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -10),
        ])
        rebuildCatalog()
    }

    // Catalog: the Wizard's bindings first, then every app the Wizard lists.
    func rebuildCatalog(apps: [SearchItem] = []) {
        var items = WizardBindings.current.compactMap { b in
            b.open.map { SearchItem(title: b.title, subtitle: "View", key: b.key, open: $0) }
        }
        let bound = Set(items.map { $0.open })
        items += apps.filter { !bound.contains($0.open) }
        catalog = items
        filter()
    }

    func workspaceChanged() {
        panel.orderOut(nil)
        field.stringValue = ""
        rebuildCatalog()
    }

    func refreshApps() {
        guard let origin = origin() else { return }
        var req = URLRequest(url: origin.appendingPathComponent("files/api/apps"), cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 5)
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        URLSession.shared.dataTask(with: req) { [weak self] data, resp, _ in
            guard (resp as? HTTPURLResponse)?.statusCode == 200, let data,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let apps = obj["apps"] as? [[String: Any]] else { return }
            let host = origin.host
            let items: [SearchItem] = apps.compactMap { a in
                guard let name = a["name"] as? String, let urlS = a["url"] as? String, let u = URL(string: urlS),
                      u.host == host, u.path.hasPrefix("/") else { return nil }
                // URL.path drops the trailing slash; keep the exact path so views dedupe against bindings.
                var open = URLComponents(url: u, resolvingAgainstBaseURL: false)?.percentEncodedPath ?? u.path
                if let f = u.fragment { open += "#" + f }
                let installed = (a["group"] as? String) == "installed"
                return SearchItem(title: name, subtitle: installed ? "App" : "Preview", key: nil, open: open)
            }.sorted { ($0.subtitle == "App" ? 0 : 1, $0.title) < ($1.subtitle == "App" ? 0 : 1, $1.title) }
            DispatchQueue.main.async {
                guard let self, self.origin() == origin else { return }
                self.rebuildCatalog(apps: items)
            }
        }.resume()
    }

    func filter() {
        let q = field.stringValue.trimmingCharacters(in: .whitespaces).lowercased()
        if q.isEmpty { results = catalog }
        else {
            let words = q.split(separator: " ").map(String.init)
            results = catalog.filter { item in
                let hay = (item.title + " " + item.subtitle + " " + item.open + " " + Self.aliases(item)).lowercased()
                return words.allSatisfy { hay.contains($0) }
            }.sorted { a, b in
                let ap = a.title.lowercased().hasPrefix(q), bp = b.title.lowercased().hasPrefix(q)
                return ap != bp ? ap : false
            }
        }
        table.reloadData()
        if !results.isEmpty { table.selectRowIndexes([0], byExtendingSelection: false); table.scrollRowToVisible(0) }
    }

    static func aliases(_ item: SearchItem) -> String {
        item.open.hasPrefix("/meetings") ? "meeting meetings record recorder recording transcribe transcript notes call zoom mizel" : ""
    }

    func show() {
        field.stringValue = ""
        rebuildCatalog(apps: catalog.filter { $0.key == nil })
        refreshApps()
        WizardBindings.refresh(origin: origin())
        let screen = NSScreen.screens.first(where: { NSMouseInRect(NSEvent.mouseLocation, $0.frame, false) }) ?? NSScreen.main
        if let f = screen?.visibleFrame {
            panel.setFrameOrigin(NSPoint(x: f.midX - panel.frame.width / 2, y: f.minY + f.height * 0.62))
        }
        panel.makeKeyAndOrderFront(nil)
        panel.makeFirstResponder(field)
    }

    func toggle() { panel.isVisible ? panel.orderOut(nil) : show() }

    @objc func openSelected() {
        let row = table.selectedRow
        guard results.indices.contains(row) else { return }
        panel.orderOut(nil)
        onOpen(results[row].open)
    }

    // NSTextFieldDelegate
    func controlTextDidChange(_ obj: Notification) { filter() }
    func control(_ control: NSControl, textView: NSTextView, doCommandBy sel: Selector) -> Bool {
        switch sel {
        case #selector(NSResponder.moveDown(_:)): move(1); return true
        case #selector(NSResponder.moveUp(_:)): move(-1); return true
        case #selector(NSResponder.insertNewline(_:)): openSelected(); return true
        case #selector(NSResponder.cancelOperation(_:)): panel.orderOut(nil); return true
        default: return false
        }
    }
    private func move(_ d: Int) {
        guard !results.isEmpty else { return }
        let r = max(0, min(results.count - 1, table.selectedRow + d))
        table.selectRowIndexes([r], byExtendingSelection: false); table.scrollRowToVisible(r)
    }

    // Table
    func numberOfRows(in tableView: NSTableView) -> Int { results.count }
    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        let item = results[row]
        let cell = NSView()
        let title = NSTextField(labelWithString: item.title)
        title.font = .systemFont(ofSize: 15, weight: .medium); title.textColor = WizardSearch.text
        title.lineBreakMode = .byTruncatingTail
        let sub = NSTextField(labelWithString: item.subtitle)
        sub.font = .systemFont(ofSize: 11); sub.textColor = WizardSearch.text2
        let key = NSTextField(labelWithString: item.key.map { "⇪ \($0.uppercased())" } ?? "")
        key.font = .monospacedSystemFont(ofSize: 12, weight: .medium); key.textColor = WizardSearch.wiz
        key.alignment = .right
        for v in [title, sub, key] { v.translatesAutoresizingMaskIntoConstraints = false; cell.addSubview(v) }
        NSLayoutConstraint.activate([
            title.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 12),
            title.topAnchor.constraint(equalTo: cell.topAnchor, constant: 6),
            title.trailingAnchor.constraint(lessThanOrEqualTo: key.leadingAnchor, constant: -12),
            sub.leadingAnchor.constraint(equalTo: title.leadingAnchor),
            sub.topAnchor.constraint(equalTo: title.bottomAnchor, constant: 1),
            key.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -14),
            key.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
            key.widthAnchor.constraint(equalToConstant: 48),
        ])
        return cell
    }
    func tableView(_ tableView: NSTableView, rowViewForRow row: Int) -> NSTableRowView? { SearchRow() }
}

private final class SearchRow: NSTableRowView {
    override func drawSelection(in dirtyRect: NSRect) {
        WizardSearch.raised.setFill()
        NSBezierPath(roundedRect: bounds.insetBy(dx: 2, dy: 1), xRadius: 10, yRadius: 10).fill()
        WizardSearch.wiz.setFill()
        NSBezierPath(roundedRect: NSRect(x: 4, y: bounds.midY - 9, width: 3, height: 18), xRadius: 1.5, yRadius: 1.5).fill()
    }
}

// MARK: - The one Wizard menu-bar icon

/// Owned by Wizard.app so it exists whether Wizard OS runs on this Mac or elsewhere.
/// Wizard Host hides its own icon while Wizard.app is running and shows it again if the app quits.
final class WizardStatusMenu: NSObject, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    var actions: WizardStatusActions!

    func install(_ actions: WizardStatusActions) {
        self.actions = actions
        item.button?.image = WizardBrand.menuBarImage()
        let menu = NSMenu(); menu.delegate = self; menu.autoenablesItems = false
        item.menu = menu
    }

    func menuNeedsUpdate(_ menu: NSMenu) { rebuild(menu) }

    func rebuild(_ menu: NSMenu) {
        menu.removeAllItems()
        let status = NSMenuItem(title: actions.statusLine(), action: nil, keyEquivalent: ""); status.isEnabled = false
        menu.addItem(status)
        menu.addItem(.separator())
        add(menu, "Open Wizard", #selector(WizardStatusActions.openWizard))
        add(menu, actions.isRecording() ? "Stop Recording" : "Record a Meeting", #selector(WizardStatusActions.toggleRecording))
        let search = add(menu, "Search…", #selector(WizardStatusActions.openSearch))
        search.toolTip = "Tap Caps Lock"
        let views = NSMenuItem(title: "Views", action: nil, keyEquivalent: ""); let sub = NSMenu()
        for (i, b) in WizardBindings.current.enumerated() {
            let it = NSMenuItem(title: "\(b.title)    ⇪ \(b.key.uppercased())", action: #selector(WizardStatusActions.openBinding(_:)), keyEquivalent: "")
            it.tag = i; it.target = actions; sub.addItem(it)
        }
        views.submenu = sub; menu.addItem(views)
        menu.addItem(.separator())
        let caps = add(menu, "Use Caps Lock as the Wizard key", #selector(WizardStatusActions.toggleWizardKey))
        caps.state = CapsLockRemap.enabled ? .on : .off
        let prompts = add(menu, "Ask to Record Calls", #selector(WizardStatusActions.togglePrompts))
        prompts.state = CallDetector.enabled ? .on : .off
        let voice = add(menu, "Voice Keys (Right ⌥ dictate, Right ⌘ Wizard)", #selector(WizardStatusActions.toggleVoiceKeys))
        voice.state = VoiceKeys.enabled ? .on : .off
        if actions.isLocal() {
            menu.addItem(.separator())
            add(menu, "Restart Wizard OS", #selector(WizardStatusActions.restartOS))
            add(menu, "Stop Wizard OS", #selector(WizardStatusActions.stopOS))
            add(menu, "Start Wizard OS", #selector(WizardStatusActions.startOS))
            add(menu, "Show Logs", #selector(WizardStatusActions.showLogs))
        }
        menu.addItem(.separator())
        add(menu, actions.isLocal() ? "Quit Wizard (stops Wizard OS)" : "Quit Wizard", #selector(WizardStatusActions.quitAll))
    }

    @discardableResult
    private func add(_ menu: NSMenu, _ title: String, _ sel: Selector) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: sel, keyEquivalent: ""); it.target = actions; menu.addItem(it); return it
    }

    func titles() -> [String] { let m = NSMenu(); rebuild(m); return m.items.map { $0.isSeparatorItem ? "—" : $0.title } }
}

/// Closures are wired by the app delegate.
final class WizardStatusActions: NSObject {
    var statusLine: () -> String = { "" }
    var isLocal: () -> Bool = { false }
    var open: (String) -> Void = { _ in }
    var show: () -> Void = {}
    var quit: () -> Void = {}
    var isRecording: () -> Bool = { false }
    var recordToggle: () -> Void = {}
    var toggleVoice: () -> Void = {}
    @objc func openWizard() { show() }
    @objc func toggleRecording() { recordToggle() }
    @objc func togglePrompts() { CallDetector.enabled.toggle() }
    @objc func toggleVoiceKeys() { toggleVoice() }
    @objc func openSearch() { WizardSearch.shared.show() }
    @objc func openBinding(_ sender: NSMenuItem) {
        let list = WizardBindings.current
        if list.indices.contains(sender.tag), let p = list[sender.tag].open { open(p) }
    }
    @objc func toggleWizardKey() { CapsLockRemap.enabled.toggle() }
    @objc func restartOS() { HostControl.send("restart") }
    @objc func stopOS() { HostControl.send("stop") }
    @objc func startOS() { HostControl.send("start") }
    @objc func showLogs() { NSWorkspace.shared.open(WizardShared.logsDir) }
    @objc func quitAll() { quit() }
}
