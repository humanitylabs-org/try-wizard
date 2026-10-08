import AVFoundation
import AppKit
import ApplicationServices
import CoreAudio

// Mizel on the Mac: floating recorder, call detection pop-up, voice keys, and the meeting.* bridge.

enum WizStyle {
    static let bg = NSColor(calibratedRed: 0.059, green: 0.063, blue: 0.078, alpha: 0.97)   // #0f1014
    static let raised = NSColor(calibratedRed: 0.086, green: 0.090, blue: 0.114, alpha: 1)  // #16171d
    static let line = NSColor(calibratedRed: 0.137, green: 0.141, blue: 0.176, alpha: 1)    // #23242d
    static let text = NSColor(calibratedRed: 0.922, green: 0.925, blue: 0.949, alpha: 1)    // #ebecf2
    static let text2 = NSColor(calibratedRed: 0.651, green: 0.663, blue: 0.714, alpha: 1)   // #a6a9b6
    static let wiz = NSColor(calibratedRed: 0.643, green: 0.545, blue: 0.980, alpha: 1)     // #a48bfa
    static let them = NSColor(calibratedRed: 0.490, green: 0.827, blue: 0.988, alpha: 1)    // #7dd3fc
    static let rec = NSColor(calibratedRed: 0.973, green: 0.443, blue: 0.443, alpha: 1)     // #f87171

    static func panel(_ rect: NSRect) -> FloatingPanel {
        let p = FloatingPanel(contentRect: rect, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        p.level = .floating
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        p.isOpaque = false; p.backgroundColor = .clear; p.hasShadow = true
        p.isMovableByWindowBackground = true
        p.hidesOnDeactivate = false
        p.appearance = NSAppearance(named: .darkAqua)
        let v = NSView(frame: NSRect(origin: .zero, size: rect.size))
        v.wantsLayer = true
        v.layer?.backgroundColor = bg.cgColor
        v.layer?.cornerRadius = 14
        v.layer?.borderWidth = 1
        v.layer?.borderColor = line.cgColor
        p.contentView = v
        return p
    }
    static func label(_ s: String, size: CGFloat, weight: NSFont.Weight = .regular, color: NSColor = text, mono: Bool = false) -> NSTextField {
        let l = NSTextField(labelWithString: s)
        l.font = mono ? .monospacedDigitSystemFont(ofSize: size, weight: weight) : .systemFont(ofSize: size, weight: weight)
        l.textColor = color; l.lineBreakMode = .byTruncatingTail
        return l
    }
    static func button(_ title: String, symbol: String? = nil, primary: Bool = false, target: AnyObject, action: Selector) -> NSButton {
        let b = HoverButton(title: title, target: target, action: action)
        b.isBordered = false; b.wantsLayer = true
        b.layer?.cornerRadius = 8
        b.layer?.backgroundColor = (primary ? wiz : raised).cgColor
        b.contentTintColor = primary ? bg : text
        b.attributedTitle = NSAttributedString(string: title, attributes: [.foregroundColor: primary ? NSColor(calibratedRed: 0.06, green: 0.06, blue: 0.08, alpha: 1) : text,
                                                                         .font: NSFont.systemFont(ofSize: 12.5, weight: .semibold)])
        if let symbol, let img = NSImage(systemSymbolName: symbol, accessibilityDescription: title) {
            b.image = img.withSymbolConfiguration(.init(pointSize: 11, weight: .semibold)); b.imagePosition = title.isEmpty ? .imageOnly : .imageLeading
        }
        return b
    }
}

final class FloatingPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}
final class HoverButton: NSButton {
    override func resetCursorRects() { addCursorRect(bounds, cursor: .pointingHand) }
}

/// Horizontal level meter (0…1) with a soft floor.
final class LevelBar: NSView {
    var color: NSColor = WizStyle.wiz
    var level: Float = 0 { didSet { if abs(level - oldValue) > 0.005 { needsDisplay = true } } }
    var muted = false { didSet { needsDisplay = true } }
    override func draw(_ dirtyRect: NSRect) {
        let r = bounds.insetBy(dx: 0, dy: 0.5)
        WizStyle.raised.setFill(); NSBezierPath(roundedRect: r, xRadius: r.height / 2, yRadius: r.height / 2).fill()
        guard !muted else { return }
        let w = max(r.height, r.width * CGFloat(min(1, max(0, level))))
        color.withAlphaComponent(level > 0.02 ? 1 : 0.35).setFill()
        NSBezierPath(roundedRect: NSRect(x: r.minX, y: r.minY, width: w, height: r.height), xRadius: r.height / 2, yRadius: r.height / 2).fill()
    }
}

// MARK: - Floating recorder

