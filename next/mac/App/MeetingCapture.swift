import AVFoundation
import AppKit
import CoreAudio
import CoreMedia
import ScreenCaptureKit

// Mizel native capture: two tracks, "me" (microphone) and "them" (everything the Mac plays: the call).
// Each track is resampled to 16 kHz mono PCM16, cut into 5 s WAV chunks, spooled to disk first
// (~/Library/Application Support/Wizard/meetings/<id>/) and uploaded idempotently to the active
// Wizard's /meetings/api/meetings/<id>/chunks. Capture lives in Wizard.app (never Wizard Host),
// so it works for a Wizard on this Mac and a Wizard on another computer, with the window closed.

enum MeetingLog {
    static func log(_ s: String) {
        NSLog("Wizard meetings: %@", s)
        let dir = WizardShared.logsDir
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let f = dir.appendingPathComponent("meetings.log")
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(s)\n"
        if let h = try? FileHandle(forWritingTo: f) { h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); try? h.close() }
        else { try? line.data(using: .utf8)?.write(to: f) }
    }
}

// MARK: - 16 kHz mono PCM16 chunker

/// Converts any input format to 16 kHz mono Int16 with one persistent converter
/// (input exhaustion = .noDataNow, never end-of-stream, so it keeps producing for the whole meeting)
/// and emits fixed 5 s chunks.
final class PCMChunker {
    static let rate = 16_000
    static let chunkSamples = 80_000 // 5 s
    let outFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true)!
    private var converter: AVAudioConverter?
    private var inFormat: AVAudioFormat?
    private var pending: [Int16] = []
    var onChunk: ([Int16]) -> Void = { _ in }
    private(set) var level: Float = 0        // 0…1, log-scaled for meters
    private(set) var buffersIn = 0
    private(set) var lastBufferAt: Date?

    func feed(_ buf: AVAudioPCMBuffer) {
        buffersIn += 1; lastBufferAt = Date()
        guard buf.frameLength > 0 else { return }
        if inFormat != buf.format || converter == nil {
            converter = AVAudioConverter(from: buf.format, to: outFormat)
            converter?.downmix = true
            inFormat = buf.format
        }
        guard let converter else { return }
        let cap = AVAudioFrameCount(Double(buf.frameLength) * 16_000 / buf.format.sampleRate) + 256
        guard let out = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: cap) else { return }
        var given = false
        var err: NSError?
        let status = converter.convert(to: out, error: &err) { _, st in
            if given { st.pointee = .noDataNow; return nil }
            given = true; st.pointee = .haveData; return buf
        }
        guard status != .error, let p = out.int16ChannelData?[0] else { return }
        let n = Int(out.frameLength)
        guard n > 0 else { return }
        var sum: Double = 0
        for i in 0..<n { let s = Double(p[i]) / 32768; sum += s * s }
        let rms = sqrt(sum / Double(n))
        let db = 20 * log10(max(rms, 1e-6))              // -120…0 dBFS
        level = Float(max(0, min(1, (db + 60) / 50)))     // -60 dBFS → 0, -10 dBFS → 1
        pending.append(contentsOf: UnsafeBufferPointer(start: p, count: n))
        while pending.count >= Self.chunkSamples {
            onChunk(Array(pending[0..<Self.chunkSamples]))
            pending.removeFirst(Self.chunkSamples)
        }
    }

    /// Emit the tail (≥ 0.5 s) at stop.
    func flush() {
        if pending.count >= Self.rate / 2 { onChunk(pending) }
        pending.removeAll()
        level = 0
    }

    static func wav(_ s: [Int16]) -> Data {
        var d = Data(capacity: 44 + s.count * 2)
        func u32(_ v: UInt32) { var x = v.littleEndian; withUnsafeBytes(of: &x) { d.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { var x = v.littleEndian; withUnsafeBytes(of: &x) { d.append(contentsOf: $0) } }
        let len = UInt32(s.count * 2)
        d.append(contentsOf: Array("RIFF".utf8)); u32(36 + len); d.append(contentsOf: Array("WAVE".utf8))
        d.append(contentsOf: Array("fmt ".utf8)); u32(16); u16(1); u16(1); u32(16_000); u32(32_000); u16(2); u16(16)
        d.append(contentsOf: Array("data".utf8)); u32(len)
        s.withUnsafeBufferPointer { d.append(Data(buffer: $0)) }
        return d
    }
}

// MARK: - Spool + uploader

/// Disk-first spool. Files: meetings/<id>/meta.json and <source>-<seq>-<startms>.wav.
/// The uploader deletes a chunk only after the server confirms it (duplicates are accepted server-side).
final class MeetingSpool {
    static let shared = MeetingSpool()
    let root = WizardShared.supportDir.appendingPathComponent("meetings", isDirectory: true)
    private let q = DispatchQueue(label: "wizard.meetings.upload")
    private var running = false
    private var backoff: [String: (Date, Double)] = [:]   // meetingId -> (next try, delay)
    private(set) var uploaded = 0
    private(set) var lastError: String?
    var onChange: () -> Void = {}

    struct Meta: Codable { var meetingId: String; var apiBase: String; var title: String; var createdAt: Date; var done: Bool }

    func dir(_ id: String) -> URL { root.appendingPathComponent(id, isDirectory: true) }

    func open(_ meta: Meta) {
        try? FileManager.default.createDirectory(at: dir(meta.meetingId), withIntermediateDirectories: true)
        writeMeta(meta)
    }
    func writeMeta(_ meta: Meta) {
        if let d = try? JSONEncoder().encode(meta) { try? d.write(to: dir(meta.meetingId).appendingPathComponent("meta.json"), options: .atomic) }
    }
    func meta(_ id: String) -> Meta? {
        (try? Data(contentsOf: dir(id).appendingPathComponent("meta.json"))).flatMap { try? JSONDecoder().decode(Meta.self, from: $0) }
    }
    func markDone(_ id: String) { if var m = meta(id) { m.done = true; writeMeta(m) }; kick() }

    func write(meetingId: String, source: String, seq: Int, startMs: Int, samples: [Int16]) {
        let name = String(format: "%@-%06d-%d.wav", source, seq, startMs)
        let f = dir(meetingId).appendingPathComponent(name)
        let tmp = f.appendingPathExtension("part")
        do { try PCMChunker.wav(samples).write(to: tmp); try FileManager.default.moveItem(at: tmp, to: f) }
        catch { MeetingLog.log("spool write failed \(name): \(error.localizedDescription)") }
        kick()
    }

    func pending(_ id: String) -> Int {
        ((try? FileManager.default.contentsOfDirectory(atPath: dir(id).path)) ?? []).filter { $0.hasSuffix(".wav") }.count
    }
    var pendingTotal: Int {
        ((try? FileManager.default.contentsOfDirectory(atPath: root.path)) ?? []).reduce(0) { $0 + pending($1) }
    }

    /// Start (or continue) the upload loop. Safe to call any time; also called at launch to resume old spools.
    func kick() {
        q.async {
            guard !self.running else { return }
            self.running = true
            self.loop()
        }
    }

    private func loop() {
        let fm = FileManager.default
        var next: (URL, Meta)?
        let ids = ((try? fm.contentsOfDirectory(atPath: root.path)) ?? []).sorted()
        for id in ids {
            guard let meta = meta(id) else { continue }
            if let b = backoff[id], b.0 > Date() { continue }
            let files = ((try? fm.contentsOfDirectory(atPath: dir(id).path)) ?? []).filter { $0.hasSuffix(".wav") }.sorted {
                // interleave me/them by start time
                (Int($0.split(separator: "-").last?.dropLast(4) ?? "") ?? 0) < (Int($1.split(separator: "-").last?.dropLast(4) ?? "") ?? 0)
            }
            if let f = files.first { next = (dir(id).appendingPathComponent(f), meta); break }
            if meta.done { try? fm.removeItem(at: dir(id)) } // everything delivered
        }
        guard let (file, meta) = next else {
            running = false
            // something waiting on backoff? come back later
            if let soonest = backoff.values.map({ $0.0 }).min() {
                q.asyncAfter(deadline: .now() + max(0.5, soonest.timeIntervalSinceNow)) { if !self.running { self.running = true; self.loop() } }
            }
            return
        }
        let parts = file.deletingPathExtension().lastPathComponent.split(separator: "-")
        guard parts.count == 3, let seq = Int(parts[1]), let start = Int(parts[2]),
              var comps = URLComponents(string: meta.apiBase + "/meetings/" + meta.meetingId + "/chunks") else {
            try? fm.removeItem(at: file); q.async { self.loop() }; return
        }
        comps.queryItems = [URLQueryItem(name: "source", value: String(parts[0])), URLQueryItem(name: "seq", value: String(seq)),
                            URLQueryItem(name: "start_ms", value: String(start))]
        guard let url = comps.url, let body = try? Data(contentsOf: file) else { try? fm.removeItem(at: file); q.async { self.loop() }; return }
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30)
        req.httpMethod = "POST"; req.setValue("audio/wav", forHTTPHeaderField: "Content-Type"); req.httpBody = body
        URLSession.shared.dataTask(with: req) { _, resp, err in
            self.q.async {
                let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
                if code == 200 || code == 400 || code == 404 {
                    if code != 200 { MeetingLog.log("chunk \(file.lastPathComponent) rejected (\(code)); dropped") }
                    try? fm.removeItem(at: file)
                    self.uploaded += code == 200 ? 1 : 0
                    self.backoff[meta.meetingId] = nil; self.lastError = nil
                } else {
                    let delay = min(60, (self.backoff[meta.meetingId]?.1 ?? 1) * 2)
                    self.backoff[meta.meetingId] = (Date().addingTimeInterval(delay), delay)
                    self.lastError = err?.localizedDescription ?? "HTTP \(code)"
                    MeetingLog.log("upload \(file.lastPathComponent) failed (\(self.lastError!)); retry in \(Int(delay))s")
                }
                DispatchQueue.main.async { self.onChange() }
                self.loop()
            }
        }.resume()
    }

    /// Wait until every chunk of a meeting is delivered (or the deadline passes).
    func drain(_ id: String, timeout: TimeInterval, done: @escaping (Int) -> Void) {
        let deadline = Date().addingTimeInterval(timeout)
        func poll() {
            let left = pending(id)
            if left == 0 || Date() > deadline { done(left); return }
            backoff[id] = nil; kick()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: poll)
        }
        poll()
    }
}

