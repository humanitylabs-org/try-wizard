import Foundation
import Darwin

let root = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
let prompt = "/bin/sh: 0: can't access tty; job control turned off\n# "
var passed = 0
func check(_ ok: @autoclosure () -> Bool, _ name: String) {
    precondition(ok(), name); passed += 1
}
func fixture(_ name: String) throws -> (ColdBootstrapSerial, FileHandle) {
    let file = root.appendingPathComponent(name)
    try Data().write(to: file)
    let serial = try ColdBootstrapSerial(console: file, now: 100, timeout: 60)
    let fd = serial.input.fileHandleForReading.fileDescriptor
    precondition(fcntl(fd, F_SETFL, O_NONBLOCK) == 0)
    return (serial, try FileHandle(forWritingTo: file))
}
func bytes(_ serial: ColdBootstrapSerial) -> String {
    var buffer = [UInt8](repeating: 0, count: 4096)
    let count = read(serial.input.fileHandleForReading.fileDescriptor, &buffer, buffer.count)
    if count < 0 { precondition(errno == EAGAIN); return "" }
    precondition(count > 0, "writer was closed while PID1 alive")
    return String(decoding: buffer.prefix(count), as: UTF8.self)
}
func append(_ handle: FileHandle, _ text: String) throws {
    try handle.write(contentsOf: Data(text.utf8))
}
let (ready, output) = try fixture("ready")
check(bytes(ready).isEmpty, "no prequeued bytes")
check(ready.poll(generation: ready.generation, now: 101) == .waiting, "empty console")
try append(output, "kernel init=/bin/sh\n# ")
check(ready.poll(generation: ready.generation, now: 102) == .waiting, "bare prompt/kernel text not shell readiness")
for byte in prompt.utf8.dropLast() {
    try output.write(contentsOf: Data([byte]))
    precondition(ready.poll(generation: ready.generation, now: 103) == .waiting)
    precondition(bytes(ready).isEmpty)
}
passed += 1 // every split point kept input empty
try append(output, " ")
check(ready.poll(generation: ready.generation, now: 104) == .delivered, "split prompt admits")
check(bytes(ready) == ColdBootstrapSerial.command, "exact one command")
try append(output, prompt)
check(ready.poll(generation: ready.generation, now: 105) == .inactive && bytes(ready).isEmpty, "no duplicate exec")
ready.closeAfterStop(); try output.close()

let (timeout, timedOutput) = try fixture("timeout")
try append(timedOutput, prompt)
check(timeout.poll(generation: timeout.generation, now: 160) == .failed("Cold bootstrap shell readiness timed out; no command sent"), "deadline wins over late prompt")
check(!timeout.delivered && bytes(timeout).isEmpty, "timeout no bytes and writer retained")
check(timeout.poll(generation: timeout.generation, now: 161) == .inactive, "timeout terminal")
timeout.closeAfterStop(); try timedOutput.close()

let (old, oldOutput) = try fixture("old")
old.cancelWaiting()
try append(oldOutput, prompt)
check(old.poll(generation: old.generation, now: 101) == .inactive && bytes(old).isEmpty, "cancelled callback inert")
let (fresh, freshOutput) = try fixture("fresh")
try append(freshOutput, prompt.replacingOccurrences(of: "\n", with: "\r\n"))
check(fresh.poll(generation: old.generation, now: 101) == .inactive && bytes(fresh).isEmpty, "old generation cannot deliver to new boot")
check(fresh.poll(generation: fresh.generation, now: 101) == .delivered, "new generation and CRLF")
check(bytes(fresh) == ColdBootstrapSerial.command, "new pipe gets one command")
let oldFD = old.input.fileHandleForWriting.fileDescriptor
old.closeAfterStop(); old.closeAfterStop(); fresh.closeAfterStop()
check(fcntl(oldFD, F_GETFD) == -1 && errno == EBADF, "stop cleanup closes pipe idempotently")
try oldOutput.close(); try freshOutput.close()

let (noisy, noisyOutput) = try fixture("noisy")
try append(noisyOutput, String(repeating: "x", count: 140000) + "\n" + prompt)
check(noisy.poll(generation: noisy.generation, now: 101) == .waiting, "bounded read one")
check(noisy.poll(generation: noisy.generation, now: 102) == .waiting, "bounded read two")
check(noisy.poll(generation: noisy.generation, now: 103) == .delivered, "noisy boot eventually observes prompt")
check(bytes(noisy) == ColdBootstrapSerial.command, "bounded tail exact command")
noisy.closeAfterStop(); try noisyOutput.close()

let (failedWrite, failedOutput) = try fixture("failed-write")
try failedWrite.input.fileHandleForWriting.close()
try append(failedOutput, prompt)
check(failedWrite.poll(generation: failedWrite.generation, now: 101) == .failed("Cold bootstrap serial I/O failed; command will not be retried"), "write error fails closed")
check(failedWrite.poll(generation: failedWrite.generation, now: 102) == .inactive, "failed write never retries")
failedWrite.closeAfterStop(); try failedOutput.close()
print("COLD_SERIAL_REGRESSIONS_PASS checks=\(passed)")