final class RecorderPanel: NSObject, NSTextFieldDelegate {
    static let shared = RecorderPanel()
    let panel = WizStyle.panel(NSRect(x: 0, y: 0, width: 340, height: 138))
    let dot = NSView()
    let clock = WizStyle.label("0:00", size: 15, weight: .semibold, mono: true)
    let title = WizStyle.label("Recording", size: 12.5, color: WizStyle.text2)
    let meBar = LevelBar(), themBar = LevelBar()
    let themLabel = WizStyle.label("Them", size: 11, weight: .medium, color: WizStyle.text2)
    let note = NSTextField()
    var pauseBtn: NSButton!, stopBtn: NSButton!, expandBtn: NSButton!
    private var timer: Timer?
    var onExpand: (String) -> Void = { _ in }
    /// Hide while the Mizel page itself is in front (it has its own recording UI).
    var shouldShow: () -> Bool = { true }

    override init() {
        super.init()
        let v = panel.contentView!
        dot.wantsLayer = true; dot.layer?.backgroundColor = WizStyle.rec.cgColor; dot.layer?.cornerRadius = 5
        let me = WizStyle.label("Me", size: 11, weight: .medium, color: WizStyle.text2)
        meBar.color = WizStyle.wiz; themBar.color = WizStyle.them
        note.placeholderString = "Quick note — press Return"
        note.font = .systemFont(ofSize: 12.5); note.textColor = WizStyle.text
        note.isBordered = false; note.drawsBackground = true; note.backgroundColor = WizStyle.raised
        note.focusRingType = .none; note.delegate = self; note.wantsLayer = true; note.layer?.cornerRadius = 7
        note.cell?.usesSingleLineMode = true
        pauseBtn = WizStyle.button("", symbol: "pause.fill", target: self, action: #selector(pauseResume))
        stopBtn = WizStyle.button("Stop", symbol: "stop.fill", target: self, action: #selector(stop))
        stopBtn.layer?.backgroundColor = WizStyle.rec.withAlphaComponent(0.18).cgColor
        stopBtn.attributedTitle = NSAttributedString(string: "Stop", attributes: [.foregroundColor: WizStyle.rec, .font: NSFont.systemFont(ofSize: 12.5, weight: .semibold)])
        stopBtn.contentTintColor = WizStyle.rec
        expandBtn = WizStyle.button("", symbol: "arrow.up.left.and.arrow.down.right", target: self, action: #selector(expand))
        expandBtn.toolTip = "Open in Mizel"; pauseBtn.toolTip = "Pause"
        for x in [dot, clock, title, me, meBar, themLabel, themBar, note, pauseBtn!, stopBtn!, expandBtn!] as [NSView] {
            x.translatesAutoresizingMaskIntoConstraints = false; v.addSubview(x)
        }
        NSLayoutConstraint.activate([
            dot.leadingAnchor.constraint(equalTo: v.leadingAnchor, constant: 16), dot.widthAnchor.constraint(equalToConstant: 10),
            dot.heightAnchor.constraint(equalToConstant: 10), dot.centerYAnchor.constraint(equalTo: clock.centerYAnchor),
            clock.leadingAnchor.constraint(equalTo: dot.trailingAnchor, constant: 9), clock.topAnchor.constraint(equalTo: v.topAnchor, constant: 13),
            title.leadingAnchor.constraint(equalTo: clock.trailingAnchor, constant: 10), title.firstBaselineAnchor.constraint(equalTo: clock.firstBaselineAnchor),
            title.trailingAnchor.constraint(lessThanOrEqualTo: expandBtn.leadingAnchor, constant: -8),
            expandBtn.trailingAnchor.constraint(equalTo: v.trailingAnchor, constant: -12), expandBtn.centerYAnchor.constraint(equalTo: clock.centerYAnchor),
            expandBtn.widthAnchor.constraint(equalToConstant: 26), expandBtn.heightAnchor.constraint(equalToConstant: 24),

            me.leadingAnchor.constraint(equalTo: v.leadingAnchor, constant: 16), me.topAnchor.constraint(equalTo: clock.bottomAnchor, constant: 12),
            me.widthAnchor.constraint(equalToConstant: 34),
            meBar.leadingAnchor.constraint(equalTo: me.trailingAnchor, constant: 4), meBar.centerYAnchor.constraint(equalTo: me.centerYAnchor),
            meBar.heightAnchor.constraint(equalToConstant: 6), meBar.widthAnchor.constraint(equalToConstant: 92),
            themLabel.leadingAnchor.constraint(equalTo: meBar.trailingAnchor, constant: 18), themLabel.centerYAnchor.constraint(equalTo: me.centerYAnchor),
            themLabel.widthAnchor.constraint(equalToConstant: 40),
            themBar.leadingAnchor.constraint(equalTo: themLabel.trailingAnchor, constant: 2), themBar.centerYAnchor.constraint(equalTo: me.centerYAnchor),
            themBar.heightAnchor.constraint(equalToConstant: 6), themBar.trailingAnchor.constraint(equalTo: v.trailingAnchor, constant: -16),

            note.leadingAnchor.constraint(equalTo: v.leadingAnchor, constant: 12), note.bottomAnchor.constraint(equalTo: v.bottomAnchor, constant: -14),
            note.heightAnchor.constraint(equalToConstant: 28), note.trailingAnchor.constraint(equalTo: pauseBtn.leadingAnchor, constant: -8),
            pauseBtn.widthAnchor.constraint(equalToConstant: 30), pauseBtn.heightAnchor.constraint(equalToConstant: 28),
            pauseBtn.centerYAnchor.constraint(equalTo: note.centerYAnchor), pauseBtn.trailingAnchor.constraint(equalTo: stopBtn.leadingAnchor, constant: -6),
            stopBtn.widthAnchor.constraint(equalToConstant: 70), stopBtn.heightAnchor.constraint(equalToConstant: 28),
            stopBtn.centerYAnchor.constraint(equalTo: note.centerYAnchor), stopBtn.trailingAnchor.constraint(equalTo: v.trailingAnchor, constant: -12),
        ])
        MeetingRecorder.shared.onChange = { [weak self] in DispatchQueue.main.async { self?.sync() } }
    }

    func place() {
        guard let screen = NSScreen.main?.visibleFrame else { return }
        if panel.frame.origin == .zero {
            panel.setFrameOrigin(NSPoint(x: screen.maxX - panel.frame.width - 18, y: screen.maxY - panel.frame.height - 14))
        }
    }

    /// Show/hide and refresh from recorder state.
    func sync() {
        let r = MeetingRecorder.shared
        guard r.isRecording else { timer?.invalidate(); timer = nil; panel.orderOut(nil); return }
        if timer == nil {
            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in self?.tick() }
            RunLoop.main.add(timer!, forMode: .common)
        }
        tick()
        if shouldShow() { if !panel.isVisible { place(); panel.orderFrontRegardless() } } else if panel.isVisible { panel.orderOut(nil) }
    }

    func tick() {
        let r = MeetingRecorder.shared
        guard let s = r.session else { return }
        let e = Int(r.elapsed)
        clock.stringValue = e >= 3600 ? String(format: "%d:%02d:%02d", e / 3600, e / 60 % 60, e % 60) : String(format: "%d:%02d", e / 60, e % 60)
        title.stringValue = r.stopping ? "Saving…" : (s.pausedAt != nil ? "Paused · " : "") + s.title
        let l = r.levels
        meBar.level = l.me; themBar.level = l.them
        themBar.muted = s.them == nil || s.them?.input == nil; themLabel.textColor = themBar.muted ? WizStyle.line : WizStyle.text2
        themLabel.stringValue = s.them == nil ? "Them off" : "Them"
        let paused = s.pausedAt != nil
        dot.layer?.backgroundColor = (paused ? WizStyle.text2 : WizStyle.rec).cgColor
        dot.alphaValue = paused ? 1 : (Int(Date().timeIntervalSince1970 * 2) % 2 == 0 ? 1 : 0.45)
        pauseBtn.image = NSImage(systemSymbolName: paused ? "play.fill" : "pause.fill", accessibilityDescription: nil)
        pauseBtn.toolTip = paused ? "Resume" : "Pause"
        stopBtn.isEnabled = !r.stopping
    }

    @objc func pauseResume() { let r = MeetingRecorder.shared; r.session?.pausedAt == nil ? r.pause() : r.resume() }
    @objc func stop() { MeetingRecorder.shared.stop(finalize: true) { _ in } }
    @objc func expand() {
        guard let s = MeetingRecorder.shared.session else { return }
        let view = s.apiBase.hasSuffix("/api") ? String(s.apiBase.dropLast(3)) : s.apiBase + "/"
        onExpand(view + "#/m/" + s.meetingId)
    }
    func control(_ control: NSControl, textView: NSTextView, doCommandBy sel: Selector) -> Bool {
        if sel == #selector(NSResponder.insertNewline(_:)) {
            MeetingRecorder.shared.addNote(note.stringValue); note.stringValue = ""; return true
        }
        if sel == #selector(NSResponder.cancelOperation(_:)) { note.stringValue = ""; panel.makeFirstResponder(nil); return true }
        return false
    }
}

// MARK: - Call detection + "Record?" pop-up

final class CallPrompt: NSObject {
    static let shared = CallPrompt()
    let panel = WizStyle.panel(NSRect(x: 0, y: 0, width: 360, height: 92))
    let heading = WizStyle.label("", size: 13.5, weight: .semibold)
    let sub = WizStyle.label("Record it with Mizel?", size: 12, color: WizStyle.text2)
    private var hideTimer: Timer?
    var onRecord: (_ title: String, _ eventId: String?) -> Void = { _, _ in }
    private(set) var current: (title: String, eventId: String?)?