// MARK: - Sources

protocol CaptureSource: AnyObject {
    var kind: String { get }
    func start(onBuffer: @escaping (AVAudioPCMBuffer) -> Void) throws
    func stop()
}

/// Microphone via AVAudioEngine (follows the default input; restarts on device changes).
final class MicSource: CaptureSource {
    let kind = "microphone"
    private var engine = AVAudioEngine()
    private var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    private var observer: NSObjectProtocol?
    var deviceName: String {
        var id = AudioDeviceID(0); var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        var a = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultInputDevice, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &size, &id)
        return CoreAudioUtil.string(id, kAudioObjectPropertyName) ?? "Microphone"
    }

    func start(onBuffer: @escaping (AVAudioPCMBuffer) -> Void) throws {
        self.onBuffer = onBuffer
        try startEngine()
        observer = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            guard let self else { return }
            MeetingLog.log("microphone changed; restarting input")
            self.engine.inputNode.removeTap(onBus: 0); self.engine.stop()
            try? self.startEngine()
        }
    }
    private func startEngine() throws {
        let input = engine.inputNode
        let fmt = input.outputFormat(forBus: 0)
        guard fmt.sampleRate > 0, fmt.channelCount > 0 else { throw MeetingRecorder.err("No microphone is available.") }
        input.installTap(onBus: 0, bufferSize: 4096, format: fmt) { [weak self] buf, _ in self?.onBuffer?(buf) }
        engine.prepare()
        try engine.start()
    }
    func stop() {
        if let observer { NotificationCenter.default.removeObserver(observer) }
        engine.inputNode.removeTap(onBus: 0); engine.stop()
        onBuffer = nil
    }
}

