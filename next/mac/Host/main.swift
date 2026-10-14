import AppKit
import Darwin
import Virtualization

// Wizard Host: the menu-bar service that runs Wizard OS (a lightweight Linux VM on
// Apple's Virtualization framework) and keeps it running after the Wizard window closes.

func log(_ message: String) {
    let line = "\(ISO8601DateFormatter().string(from: Date())) \(message)\n"
    FileHandle.standardError.write(line.data(using: .utf8)!)
    let url = WizardShared.logsDir.appendingPathComponent("host.log")
    if let h = try? FileHandle(forWritingTo: url) {
        h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); try? h.close()
    } else {
        try? line.data(using: .utf8)!.write(to: url)
    }
}

// MARK: - Byte pump between a loopback TCP socket and a guest vsock connection

final class Pipe2 {
    let tcp: Int32
    let conn: VZVirtioSocketConnection
    private var remaining = 2
    private let lock = NSLock()
    init(tcp: Int32, conn: VZVirtioSocketConnection) { self.tcp = tcp; self.conn = conn }

    func run() {
        let v = conn.fileDescriptor
        spawn(from: tcp, to: v)
        spawn(from: v, to: tcp)
    }

    private func spawn(from a: Int32, to b: Int32) {
        let t = Thread { [self] in
            var buf = [UInt8](repeating: 0, count: 65536)
            outer: while true {
                let n = buf.withUnsafeMutableBytes { read(a, $0.baseAddress, 65536) }
                if n <= 0 { break }
                var off = 0
                while off < n {
                    let w = buf.withUnsafeBytes { write(b, $0.baseAddress! + off, n - off) }
                    if w <= 0 { break outer }
                    off += w
                }
            }
            shutdown(b, SHUT_WR)
            finish()
        }
        t.stackSize = 256 * 1024
        t.start()
    }

    private func finish() {
        lock.lock(); remaining -= 1; let done = remaining == 0; lock.unlock()
        if done { close(tcp); conn.close() }
    }
}

final class LoopbackBridge {
    let hostPort: UInt16
    let guestPort: UInt32
    weak var vm: VMController?
    private var fd: Int32 = -1

    init(hostPort: UInt16, guestPort: UInt32, vm: VMController) {
        self.hostPort = hostPort; self.guestPort = guestPort; self.vm = vm
    }

    func start() {
        fd = socket(AF_INET, SOCK_STREAM, 0)
        var yes: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = hostPort.bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let ok = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        guard ok == 0, listen(fd, 64) == 0 else {
            log("bridge \(hostPort): bind/listen failed errno=\(errno)"); return
        }
        log("bridge 127.0.0.1:\(hostPort) -> guest vsock \(guestPort)")
        let t = Thread { [self] in
            while true {
                let c = accept(fd, nil, nil)
                if c < 0 { continue }
                var one: Int32 = 1
                setsockopt(c, IPPROTO_TCP, TCP_NODELAY, &one, socklen_t(MemoryLayout<Int32>.size))
                DispatchQueue.main.async { self.connect(c) }
            }
        }
        t.start()
    }

    private func connect(_ c: Int32) {
        guard let dev = vm?.socketDevice else { close(c); return }
        dev.connect(toPort: guestPort) { result in
            switch result {
            case .success(let conn): Pipe2(tcp: c, conn: conn).run()
            case .failure: close(c)
            }
        }
    }
}

// MARK: - Wizard OS virtual machine

final class VMController: NSObject, VZVirtualMachineDelegate, VZVirtioSocketListenerDelegate {
    enum State: String { case notInstalled, stopped, starting, running, stopping, error }

    private(set) var state: State = .stopped { didSet { writeStatus(); onChange?() } }
    var onChange: (() -> Void)?
    private var vm: VZVirtualMachine?
    private(set) var socketDevice: VZVirtioSocketDevice?
    private let openURLListener = VZVirtioSocketListener()
    private var bootStartedAt: Date?
    private var readyAt: Date?
    private var lastError: String?
    private var heldConnections: [VZVirtioSocketConnection] = []