    override init() {
        super.init()
        let v = panel.contentView!
        let icon = NSImageView(image: NSImage(systemSymbolName: "waveform.circle.fill", accessibilityDescription: nil)!)
        icon.symbolConfiguration = .init(pointSize: 26, weight: .regular); icon.contentTintColor = WizStyle.wiz
        let rec = WizStyle.button("Record", symbol: "record.circle", primary: true, target: self, action: #selector(record))
        let later = WizStyle.button("Not now", target: self, action: #selector(dismiss))
        rec.keyEquivalent = "\r"
        for x in [icon, heading, sub, rec, later] as [NSView] { x.translatesAutoresizingMaskIntoConstraints = false; v.addSubview(x) }
        NSLayoutConstraint.activate([
            icon.leadingAnchor.constraint(equalTo: v.leadingAnchor, constant: 14), icon.topAnchor.constraint(equalTo: v.topAnchor, constant: 14),
            heading.leadingAnchor.constraint(equalTo: icon.trailingAnchor, constant: 10), heading.topAnchor.constraint(equalTo: v.topAnchor, constant: 13),
            heading.trailingAnchor.constraint(lessThanOrEqualTo: v.trailingAnchor, constant: -14),
            sub.leadingAnchor.constraint(equalTo: heading.leadingAnchor), sub.topAnchor.constraint(equalTo: heading.bottomAnchor, constant: 2),
            rec.trailingAnchor.constraint(equalTo: v.trailingAnchor, constant: -12), rec.bottomAnchor.constraint(equalTo: v.bottomAnchor, constant: -12),
            rec.widthAnchor.constraint(equalToConstant: 92), rec.heightAnchor.constraint(equalToConstant: 28),
            later.trailingAnchor.constraint(equalTo: rec.leadingAnchor, constant: -8), later.centerYAnchor.constraint(equalTo: rec.centerYAnchor),
            later.widthAnchor.constraint(equalToConstant: 80), later.heightAnchor.constraint(equalToConstant: 28),
        ])
    }

    func show(title: String, eventId: String?) {
        current = (title, eventId)
        heading.stringValue = title
        if let screen = NSScreen.main?.visibleFrame {
            panel.setFrameOrigin(NSPoint(x: screen.maxX - panel.frame.width - 18, y: screen.maxY - panel.frame.height - 14))
        }
        panel.alphaValue = 0; panel.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { $0.duration = 0.18; panel.animator().alphaValue = 1 }
        NSSound(named: "Tink")?.play()
        hideTimer?.invalidate()
        hideTimer = Timer.scheduledTimer(withTimeInterval: 45, repeats: false) { [weak self] _ in self?.dismiss() }
        MeetingLog.log("prompt shown: \(title)")
    }
    @objc func record() {
        guard let c = current else { return }
        dismiss(); onRecord(c.title, c.eventId)
    }
    @objc func dismiss() { hideTimer?.invalidate(); panel.orderOut(nil); current = nil }
}

/// Watches for calls: another app opening the microphone (Zoom, Meet in a browser, Teams, FaceTime, Slack…)
/// and Wizard calendar events with people or a meeting link starting now. One prompt per call.
final class CallDetector {
    static let shared = CallDetector()
    static var enabled: Bool {
        get { UserDefaults.standard.object(forKey: "MeetingPrompts") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "MeetingPrompts") }
    }
    static let callApps: [String: String] = [
        "us.zoom.xos": "Zoom", "com.microsoft.teams2": "Microsoft Teams", "com.microsoft.teams": "Microsoft Teams",
        "com.apple.FaceTime": "FaceTime", "com.tinyspeck.slackmacgap": "Slack", "com.hnc.Discord": "Discord",
        "net.whatsapp.WhatsApp": "WhatsApp", "ru.keepcoder.Telegram": "Telegram", "org.whispersystems.signal-desktop": "Signal",
        "com.cisco.webexmeetingsapp": "Webex", "com.webex.meetingmanager": "Webex",
    ]
    static let browsers: [String: String] = [
        "com.google.Chrome": "Chrome", "com.apple.Safari": "Safari", "company.thebrowser.Browser": "Arc",
        "org.mozilla.firefox": "Firefox", "com.brave.Browser": "Brave", "com.microsoft.edgemac": "Edge", "com.vivaldi.Vivaldi": "Vivaldi",
    ]
    var origin: () -> URL? = { nil }
    private var timer: Timer?
    private var calendarTimer: Timer?
    private var events: [[String: Any]] = []
    private var promptedApps: Set<String> = []
    private var promptedEvents: Set<String> = []
    private(set) var micUsers: [String] = []
    private(set) var lastCalendarFetch: Date?

    func install() {
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.check() }
        calendarTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.fetchCalendar() }
        fetchCalendar()
    }