enum CoreAudioUtil {
    static func string(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector) -> String? {
        var a = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var s: Unmanaged<CFString>?; var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        guard AudioObjectGetPropertyData(obj, &a, 0, nil, &size, &s) == noErr, let v = s?.takeRetainedValue() else { return nil }
        return v as String
    }
    static func u32(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector) -> UInt32? {
        var a = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var v: UInt32 = 0; var size = UInt32(4)
        return AudioObjectGetPropertyData(obj, &a, 0, nil, &size, &v) == noErr ? v : nil
    }
    static func pid(_ obj: AudioObjectID) -> pid_t? {
        var a = AudioObjectPropertyAddress(mSelector: kAudioProcessPropertyPID, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var v: pid_t = 0; var size = UInt32(MemoryLayout<pid_t>.size)
        return AudioObjectGetPropertyData(obj, &a, 0, nil, &size, &v) == noErr ? v : nil
    }
    static func defaultDevice(_ sel: AudioObjectPropertySelector) -> AudioDeviceID {
        var id = AudioDeviceID(0); var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        var a = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &size, &id)
        return id
    }
    static func processObject(for pid: pid_t) -> AudioObjectID? {
        var a = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyTranslatePIDToProcessObject, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var p = pid; var obj = AudioObjectID(0); var size = UInt32(MemoryLayout<AudioObjectID>.size)
        let st = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, UInt32(MemoryLayout<pid_t>.size), &p, &size, &obj)
        return st == noErr && obj != kAudioObjectUnknown ? obj : nil
    }
    /// Every process Core Audio knows about.
    static func processObjects() -> [AudioObjectID] {
        var a = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyProcessObjectList, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var size = UInt32(0)
        guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &size) == noErr, size > 0 else { return [] }
        var list = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &size, &list) == noErr else { return [] }
        return list
    }
}