    override init() {
        super.init()
        openURLListener.delegate = self
        state = WizardShared.osInstalled ? .stopped : .notInstalled
    }

    var bootSeconds: Double? {
        guard let a = bootStartedAt, let b = readyAt else { return nil }
        return b.timeIntervalSince(a)
    }

    func start() {
        guard vm == nil || state == .stopped || state == .error || state == .notInstalled else { return }
        guard WizardShared.osInstalled else { state = .notInstalled; return }
        if let free = Self.freeBytes(), free < Self.minFreeToStart {
            fail(String(format: "Not enough free space on this Mac to run Wizard OS safely (%.1f GB free, needs %.0f GB).",
                        Double(free) / 1e9, Double(Self.minFreeToStart) / 1e9))
            return
        }
        do {
            let config = try makeConfiguration()
            let machine = VZVirtualMachine(configuration: config)
            machine.delegate = self
            vm = machine
            socketDevice = machine.socketDevices.first as? VZVirtioSocketDevice
            socketDevice?.setSocketListener(openURLListener, forPort: WizardShared.hostOpenURLPort)
            bootStartedAt = Date(); readyAt = nil; lastError = nil
            state = .starting
            log("starting Wizard OS (cpus=\(config.cpuCount) mem=\(config.memorySize >> 20)MiB)")
            machine.start { [weak self] result in
                guard let self else { return }
                if case .failure(let error) = result {
                    self.fail("VM failed to start: \(error.localizedDescription)")
                } else {
                    self.waitUntilReady()
                    self.watchDiskSpace()
                }
            }
        } catch {
            fail("VM configuration failed: \(error.localizedDescription)")
        }
    }