    func fetchCalendar() {
        guard let o = origin(), let url = URL(string: "meetings/api/calendar", relativeTo: o) else { return }
        var req = URLRequest(url: url, timeoutInterval: 10); req.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: req) { [weak self] data, resp, _ in
            guard (resp as? HTTPURLResponse)?.statusCode == 200, let data,
                  let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let ev = j["events"] as? [[String: Any]] else { return }
            DispatchQueue.main.async { self?.events = ev; self?.lastCalendarFetch = Date() }
        }.resume()
    }

    /// Bundle IDs of other processes currently capturing audio input.
    static func inputUsers() -> [String] {
        let me = getpid()
        return CoreAudioUtil.processObjects().compactMap { obj in
            guard CoreAudioUtil.u32(obj, kAudioProcessPropertyIsRunningInput) == 1, CoreAudioUtil.pid(obj) != me else { return nil }
            return CoreAudioUtil.string(obj, kAudioProcessPropertyBundleID)
        }
    }

    static let iso: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime]; return f }()
    func currentEvent(window: TimeInterval = 120) -> [String: Any]? {
        let now = Date()
        return events.first { e in
            guard let s = (e["start"] as? String).flatMap({ Self.iso.date(from: $0) }),
                  let en = (e["end"] as? String).flatMap({ Self.iso.date(from: $0) }) else { return false }
            let social = !((e["attendees"] as? [Any]) ?? []).isEmpty || !((e["meet_url"] as? String) ?? "").isEmpty
            return social && s.addingTimeInterval(-window) <= now && now < en
        }
    }

    func check() {
        micUsers = Self.inputUsers()
        guard Self.enabled, !MeetingRecorder.shared.isRecording, CallPrompt.shared.current == nil else { return }
        // Apps that stopped using the mic can prompt again next time.
        promptedApps = promptedApps.intersection(Set(micUsers))
        let event = currentEvent()
        for b in micUsers where !promptedApps.contains(b) {
            if let name = Self.callApps[b] {
                promptedApps.insert(b)
                prompt(event.flatMap { $0["title"] as? String }.map { "Call: \($0)" } ?? "Call in \(name)", eventId: event?["id"] as? String)
                return
            }
            if let name = Self.browsers[b] {
                promptedApps.insert(b)
                let meet = (event?["meet_url"] as? String).map { $0.contains("meet.google") ? "Google Meet" : "a call" } ?? "a call"
                prompt(event.flatMap { $0["title"] as? String }.map { "Call: \($0)" } ?? "\(meet.prefix(1).uppercased() + meet.dropFirst()) in \(name)", eventId: event?["id"] as? String)
                return
            }
        }
        // Calendar meeting starting (within a minute) even before anyone opens the mic.
        if let e = currentEvent(window: 60), let id = e["id"] as? String, !promptedEvents.contains(id),
           let s = (e["start"] as? String).flatMap({ Self.iso.date(from: $0) }), Date().timeIntervalSince(s) < 300 {
            promptedEvents.insert(id)
            prompt("Starting now: \((e["title"] as? String) ?? "Meeting")", eventId: id)
        }
    }

    func prompt(_ title: String, eventId: String?) {
        if let id = eventId { promptedEvents.insert(id) }
        CallPrompt.shared.show(title: title, eventId: eventId)
    }

    var state: [String: Any] {
        ["enabled": Self.enabled, "micUsers": micUsers, "events": events.count, "promptedApps": Array(promptedApps),
         "calendarFetched": lastCalendarFetch.map { Self.iso.string(from: $0) } ?? NSNull(), "promptVisible": CallPrompt.shared.panel.isVisible]
    }
}