/// System audio via a Core Audio process tap (macOS 14.2+): a private, unmuted global tap of every process
/// except Wizard itself, attached to a private aggregate device on the default output.
@available(macOS 14.2, *)
final class ProcessTapSource: CaptureSource {
    let kind = "process-tap"
    private var tapID = AudioObjectID(kAudioObjectUnknown)
    private var aggID = AudioObjectID(kAudioObjectUnknown)
    private var procID: AudioDeviceIOProcID?
    private let queue = DispatchQueue(label: "wizard.meetings.tap", qos: .userInitiated)      // IOProc
    private let ctl = DispatchQueue(label: "wizard.meetings.tapctl")                           // rebuilds (never the IO queue)
    private var outputListener: AudioObjectPropertyListenerBlock?
    private var onBuffer: ((AVAudioPCMBuffer) -> Void)?

    func start(onBuffer: @escaping (AVAudioPCMBuffer) -> Void) throws {
        self.onBuffer = onBuffer
        try build()
        // Follow the default output (AirPods connected mid-call etc.).
        var a = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultOutputDevice, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        let l: AudioObjectPropertyListenerBlock = { [weak self] _, _ in
            guard let self, self.onBuffer != nil else { return }
            MeetingLog.log("default output changed; rebuilding the call-audio tap")
            self.teardown(); try? self.build()
        }
        outputListener = l
        AudioObjectAddPropertyListenerBlock(AudioObjectID(kAudioObjectSystemObject), &a, ctl, l)
    }

