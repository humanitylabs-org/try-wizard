import Foundation
final class ColdBootstrapSerial {
    enum Outcome: Equatable { case waiting, delivered, inactive, failed(String) }
    static let command = "mount -t proc proc /proc 2>/dev/null; mount -t sysfs sysfs /sys 2>/dev/null; mount -o remount,rw /; mkdir -p /run/wizard-update; mount -t virtiofs -o ro wizard-update /run/wizard-update && exec /usr/bin/python3 /run/wizard-update/source/next/guest/cold-bootstrap.py init\n"
    let generation = UUID()
    let input = Pipe()
    private let reader: FileHandle
    private var deadline: TimeInterval
    private let timeout: TimeInterval
    private var tail = Data()
    private var active = true
    private(set) var delivered = false

    init(console: URL, now: TimeInterval, timeout: TimeInterval = 60) throws {
        reader = try FileHandle(forReadingFrom: console)
        deadline = now + timeout
        self.timeout = timeout
    }

    func poll(generation: UUID, now: TimeInterval) -> Outcome {
        guard generation == self.generation, active else { return .inactive }
        guard now < deadline else {
            cancelWaiting()
            return .failed("Cold bootstrap shell readiness timed out; no command sent")
        }
        do {
            // Incremental and bounded, including unusually noisy kernel boots.
            tail.append(try reader.read(upToCount: 65536) ?? Data())
            let text = String(decoding: tail, as: UTF8.self).replacingOccurrences(of: "\r", with: "")
            let prompt = "/bin/sh: 0: can't access tty; job control turned off\n# "
            guard text.hasSuffix(prompt) else {
                tail = Data(tail.suffix(1024))
                return .waiting
            }
            // Latch BEFORE writing: even a partial/failed write cannot retry init.
            delivered = true
            cancelWaiting()
            try input.fileHandleForWriting.write(contentsOf: Data(Self.command.utf8))
            return .delivered
        } catch {
            cancelWaiting()
            return .failed("Cold bootstrap serial I/O failed; command will not be retried")
        }
    }

    /// Count readiness from the VM's actual start. macOS can hold `VZVirtualMachine.start` behind a permission
    /// prompt for the shared folder; that wait is the owner's, not the guest's.
    func arm(now: TimeInterval) { deadline = now + timeout }

    func cancelWaiting() {
        active = false
        tail.removeAll()
        try? reader.close()
        // Keep the input writer open while PID1 is alive: EOF can panic Linux.
    }

    func closeAfterStop() {
        cancelWaiting()
        try? input.fileHandleForWriting.close()
        try? input.fileHandleForReading.close()
    }
}