// MARK: - Voice keys (tap to start, tap again to send)

/// Short mic capture for dictation: 16 kHz mono WAV.
final class VoiceCapture {
    private var mic: MicSource?
    private let chunker = PCMChunker()
    private var samples: [Int16] = []
    private let q = DispatchQueue(label: "wizard.voice")
    var level: Float { chunker.level }
    var startedAt: Date?

    func start() throws {
        samples = []
        chunker.onChunk = { [weak self] s in self?.samples.append(contentsOf: s) }
        let m = MicSource()
        try m.start { [weak self] buf in self?.q.sync { self?.chunker.feed(buf) } }
        mic = m; startedAt = Date()
    }
    func stop() -> Data? {
        mic?.stop(); mic = nil
        q.sync { chunker.flush() }
        startedAt = nil
        return samples.count >= 8000 ? PCMChunker.wav(samples) : nil
    }
    var running: Bool { mic != nil }
}

/// Small non-activating HUD at the bottom of the screen while a voice key is live.
final class VoiceHUD {
    static let shared = VoiceHUD()
    let panel = WizStyle.panel(NSRect(x: 0, y: 0, width: 300, height: 44))
    let label = WizStyle.label("", size: 12.5, weight: .medium)
    let bar = LevelBar()
    private var timer: Timer?
    var levelSource: () -> Float = { 0 }