    private func build() throws {
        let out = CoreAudioUtil.defaultDevice(kAudioHardwarePropertyDefaultOutputDevice)
        guard let outUID = CoreAudioUtil.string(out, kAudioDevicePropertyDeviceUID) else { throw MeetingRecorder.err("No audio output device.") }
        let me = CoreAudioUtil.processObject(for: getpid()).map { [$0] } ?? []
        // Only what the Mac plays on the current output device (the call), never virtual devices the mic path might use.
        let desc = CATapDescription(excludingProcesses: me, deviceUID: outUID, stream: 0)
        desc.name = "Wizard meeting audio"
        desc.isPrivate = true
        desc.muteBehavior = .unmuted
        var tap = AudioObjectID(kAudioObjectUnknown)
        var st = AudioHardwareCreateProcessTap(desc, &tap)
        guard st == noErr else { throw MeetingRecorder.err("Couldn't tap call audio (\(st)).") }
        tapID = tap

        var a = AudioObjectPropertyAddress(mSelector: kAudioTapPropertyFormat, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var asbd = AudioStreamBasicDescription(); var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        st = AudioObjectGetPropertyData(tap, &a, 0, nil, &size, &asbd)
        guard st == noErr, let fmt = AVAudioFormat(streamDescription: &asbd) else { teardown(); throw MeetingRecorder.err("Call audio format unavailable (\(st)).") }

        let agg: [String: Any] = [
            kAudioAggregateDeviceNameKey: "Wizard Meeting Tap",
            kAudioAggregateDeviceUIDKey: "org.humanitylabs.wizard.meetingtap.\(UUID().uuidString)",
            kAudioAggregateDeviceMainSubDeviceKey: outUID,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outUID]],
            kAudioAggregateDeviceTapListKey: [[kAudioSubTapDriftCompensationKey: true, kAudioSubTapUIDKey: desc.uuid.uuidString]],
        ]
        var aggDev = AudioObjectID(kAudioObjectUnknown)
        st = AudioHardwareCreateAggregateDevice(agg as CFDictionary, &aggDev)
        guard st == noErr else { teardown(); throw MeetingRecorder.err("Couldn't create the call-audio device (\(st)).") }
        aggID = aggDev
        st = AudioDeviceCreateIOProcIDWithBlock(&procID, aggDev, queue) { [weak self] _, input, _, _, _ in
            guard let buf = AVAudioPCMBuffer(pcmFormat: fmt, bufferListNoCopy: input, deallocator: nil) else { return }
            self?.onBuffer?(buf)
        }
        guard st == noErr else { teardown(); throw MeetingRecorder.err("Couldn't read call audio (\(st)).") }
        st = AudioDeviceStart(aggDev, procID)
        guard st == noErr else { teardown(); throw MeetingRecorder.err("Couldn't start call audio (\(st)).") }
        MeetingLog.log("call-audio tap running on \(outUID) at \(Int(fmt.sampleRate)) Hz × \(fmt.channelCount)")
    }

    private func teardown() {
        if aggID != kAudioObjectUnknown {
            AudioDeviceStop(aggID, procID)
            if let p = procID { AudioDeviceDestroyIOProcID(aggID, p) }
            AudioHardwareDestroyAggregateDevice(aggID)
        }
        if tapID != kAudioObjectUnknown { AudioHardwareDestroyProcessTap(tapID) }
        aggID = AudioObjectID(kAudioObjectUnknown); tapID = AudioObjectID(kAudioObjectUnknown); procID = nil
    }

    func stop() {
        if let l = outputListener {
            var a = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultOutputDevice, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
            AudioObjectRemovePropertyListenerBlock(AudioObjectID(kAudioObjectSystemObject), &a, ctl, l)
        }
        outputListener = nil
        onBuffer = nil
        ctl.sync { teardown() }
    }
}

/// Fallback: ScreenCaptureKit system audio (needs Screen Recording permission).
final class SCKAudioSource: NSObject, CaptureSource, SCStreamOutput, SCStreamDelegate {
    let kind = "screencapturekit"
    private var stream: SCStream?
    private var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    private let queue = DispatchQueue(label: "wizard.meetings.sck")