    // Wizard OS's disk is a sparse file: when the Mac's volume fills up, its writes fail and the guest file system is
    // damaged. Refuse to start below 2 GB free; shut down cleanly below 1 GB while running.
    static let minFreeToStart: Int64 = 2_000_000_000
    static let minFreeRunning: Int64 = 1_000_000_000
    static func freeBytes() -> Int64? {
        let v = try? WizardShared.osDir.resourceValues(forKeys: [.volumeAvailableCapacityKey])
        return v?.volumeAvailableCapacity.map(Int64.init)
    }
    private var diskTimer: Timer?
    private func watchDiskSpace() {
        diskTimer?.invalidate()
        diskTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] t in
            guard let self, self.state == .running || self.state == .starting else { t.invalidate(); return }
            if let free = Self.freeBytes(), free < Self.minFreeRunning {
                log(String(format: "only %.2f GB free on this Mac; stopping Wizard OS to protect its disk", Double(free) / 1e9))
                self.stop { [weak self] in self?.lastError = "Stopped: this Mac is almost out of disk space."; self?.state = .error }
            }
        }
    }

    private func fail(_ message: String) {
        log(message); lastError = message; vm = nil; socketDevice = nil; state = .error
    }

    private func waitUntilReady() {
        let started = bootStartedAt
        func poll() {
            guard state == .starting, started == bootStartedAt else { return }
            WizardShared.probeReady { ok in
                DispatchQueue.main.async {
                    if ok {
                        self.readyAt = Date()
                        log(String(format: "Wizard OS ready in %.2fs", self.bootSeconds ?? -1))
                        self.state = .running
                    } else {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2, execute: poll)
                    }
                }
            }
        }
        poll()
    }

    func stop(completion: (() -> Void)? = nil) {
        guard let machine = vm, state == .running || state == .starting else { completion?(); return }
        state = .stopping
        log("stopping Wizard OS")
        var finished = false
        let done = { [weak self] in
            guard !finished else { return }
            finished = true
            self?.vm = nil; self?.socketDevice = nil
            self?.state = .stopped
            completion?()
        }
        stopCompletion = done
        // Ask Wizard OS to power off cleanly; force-stop if it hasn't within 90 s (Docker stops every app first).
        socketDevice?.connect(toPort: WizardShared.guestControlPort) { result in
            if case .success(let conn) = result {
                _ = "poweroff\n".withCString { write(conn.fileDescriptor, $0, 9) }
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { conn.close() }
            } else if machine.canRequestStop {
                try? machine.requestStop()
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 90) {
            guard !finished else { return }
            log("clean shutdown timed out; forcing stop")
            machine.stop { _ in DispatchQueue.main.async(execute: done) }
        }
    }
    private var stopCompletion: (() -> Void)?

    func restart() { stop { [weak self] in self?.start() } }

    // VZVirtualMachineDelegate
    func guestDidStop(_ virtualMachine: VZVirtualMachine) {
        DispatchQueue.main.async {
            log("Wizard OS powered off")
            if let c = self.stopCompletion { self.stopCompletion = nil; c() }
            else { self.vm = nil; self.socketDevice = nil; self.state = .stopped }
        }
    }
    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        DispatchQueue.main.async { self.fail("Wizard OS stopped: \(error.localizedDescription)") }
    }

    // Guest -> Mac: open https links in the default browser.
    func listener(_ listener: VZVirtioSocketListener, shouldAcceptNewConnection connection: VZVirtioSocketConnection,
                  from socketDevice: VZVirtioSocketDevice) -> Bool {
        heldConnections.append(connection)
        let fd = connection.fileDescriptor
        DispatchQueue.global().async {
            var buf = [UInt8](repeating: 0, count: 2100)
            let n = buf.withUnsafeMutableBytes { read(fd, $0.baseAddress, 2100) }
            var reply = "unavailable\n"
            if n > 0, let line = String(bytes: buf[0..<n], encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
               line.hasPrefix("open-url "), let url = URL(string: String(line.dropFirst(9))),
               url.scheme == "https", url.host != nil {
                _ = DispatchQueue.main.sync { NSWorkspace.shared.open(url) }
                reply = "opened\n"
                log("opened link from Wizard OS: \(url.host ?? "")")
            }
            _ = reply.withCString { write(fd, $0, strlen($0)) }
            DispatchQueue.main.async {
                connection.close()
                self.heldConnections.removeAll { $0 === connection }
            }
        }
        return true
    }

    private func makeConfiguration() throws -> VZVirtualMachineConfiguration {
        let dir = WizardShared.osDir
        let manifest = (try? JSONSerialization.jsonObject(with: Data(contentsOf: dir.appendingPathComponent("manifest.json")))) as? [String: Any] ?? [:]
        let boot = VZLinuxBootLoader(kernelURL: dir.appendingPathComponent("boot/vmlinux"))
        boot.initialRamdiskURL = dir.appendingPathComponent("boot/initrd")
        boot.commandLine = (manifest["cmdline"] as? String) ?? "console=hvc0 root=/dev/vda rw quiet"
        // Developer/QA only: with ~/Library/Application Support/Wizard/dev-shell present, the guest opens a root shell on
        // vsock 9200, bridged to 127.0.0.1:48000 (used by mac/qa-guest.sh for `wam doctor` and friends).
        if WizardShared.devShell { boot.commandLine += " wizard.dev=1" }

        let c = VZVirtualMachineConfiguration()
        c.bootLoader = boot
        let cores = ProcessInfo.processInfo.processorCount
        c.cpuCount = max(VZVirtualMachineConfiguration.minimumAllowedCPUCount, min(4, max(2, cores / 2)))
        // Wizard OS 0.2 runs Docker, Runtipi and the default apps: give it the manifest's memory (6 GiB) on Macs with
        // 16 GB or more, 4 GiB otherwise. Pages the guest never touches cost the Mac nothing.
        let physical = ProcessInfo.processInfo.physicalMemory
        let wantMiB = UInt64((manifest["memoryMiB"] as? Int) ?? 4096)
        let want: UInt64 = physical >= (16 << 30) ? (wantMiB << 20) : (min(wantMiB, 4096) << 20)
        c.memorySize = min(max(want, VZVirtualMachineConfiguration.minimumAllowedMemorySize), VZVirtualMachineConfiguration.maximumAllowedMemorySize)

        let disk = try VZDiskImageStorageDeviceAttachment(url: dir.appendingPathComponent("disk.img"), readOnly: false,
                                                          cachingMode: .automatic, synchronizationMode: .full)
        c.storageDevices = [VZVirtioBlockDeviceConfiguration(attachment: disk)]

        let net = VZVirtioNetworkDeviceConfiguration()
        net.attachment = VZNATNetworkDeviceAttachment()
        net.macAddress = stableMAC()
        c.networkDevices = [net]

        c.socketDevices = [VZVirtioSocketDeviceConfiguration()]
        c.entropyDevices = [VZVirtioEntropyDeviceConfiguration()]
        c.memoryBalloonDevices = [VZVirtioTraditionalMemoryBalloonDeviceConfiguration()]

        // The Wizard's files folder (~/Wizard by default) is the guest's Runtipi media root (virtio-fs tag wizard-files).
        if let folder = WizardShared.filesFolder {
            try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let fs = VZVirtioFileSystemDeviceConfiguration(tag: WizardShared.filesShareTag)
            fs.share = VZSingleDirectoryShare(directory: VZSharedDirectory(url: folder, readOnly: false))
            c.directorySharingDevices = [fs]
            log("sharing \(folder.path) as \(WizardShared.filesShareTag)")
        }

        let consoleURL = WizardShared.logsDir.appendingPathComponent("console.log")
        FileManager.default.createFile(atPath: consoleURL.path, contents: nil)
        let serial = VZVirtioConsoleDeviceSerialPortConfiguration()
        serial.attachment = VZFileHandleSerialPortAttachment(fileHandleForReading: nil,
                                                             fileHandleForWriting: try FileHandle(forWritingTo: consoleURL))
        c.serialPorts = [serial]
        try c.validate()
        return c
    }

    private func stableMAC() -> VZMACAddress {
        let url = WizardShared.osDir.appendingPathComponent("mac-address")
        if let s = try? String(contentsOf: url, encoding: .utf8), let m = VZMACAddress(string: s.trimmingCharacters(in: .whitespacesAndNewlines)) {
            return m
        }
        let m = VZMACAddress.randomLocallyAdministered()
        try? m.string.write(to: url, atomically: true, encoding: .utf8)
        return m
    }

    private func writeStatus() {
        var s: [String: Any] = ["state": state.rawValue, "pid": getpid(), "updatedAt": Date().timeIntervalSince1970]
        if let b = bootStartedAt { s["bootStartedAt"] = b.timeIntervalSince1970 }
        if let r = readyAt { s["readyAt"] = r.timeIntervalSince1970 }
        if let secs = bootSeconds { s["bootSeconds"] = secs }
        if let e = lastError { s["error"] = e }
        if let d = try? JSONSerialization.data(withJSONObject: s, options: [.prettyPrinted, .sortedKeys]) {
            try? d.write(to: WizardShared.statusFile, options: .atomic)
        }
    }
}