    init() {
        let v = panel.contentView!
        v.layer?.cornerRadius = 22
        panel.ignoresMouseEvents = true
        for x in [label, bar] as [NSView] { x.translatesAutoresizingMaskIntoConstraints = false; v.addSubview(x) }
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: v.leadingAnchor, constant: 18), label.centerYAnchor.constraint(equalTo: v.centerYAnchor),
            bar.trailingAnchor.constraint(equalTo: v.trailingAnchor, constant: -18), bar.centerYAnchor.constraint(equalTo: v.centerYAnchor),
            bar.widthAnchor.constraint(equalToConstant: 56), bar.heightAnchor.constraint(equalToConstant: 6),
            label.trailingAnchor.constraint(lessThanOrEqualTo: bar.leadingAnchor, constant: -10),
        ])
    }
    func show(_ text: String, color: NSColor = WizStyle.wiz, live: Bool) {
        label.stringValue = text; bar.color = color; bar.isHidden = !live
        if let s = NSScreen.main?.visibleFrame { panel.setFrameOrigin(NSPoint(x: s.midX - 150, y: s.minY + 36)) }
        panel.orderFrontRegardless()
        timer?.invalidate()
        if live { timer = Timer.scheduledTimer(withTimeInterval: 0.08, repeats: true) { [weak self] _ in self?.bar.level = self?.levelSource() ?? 0 } }
    }
    func hide(after: TimeInterval = 0) {
        timer?.invalidate(); timer = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + after) { self.panel.orderOut(nil) }
    }
}

final class VoiceKeys {
    static let shared = VoiceKeys()
    static var enabled: Bool {
        get { UserDefaults.standard.bool(forKey: "VoiceKeys") }
        set { UserDefaults.standard.set(newValue, forKey: "VoiceKeys") }
    }
    static let rightOption: UInt16 = 61, rightCommand: UInt16 = 54

    enum Mode: String { case idle, dictating, transcribing, orb }
    private(set) var mode: Mode = .idle
    private(set) var monitors: [Any] = []
    private var downKey: UInt16?, downAt = Date(), chorded = false
    private let capture = VoiceCapture()
    private var trustTimer: Timer?
    private(set) var lastText = ""
    private(set) var lastError = ""
    var origin: () -> URL? = { nil }
    var orb: (_ start: Bool) -> Void = { _ in }

    var trusted: Bool { AXIsProcessTrusted() }