    func start(onBuffer: @escaping (AVAudioPCMBuffer) -> Void) throws {
        self.onBuffer = onBuffer
        let sem = DispatchSemaphore(value: 0)
        var failure: Error?
        SCShareableContent.getExcludingDesktopWindows(false, onScreenWindowsOnly: true) { content, err in
            defer { sem.signal() }
            guard let display = content?.displays.first else { failure = err ?? MeetingRecorder.err("No display for call audio."); return }
            let cfg = SCStreamConfiguration()
            cfg.capturesAudio = true; cfg.excludesCurrentProcessAudio = true
            cfg.sampleRate = 48_000; cfg.channelCount = 2
            cfg.width = 2; cfg.height = 2; cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
            let s = SCStream(filter: SCContentFilter(display: display, excludingWindows: []), configuration: cfg, delegate: self)
            do { try s.addStreamOutput(self, type: .audio, sampleHandlerQueue: self.queue) } catch { failure = error; return }
            self.stream = s
        }
        guard sem.wait(timeout: .now() + 10) == .success else { throw MeetingRecorder.err("Screen audio didn't answer.") }
        if let failure { throw failure }
        let sem2 = DispatchSemaphore(value: 0)
        stream?.startCapture { err in failure = err; sem2.signal() }
        _ = sem2.wait(timeout: .now() + 10)
        if let failure { throw failure }
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, let fd = sb.formatDescription,
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fd), let fmt = AVAudioFormat(streamDescription: asbd) else { return }
        try? sb.withAudioBufferList { abl, _ in
            if let buf = AVAudioPCMBuffer(pcmFormat: fmt, bufferListNoCopy: abl.unsafePointer, deallocator: nil) { onBuffer?(buf) }
        }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) { MeetingLog.log("screen audio stopped: \(error.localizedDescription)") }
    func stop() { onBuffer = nil; stream?.stopCapture(completionHandler: nil); stream = nil }
}

// MARK: - Track

final class CaptureTrack {
    let source: String          // "me" | "them"
    let meetingId: String
    let chunker = PCMChunker()
    let q: DispatchQueue
    var input: CaptureSource?
    var paused = false
    private(set) var seq: Int
    private(set) var sampleOffset: Int   // samples already on the server timeline
    private(set) var chunks = 0
    private(set) var error: String?

    init(source: String, meetingId: String, seqBase: Int, offsetMs: Int) {
        self.source = source; self.meetingId = meetingId; seq = seqBase; sampleOffset = offsetMs * 16
        q = DispatchQueue(label: "wizard.meetings.\(source)", qos: .userInitiated)
        chunker.onChunk = { [weak self] s in
            guard let self else { return }
            MeetingSpool.shared.write(meetingId: meetingId, source: source, seq: self.seq, startMs: self.sampleOffset / 16, samples: s)
            self.seq += 1; self.chunks += 1; self.sampleOffset += s.count
        }
    }

    func start(_ input: CaptureSource) throws {
        self.input = input
        try input.start { [weak self] buf in
            guard let self else { return }
            // Tap/SCK buffers are only valid inside the callback: convert synchronously.
            self.q.sync { if !self.paused { self.chunker.feed(buf) } }
        }
    }
    func stop() { input?.stop(); input = nil; q.sync { chunker.flush() } }
    func fail(_ e: String) { error = e }

    var stats: [String: Any] {
        ["source": source, "input": input?.kind ?? "off", "chunks": chunks, "level": chunker.level, "buffers": chunker.buffersIn,
         "lastBufferAgeMs": chunker.lastBufferAt.map { Int(-$0.timeIntervalSinceNow * 1000) } ?? -1, "error": error ?? NSNull()]
    }
}

// MARK: - Recorder

final class MeetingRecorder {
    static let shared = MeetingRecorder()
    static func err(_ s: String) -> NSError { NSError(domain: "WizardMeetings", code: 1, userInfo: [NSLocalizedDescriptionKey: s]) }

    struct Session {
        var meetingId: String; var apiBase: String; var title: String
        var startedAt: Date; var pausedAt: Date?; var pausedTotal: TimeInterval = 0
        var me: CaptureTrack; var them: CaptureTrack?
        var notes: [String] = []
    }
    private(set) var session: Session?
    private(set) var stopping = false
    var onChange: () -> Void = {}

    var isRecording: Bool { session != nil }
    var elapsed: TimeInterval {
        guard let s = session else { return 0 }
        return (s.pausedAt ?? Date()).timeIntervalSince(s.startedAt) - s.pausedTotal
    }
    var levels: (me: Float, them: Float) {
        guard let s = session, s.pausedAt == nil else { return (0, 0) }
        return (s.me.chunker.level, s.them?.chunker.level ?? 0)
    }

    static func micAuthorized(_ done: @escaping (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: done(true)
        case .notDetermined: AVCaptureDevice.requestAccess(for: .audio) { ok in DispatchQueue.main.async { done(ok) } }
        default: done(false)
        }
    }