// MARK: - Menu bar

final class HostDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let vm = VMController()
    var bridges: [LoopbackBridge] = []
    var item: NSStatusItem!
    let statusLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    var quitting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        signal(SIGPIPE, SIG_IGN)
        try? FileManager.default.createDirectory(at: WizardShared.logsDir, withIntermediateDirectories: true)
        let mine = ProcessInfo.processInfo.processIdentifier
        if NSRunningApplication.runningApplications(withBundleIdentifier: WizardShared.hostBundleID)
            .contains(where: { $0.processIdentifier != mine }) {
            log("another Wizard Host is running; exiting"); exit(0)
        }
        log("Wizard Host launched (pid \(mine))")

        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = WizardBrand.menuBarImage()
        let menu = NSMenu(); menu.delegate = self
        statusLine.isEnabled = false
        menu.addItem(statusLine)
        menu.addItem(.separator())
        menu.addItem(withTitle: "Open Wizard", action: #selector(openWizard), keyEquivalent: "o").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Restart Wizard OS", action: #selector(restartOS), keyEquivalent: "").target = self
        menu.addItem(withTitle: "Stop Wizard OS", action: #selector(stopOS), keyEquivalent: "").target = self
        menu.addItem(withTitle: "Start Wizard OS", action: #selector(startOS), keyEquivalent: "").target = self
        menu.addItem(withTitle: "Show Logs", action: #selector(showLogs), keyEquivalent: "").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Wizard (stops Wizard OS)", action: #selector(quitAll), keyEquivalent: "q").target = self
        item.menu = menu

        // One Wizard icon: Wizard.app owns it while it runs; this one only shows when the app isn't running.
        let ws = NSWorkspace.shared.notificationCenter
        for name in [NSWorkspace.didLaunchApplicationNotification, NSWorkspace.didTerminateApplicationNotification] {
            ws.addObserver(forName: name, object: nil, queue: .main) { [weak self] n in
                let app = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
                if app?.bundleIdentifier == WizardShared.appBundleID { self?.syncIconVisibility() }
            }
        }
        syncIconVisibility()

        vm.onChange = { [weak self] in self?.refresh() }
        bridges = [LoopbackBridge(hostPort: WizardShared.uxPort, guestPort: WizardShared.guestUXPort, vm: vm),
                   LoopbackBridge(hostPort: WizardShared.setupPort, guestPort: WizardShared.guestSetupPort, vm: vm)]
        if WizardShared.devShell {
            bridges.append(LoopbackBridge(hostPort: WizardShared.devShellPort, guestPort: WizardShared.guestDevShellPort, vm: vm))
        }
        bridges.forEach { $0.start() }

        DistributedNotificationCenter.default().addObserver(self, selector: #selector(command(_:)),
            name: Notification.Name("org.humanitylabs.wizard.mvp.host.command"), object: nil, suspensionBehavior: .deliverImmediately)
        refresh()
        vm.start()
    }

    @objc func command(_ n: Notification) {
        switch n.object as? String {
        case "start": vm.start()
        case "stop": vm.stop()
        case "restart": vm.restart()
        case "quit": quitAll()
        default: break
        }
    }

    func refresh() {
        let text: String
        switch vm.state {
        case .notInstalled: text = "Wizard OS is not installed"
        case .stopped: text = "Wizard OS is stopped"
        case .starting: text = "Wizard OS is starting…"
        case .running: text = vm.bootSeconds.map { String(format: "Wizard is running (woke in %.1fs)", $0) } ?? "Wizard is running"
        case .stopping: text = "Wizard OS is shutting down…"
        case .error: text = "Wizard OS hit a problem — see logs"
        }
        statusLine.title = text
        item?.button?.toolTip = text
        item?.button?.appearsDisabled = vm.state != .running
    }

    func syncIconVisibility() {
        let appRunning = !NSRunningApplication.runningApplications(withBundleIdentifier: WizardShared.appBundleID).isEmpty
        item?.isVisible = !appRunning
        iconVisible = !appRunning
        writeIconState()
    }
    var iconVisible = true
    private func writeIconState() {
        let f = WizardShared.supportDir.appendingPathComponent("host-icon.json")
        let s: [String: Any] = ["iconVisible": iconVisible, "updatedAt": Date().timeIntervalSince1970,
            "brandAsset": "wizard-mark-white.png", "menuTemplate": item?.button?.image?.isTemplate ?? false,
            "menuSize": NSStringFromSize(item?.button?.image?.size ?? .zero)]
        if let d = try? JSONSerialization.data(withJSONObject: s) { try? d.write(to: f, options: .atomic) }
    }

    @objc func openWizard() {
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: WizardShared.appBundleID) {
            NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
        }
    }
    @objc func startOS() { vm.start() }
    @objc func stopOS() { vm.stop() }
    @objc func restartOS() { vm.restart() }
    @objc func showLogs() { NSWorkspace.shared.open(WizardShared.logsDir) }
    @objc func quitAll() { NSApp.terminate(nil) }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return .terminateNow }
        quitting = true
        vm.stop { NSApp.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }
}

let app = NSApplication.shared
let hostDelegate = HostDelegate()
app.delegate = hostDelegate
app.setActivationPolicy(.accessory)
app.run()