    /// Called at launch (no prompt) and when the user turns voice keys on (prompts once for Accessibility).
    func install(prompt: Bool) {
        guard Self.enabled else { uninstall(); return }
        if !trusted {
            if prompt { _ = AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary) }
            trustTimer?.invalidate()
            trustTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] t in
                guard let self, Self.enabled else { t.invalidate(); return }
                if self.trusted { t.invalidate(); self.addMonitors() }
            }
            return
        }
        addMonitors()
    }
    private func addMonitors() {
        guard monitors.isEmpty else { return }
        if let g = NSEvent.addGlobalMonitorForEvents(matching: [.flagsChanged, .keyDown], handler: { [weak self] e in self?.event(e) }) { monitors.append(g) }
        if let l = NSEvent.addLocalMonitorForEvents(matching: [.flagsChanged, .keyDown], handler: { [weak self] e in self?.event(e); return e }) { monitors.append(l) }
        MeetingLog.log("voice keys on (Right ⌥ dictation, Right ⌘ Wizard)")
    }
    func uninstall() { monitors.forEach(NSEvent.removeMonitor); monitors = []; trustTimer?.invalidate() }

    private func event(_ e: NSEvent) {
        if e.type == .keyDown { chorded = true; return }
        let k = e.keyCode
        guard k == Self.rightOption || k == Self.rightCommand else { if downKey != nil { chorded = true }; return }
        let flag: NSEvent.ModifierFlags = k == Self.rightOption ? .option : .command
        if e.modifierFlags.contains(flag) {
            downKey = k; downAt = Date(); chorded = e.modifierFlags.intersection([.shift, .control, .option, .command]).subtracting(flag).isEmpty == false
        } else if downKey == k {
            downKey = nil
            if !chorded && Date().timeIntervalSince(downAt) < 0.45 { tap(k) }
        }
    }

    func tap(_ k: UInt16) {
        if k == Self.rightOption { toggleDictation() } else { toggleOrb() }
    }

    func toggleDictation() {
        switch mode {
        case .idle:
            MeetingRecorder.micAuthorized { ok in
                guard ok else { VoiceHUD.shared.show("Microphone access is off for Wizard", color: WizStyle.rec, live: false); VoiceHUD.shared.hide(after: 2.5); return }
                do {
                    try self.capture.start(); self.mode = .dictating
                    VoiceHUD.shared.levelSource = { self.capture.level }
                    VoiceHUD.shared.show("Dictating — tap Right ⌥ to insert", live: true)
                } catch { self.lastError = error.localizedDescription; VoiceHUD.shared.show("Mic unavailable", color: WizStyle.rec, live: false); VoiceHUD.shared.hide(after: 2) }
            }
        case .dictating:
            mode = .transcribing
            guard let wav = capture.stop() else { mode = .idle; VoiceHUD.shared.show("Didn't hear anything", live: false); VoiceHUD.shared.hide(after: 1.5); return }
            VoiceHUD.shared.show("Transcribing…", live: false)
            transcribe(wav) { text, err in
                self.mode = .idle
                guard let text, !text.isEmpty else {
                    self.lastError = err ?? "blank"; VoiceHUD.shared.show(err ?? "Didn't catch that", color: WizStyle.rec, live: false); VoiceHUD.shared.hide(after: 2.5); return
                }
                self.lastText = text
                Self.insert(text)
                VoiceHUD.shared.hide()
            }
        default: break
        }
    }

    /// The page owns the truth (it may have been reloaded or finished by mouse): Wizard decides start vs send there.
    func toggleOrb() { orbTaps += 1; orb(true) }
    private(set) var orbTaps = 0

    /// Wizard STT on the active Wizard (Tinfoil Voxtral behind /wizard/voice/transcribe). No fallback provider.
    func transcribe(_ wav: Data, done: @escaping (String?, String?) -> Void) {
        guard let o = origin(), let url = URL(string: "wizard/voice/transcribe", relativeTo: o) else { done(nil, "No Wizard connected"); return }
        var req = URLRequest(url: url, timeoutInterval: 90); req.httpMethod = "POST"
        req.setValue("audio/wav", forHTTPHeaderField: "Content-Type"); req.setValue("wizard-dictation.wav", forHTTPHeaderField: "X-Wizard-Filename")
        req.httpBody = wav
        URLSession.shared.dataTask(with: req) { data, resp, err in
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            let j = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let text = (j?["text"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            MeetingLog.log("dictation: HTTP \(code), \(text?.count ?? 0) chars, provider \(j?["provider"] as? String ?? "-")")
            DispatchQueue.main.async { done(code == 200 ? text : nil, code == 200 ? nil : (err?.localizedDescription ?? "Transcription failed (\(code))")) }
        }.resume()
    }

    /// Type into the focused app: put the text on the pasteboard, ⌘V, then restore the clipboard.
    static func insert(_ text: String) {
        let pb = NSPasteboard.general
        let saved = pb.pasteboardItems?.map { item -> [(NSPasteboard.PasteboardType, Data)] in
            item.types.compactMap { t in item.data(forType: t).map { (t, $0) } }
        } ?? []
        pb.clearContents(); pb.setString(text, forType: .string)
        let src = CGEventSource(stateID: .combinedSessionState)
        let v: CGKeyCode = 9
        let down = CGEvent(keyboardEventSource: src, virtualKey: v, keyDown: true); down?.flags = .maskCommand
        let up = CGEvent(keyboardEventSource: src, virtualKey: v, keyDown: false); up?.flags = .maskCommand
        down?.post(tap: .cghidEventTap); up?.post(tap: .cghidEventTap)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
            guard !saved.isEmpty else { return }
            pb.clearContents()
            pb.writeObjects(saved.map { pairs in let it = NSPasteboardItem(); pairs.forEach { it.setData($0.1, forType: $0.0) }; return it })
        }
    }

    var state: [String: Any] {
        ["enabled": Self.enabled, "trusted": trusted, "monitors": monitors.count, "mode": mode.rawValue, "orbTaps": orbTaps, "lastText": lastText, "lastError": lastError]
    }
}

