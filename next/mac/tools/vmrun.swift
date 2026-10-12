import Darwin
import Foundation
import Virtualization

// vmrun: boot a Wizard OS disk headless on Virtualization.framework (no window, no app).
// Used on the build Mac to install Wizard OS inside a real VM and to time boots.
//
//   vmrun --kernel K --initrd I --disk D [--cmdline S] [--cpus N] [--mem MiB]
//         [--share tag=/path]... [--bridge hostPort:guestPort]... [--console FILE] [--timeout SECS]
//
// Exits 0 when the guest powers off, 2 on timeout (guest is force-stopped), 1 on error.

func die(_ s: String) -> Never { FileHandle.standardError.write("vmrun: \(s)\n".data(using: .utf8)!); exit(1) }
func note(_ s: String) {
    let t = String(format: "%.1f", Date().timeIntervalSince(started))
    FileHandle.standardError.write("vmrun [\(t)s] \(s)\n".data(using: .utf8)!)
}
let started = Date()

var kernel = "", initrd = "", disk = "", cmdline = "console=hvc0 root=/dev/vda rw"
var cpus = 4, memMiB = 4096, timeout = 0.0, console = ""
var shares: [(String, String)] = []
var bridges: [(UInt16, UInt32)] = []
var args = Array(CommandLine.arguments.dropFirst())
while !args.isEmpty {
    let a = args.removeFirst()
    func val() -> String { guard !args.isEmpty else { die("\(a) needs a value") }; return args.removeFirst() }
    switch a {
    case "--kernel": kernel = val()
    case "--initrd": initrd = val()
    case "--disk": disk = val()
    case "--cmdline": cmdline = val()
    case "--cpus": cpus = Int(val()) ?? 4
    case "--mem": memMiB = Int(val()) ?? 4096
    case "--timeout": timeout = Double(val()) ?? 0
    case "--console": console = val()
    case "--share":
        let p = val().split(separator: "=", maxSplits: 1).map(String.init)
        guard p.count == 2 else { die("--share tag=/path") }
        shares.append((p[0], p[1]))
    case "--bridge":
        let p = val().split(separator: ":").map(String.init)
        guard p.count == 2, let h = UInt16(p[0]), let g = UInt32(p[1]) else { die("--bridge hostPort:guestPort") }
        bridges.append((h, g))
    default: die("unknown argument \(a)")
    }
}
guard !kernel.isEmpty, !disk.isEmpty else { die("--kernel and --disk are required") }

let boot = VZLinuxBootLoader(kernelURL: URL(fileURLWithPath: kernel))
if !initrd.isEmpty { boot.initialRamdiskURL = URL(fileURLWithPath: initrd) }
boot.commandLine = cmdline
let c = VZVirtualMachineConfiguration()
c.bootLoader = boot
c.cpuCount = cpus
c.memorySize = UInt64(memMiB) << 20
do {
    let att = try VZDiskImageStorageDeviceAttachment(url: URL(fileURLWithPath: disk), readOnly: false,
                                                     cachingMode: .automatic, synchronizationMode: .full)
    c.storageDevices = [VZVirtioBlockDeviceConfiguration(attachment: att)]
    let net = VZVirtioNetworkDeviceConfiguration(); net.attachment = VZNATNetworkDeviceAttachment()
    c.networkDevices = [net]
    c.socketDevices = [VZVirtioSocketDeviceConfiguration()]
    c.entropyDevices = [VZVirtioEntropyDeviceConfiguration()]
    c.memoryBalloonDevices = [VZVirtioTraditionalMemoryBalloonDeviceConfiguration()]
    c.directorySharingDevices = shares.map { tag, path in
        let fs = VZVirtioFileSystemDeviceConfiguration(tag: tag)
        fs.share = VZSingleDirectoryShare(directory: VZSharedDirectory(url: URL(fileURLWithPath: path), readOnly: false))
        return fs
    }
    let serial = VZVirtioConsoleDeviceSerialPortConfiguration()
    let out: FileHandle
    if console.isEmpty { out = FileHandle.standardOutput } else {
        FileManager.default.createFile(atPath: console, contents: nil)
        out = try FileHandle(forWritingTo: URL(fileURLWithPath: console))
    }
    serial.attachment = VZFileHandleSerialPortAttachment(fileHandleForReading: nil, fileHandleForWriting: out)
    c.serialPorts = [serial]
    try c.validate()
} catch { die("configuration: \(error.localizedDescription)") }

final class Pump {
    static func run(_ tcp: Int32, _ conn: VZVirtioSocketConnection) {
        let v = conn.fileDescriptor
        var left = 2
        let lock = NSLock()
        func half(_ a: Int32, _ b: Int32) {
            Thread {
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
                lock.lock(); left -= 1; let done = left == 0; lock.unlock()
                if done { close(tcp); conn.close() }
            }.start()
        }
        half(tcp, v); half(v, tcp)
    }
}

final class Runner: NSObject, VZVirtualMachineDelegate {
    let vm: VZVirtualMachine
    init(_ c: VZVirtualMachineConfiguration) { vm = VZVirtualMachine(configuration: c); super.init(); vm.delegate = self }
    func guestDidStop(_ virtualMachine: VZVirtualMachine) {
        // Give the framework a moment to finish host-side writes before the process (and its XPC VM) goes away.
        note("guest powered off"); sync()
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { exit(0) }
    }
    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        note("guest stopped with error: \(error.localizedDescription)"); exit(1)
    }
    func bridge(_ hostPort: UInt16, _ guestPort: UInt32) {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        var yes: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in(); addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = hostPort.bigEndian; addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let ok = withUnsafePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) } }
        guard ok == 0, listen(fd, 64) == 0 else { die("bridge \(hostPort): bind failed errno=\(errno)") }
        note("bridge 127.0.0.1:\(hostPort) -> guest vsock \(guestPort)")
        Thread {
            while true {
                let s = accept(fd, nil, nil); if s < 0 { continue }
                DispatchQueue.main.async {
                    guard let dev = self.vm.socketDevices.first as? VZVirtioSocketDevice else { close(s); return }
                    dev.connect(toPort: guestPort) { r in
                        if case .success(let conn) = r { Pump.run(s, conn) } else { close(s) }
                    }
                }
            }
        }.start()
    }
}

signal(SIGPIPE, SIG_IGN)
let runner = Runner(c)
runner.vm.start { r in
    if case .failure(let e) = r { die("start: \(e.localizedDescription)") }
    note("started (cpus=\(cpus) mem=\(memMiB)MiB shares=\(shares.map { $0.0 }))")
    for (h, g) in bridges { runner.bridge(h, g) }
}
// SIGTERM/SIGINT: ask the guest to power off, force after 30 s.
for sig in [SIGTERM, SIGINT] {
    signal(sig, SIG_IGN)
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler {
        note("signal: requesting guest stop")
        if runner.vm.canRequestStop { try? runner.vm.requestStop() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { runner.vm.stop { _ in exit(3) } }
    }
    src.resume()
    _ = Unmanaged.passRetained(src)
}
if timeout > 0 {
    DispatchQueue.main.asyncAfter(deadline: .now() + timeout) {
        note("timeout after \(Int(timeout))s; force-stopping")
        runner.vm.stop { _ in exit(2) }
    }
}
dispatchMain()