    /// apiBase = the active Wizard's Mizel API root, e.g. https://host/meetings/api
    func start(meetingId: String, apiBase: String, title: String, includeSystemAudio: Bool, done: @escaping (Error?) -> Void) {
        if let s = session {
            done(s.meetingId == meetingId ? nil : Self.err("Already recording “\(s.title)”. Stop it first.")); return
        }
        Self.micAuthorized { ok in
            guard ok else { done(Self.err("Microphone access is off for Wizard. Turn it on in System Settings → Privacy & Security → Microphone.")); return }
            // Continue an existing meeting's timeline instead of overwriting chunk numbers.
            self.serverTracks(apiBase: apiBase, meetingId: meetingId) { seqBase, offsetMs, serverTitle in
                let title = serverTitle ?? title
                MeetingSpool.shared.open(.init(meetingId: meetingId, apiBase: apiBase, title: title, createdAt: Date(), done: false))
                let me = CaptureTrack(source: "me", meetingId: meetingId, seqBase: seqBase["me"] ?? 0, offsetMs: offsetMs)
                do { try me.start(MicSource()) } catch { done(error); return }
                var them: CaptureTrack?
                if includeSystemAudio {
                    let t = CaptureTrack(source: "them", meetingId: meetingId, seqBase: seqBase["them"] ?? 0, offsetMs: offsetMs)
                    var started = false
                    if #available(macOS 14.2, *), !UserDefaults.standard.bool(forKey: "MeetingsForceSCK") {
                        do { try t.start(ProcessTapSource()); started = true } catch { MeetingLog.log("process tap failed: \(error.localizedDescription); trying ScreenCaptureKit") }
                    }
                    if !started {
                        do { try t.start(SCKAudioSource()); started = true } catch { t.fail(error.localizedDescription); MeetingLog.log("call audio unavailable: \(error.localizedDescription)") }
                    }
                    them = t
                }
                self.session = Session(meetingId: meetingId, apiBase: apiBase, title: title, startedAt: Date(), me: me, them: them)
                MeetingLog.log("recording \(meetingId) (\(title)) me=\(me.input?.kind ?? "-") them=\(them?.input?.kind ?? "off") seqBase=\(seqBase) offset=\(offsetMs)ms")
                self.onChange()
                done(nil)
            }
        }
    }

    private func serverTracks(apiBase: String, meetingId: String, done: @escaping ([String: Int], Int, String?) -> Void) {
        guard let url = URL(string: "\(apiBase)/meetings/\(meetingId)") else { done([:], 0, nil); return }
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 6)
        req.httpMethod = "GET"
        URLSession.shared.dataTask(with: req) { data, _, _ in
            var base: [String: Int] = [:]; var offset = 0; var title: String?
            if let data, let m = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                for t in ((m["audio"] as? [String: Any])?["tracks"] as? [[String: Any]]) ?? [] {
                    if let s = t["source"] as? String, let c = t["chunks"] as? Int { base[s] = c }
                }
                offset = max((m["duration_ms"] as? Int) ?? 0, (base["me"] ?? 0) * 5000, (base["them"] ?? 0) * 5000)
                title = m["title"] as? String
            }
            DispatchQueue.main.async { done(base, offset, title) }
        }.resume()
    }

    func pause() { guard var s = session, s.pausedAt == nil else { return }; s.pausedAt = Date(); s.me.paused = true; s.them?.paused = true; session = s; onChange() }
    func resume() {
        guard var s = session, let p = s.pausedAt else { return }
        s.pausedTotal += Date().timeIntervalSince(p); s.pausedAt = nil; s.me.paused = false; s.them?.paused = false; session = s; onChange()
    }

    /// Stop capture, deliver every chunk, then tell the server the meeting ended (unless the view will).
    func stop(finalize: Bool, done: @escaping ([String: Any]) -> Void) {
        guard let s = session, !stopping else { done(status()); return }
        stopping = true; onChange()
        DispatchQueue.global(qos: .userInitiated).async {
            s.me.stop(); s.them?.stop()
            DispatchQueue.main.async {
                MeetingSpool.shared.markDone(s.meetingId)
                MeetingSpool.shared.drain(s.meetingId, timeout: 25) { left in
                    let summary: [String: Any] = ["meetingId": s.meetingId, "me": s.me.stats, "them": s.them?.stats ?? NSNull(),
                                                  "pendingUploads": left, "durationMs": Int(self.elapsed * 1000)]
                    MeetingLog.log("stopped \(s.meetingId): me \(s.me.chunks) chunks, them \(s.them?.chunks ?? 0) chunks, \(left) still queued")
                    let finish = {
                        self.session = nil; self.stopping = false; self.onChange(); done(summary)
                    }
                    guard finalize, let url = URL(string: "\(s.apiBase)/meetings/\(s.meetingId)/stop") else { finish(); return }
                    var req = URLRequest(url: url, timeoutInterval: 15); req.httpMethod = "POST"
                    URLSession.shared.dataTask(with: req) { _, _, _ in DispatchQueue.main.async(execute: finish) }.resume()
                }
            }
        }
    }

    func addNote(_ text: String) {
        guard var s = session else { return }
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines); guard !t.isEmpty else { return }
        let stamp = String(format: "%d:%02d", Int(elapsed) / 60, Int(elapsed) % 60)
        s.notes.append(t); session = s
        // Append to the meeting's notepad with the server's optimistic-concurrency rev.
        guard let get = URL(string: "\(s.apiBase)/meetings/\(s.meetingId)") else { return }
        URLSession.shared.dataTask(with: get) { data, _, _ in
            guard let data, let m = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            let notes = (m["notes"] as? String) ?? ""; let rev = (m["notes_rev"] as? Int) ?? 0
            let line = "- \(t) (\(stamp))"
            let body: [String: Any] = ["notes": notes.isEmpty ? line : notes.hasSuffix("\n") ? notes + line : notes + "\n" + line, "base_rev": rev]
            guard let put = URL(string: "\(s.apiBase)/meetings/\(s.meetingId)/notes"), let b = try? JSONSerialization.data(withJSONObject: body) else { return }
            var req = URLRequest(url: put); req.httpMethod = "PUT"; req.httpBody = b; req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            URLSession.shared.dataTask(with: req) { _, resp, _ in
                MeetingLog.log("quick note saved (\((resp as? HTTPURLResponse)?.statusCode ?? 0))")
            }.resume()
        }.resume()
    }

    /// Create a meeting on the active Wizard, then record it (menu, pop-up, floating recorder).
    func startNew(origin: URL, title: String?, calendarEventId: String?, done: @escaping (Error?) -> Void) {
        let apiBase = origin.appendingPathComponent("meetings/api").absoluteString
        guard let url = URL(string: apiBase + "/meetings") else { done(Self.err("Bad Wizard address.")); return }
        var body: [String: Any] = [:]
        if let title { body["title"] = title }
        if let calendarEventId { body["calendar_event_id"] = calendarEventId }
        var req = URLRequest(url: url, timeoutInterval: 15); req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type"); req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req) { data, resp, err in
            DispatchQueue.main.async {
                guard (resp as? HTTPURLResponse)?.statusCode == 200, let data,
                      let m = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let id = m["id"] as? String else {
                    done(err ?? Self.err("Mizel couldn't create the meeting (\((resp as? HTTPURLResponse)?.statusCode ?? 0)).")); return
                }
                self.start(meetingId: id, apiBase: apiBase, title: (m["title"] as? String) ?? "Meeting", includeSystemAudio: true, done: done)
            }
        }.resume()
    }

    func status() -> [String: Any] {
        guard let s = session else {
            return ["recording": false, "pendingUploads": MeetingSpool.shared.pendingTotal, "uploaded": MeetingSpool.shared.uploaded]
        }
        let l = levels
        return ["recording": true, "stopping": stopping, "paused": s.pausedAt != nil, "meetingId": s.meetingId, "title": s.title,
                "elapsedMs": Int(elapsed * 1000), "levels": ["me": l.me, "them": l.them],
                "tracks": [s.me.stats, s.them?.stats].compactMap { $0 },
                "pendingUploads": MeetingSpool.shared.pending(s.meetingId), "uploaded": MeetingSpool.shared.uploaded,
                "uploadError": MeetingSpool.shared.lastError ?? NSNull()]
    }
}