// MARK: - meeting.* bridge

enum MeetingBridge {
    /// Injected into every Wizard page in the app. Mizel looks for window.wizardNative.meetings and falls back
    /// to getUserMedia in a normal browser, where this script doesn't exist.
    static let adapterJS = #"""
    (() => {
      if (window.wizardNative && window.wizardNative.__mac) return;
      const pending = new Map(); let seq = 0;
      window.wizardNativeReply = (msg) => {
        const p = pending.get(msg && msg.id); if (!p) return; pending.delete(msg.id);
        const r = msg.result;
        if (r && typeof r === 'object' && r.error) p.reject(Object.assign(new Error(r.error), { name: r.name || 'Error' })); else p.resolve(r);
      };
      const call = (method, params = {}) => new Promise((resolve, reject) => {
        const id = ++seq; pending.set(id, { resolve, reject });
        window.webkit.messageHandlers.wizardNative.postMessage({ id, method, params });
      });
      const levelCbs = new Set(); let timer = 0;
      const poll = () => {
        if (timer) return;
        timer = setInterval(async () => {
          try {
            const l = await call('meeting.levels');
            const v = Math.max(l.me || 0, l.them || 0);
            levelCbs.forEach((cb) => { try { cb(v, l); } catch (_) {} });
            window.dispatchEvent(new CustomEvent('wizard-meeting-levels', { detail: l }));
            if (!l.recording) { clearInterval(timer); timer = 0; }
          } catch (_) { clearInterval(timer); timer = 0; }
        }, 120);
      };
      const meetings = {
        native: 'mac', version: 1, tracks: ['me', 'them'],
        start: async ({ meetingId, includeSystemAudio, title } = {}) => {
          // In Wizard.app call audio (Them) is on unless the user explicitly switched it off in Mizel.
          let them = includeSystemAudio;
          try { if (localStorage.getItem('meetings.systemAudio') === null) them = true; } catch (_) {}
          const r = await call('meeting.start', { meetingId, includeSystemAudio: them !== false, title: title || document.title, apiBase: new URL('api', location.href).href.replace(/\/$/, '') });
          poll(); return r;
        },
        stop: (opts = {}) => call('meeting.stop', { finalize: !!opts.finalize }),
        pause: () => call('meeting.pause'),
        resume: () => call('meeting.resume'),
        status: () => call('meeting.status'),
        levels: () => call('meeting.levels'),
        showRecorder: () => call('meeting.showRecorder'),
        onLevel: (cb) => { if (typeof cb === 'function') levelCbs.add(cb); return () => levelCbs.delete(cb); },
      };
      window.wizardNative = Object.assign(window.wizardNative || {}, { __mac: true, call, meetings });
      window.addEventListener('wizard-meeting-state', (e) => { if (e.detail && e.detail.recording) poll(); });
    })();
    """#

    static func register(origin: @escaping () -> URL?) {
        NativeBridge.shared.register("meeting.") { method, params, reply in
            let r = MeetingRecorder.shared
            switch method {
            case "meeting.start":
                guard let id = params["meetingId"] as? String, id.range(of: "^[A-Za-z0-9_-]{3,64}$", options: .regularExpression) != nil,
                      let frame = (params["_origin"] as? String).flatMap(URL.init(string:)),
                      let api = (params["apiBase"] as? String).flatMap(URL.init(string:)), api.host == frame.host, api.port == frame.port else {
                    reply(["error": "Bad meeting request"]); return
                }
                r.start(meetingId: id, apiBase: api.absoluteString, title: (params["title"] as? String).map { $0.replacingOccurrences(of: " — Mizel", with: "") } ?? "Meeting",
                        includeSystemAudio: params["includeSystemAudio"] as? Bool ?? true) { err in
                    if let err { reply(["error": err.localizedDescription, "name": (err.localizedDescription.contains("Microphone access") ? "NotAllowedError" : "Error")]) }
                    else { reply(r.status()) }
                }
            case "meeting.stop": r.stop(finalize: params["finalize"] as? Bool ?? false) { reply($0) }
            case "meeting.pause": r.pause(); reply(r.status())
            case "meeting.resume": r.resume(); reply(r.status())
            case "meeting.status": reply(r.status())
            case "meeting.levels":
                let l = r.levels
                reply(["recording": r.isRecording, "paused": r.session?.pausedAt != nil, "me": l.me, "them": l.them, "elapsedMs": Int(r.elapsed * 1000)])
            case "meeting.showRecorder": RecorderPanel.shared.shouldShow = { true }; RecorderPanel.shared.sync(); reply(true)
            default: reply(["error": "Unknown method \(method)"])
            }
        }
    }
}
