// Compile with the real App/UpdateArtifact.swift, once with WIZARD_UPDATE_QA
// and once without it. These tests do not load AppKit, Sparkle, or user defaults.
import Foundation
import CryptoKit
import Network
import Darwin

enum WizardUpdate {
    static var dir: URL {
        URL(fileURLWithPath: ProcessInfo.processInfo.environment["WIZARD_ARTIFACT_TEST_ROOT"]!).appendingPathComponent("updates")
    }
    static func error(_ text: String) -> NSError {
        NSError(domain: "WizardUpdate", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }
}
func check(_ condition: @autoclosure () -> Bool, _ name: String) {
    if !condition() { fatalError(name) }
}
func mustRefuse(_ name: String, _ body: () throws -> Void) {
    do { try body(); fatalError("Accepted: \(name)") }
    catch { check((error as NSError).domain == "WizardUpdate", name) }
}
try UpdateArtifact.requireCapacity(300, bytes: 100)
mustRefuse("unknown capacity") { try UpdateArtifact.requireCapacity(nil, bytes: 100) }
mustRefuse("insufficient capacity") { try UpdateArtifact.requireCapacity(299, bytes: 100) }
mustRefuse("zero length") { try UpdateArtifact.requireCapacity(300, bytes: 0) }
mustRefuse("capacity multiplication overflow") { try UpdateArtifact.requireCapacity(.max, bytes: .max) }
check(UpdateArtifact.allowed(URL(string: "https://example.invalid/archive.zip")!), "HTTPS allowed")
check(!UpdateArtifact.allowed(URL(string: "http://example.invalid/archive.zip")!), "public HTTP refused")
check(!UpdateArtifact.allowed(URL(string: "file:///archive.zip")!), "file refused")
#if WIZARD_UPDATE_QA
check(UpdateArtifact.allowed(URL(string: "http://127.0.0.1/archive.zip")!), "QA loopback allowed")
#else
check(!UpdateArtifact.allowed(URL(string: "http://127.0.0.1/archive.zip")!), "production loopback refused")
#endif
let manager = FileManager.default
try manager.createDirectory(at: WizardUpdate.dir, withIntermediateDirectories: true)
let stale = WizardUpdate.dir.appendingPathComponent("download-abandoned")
let preserved = WizardUpdate.dir.appendingPathComponent("transaction.json")
try manager.createDirectory(at: stale, withIntermediateDirectories: true)
try Data("preserve".utf8).write(to: preserved)
try UpdateArtifact.sweepStaleDownloads()
check(!manager.fileExists(atPath: stale.path), "abandoned stage removed")
check(manager.fileExists(atPath: preserved.path), "non-download state preserved")
let held = WizardUpdate.dir.appendingPathComponent("download-held")
try manager.createDirectory(at: held, withIntermediateDirectories: true)
let heldFD = open(held.appendingPathComponent("lock").path, O_CREAT | O_RDWR, 0o600)
check(heldFD >= 0 && flock(heldFD, LOCK_EX | LOCK_NB) == 0, "fixture lock")
try UpdateArtifact.sweepStaleDownloads()
check(manager.fileExists(atPath: held.path), "live stage preserved")
flock(heldFD, LOCK_UN); close(heldFD)
try UpdateArtifact.sweepStaleDownloads()
check(!manager.fileExists(atPath: held.path), "unlocked stage removed")
let file = WizardUpdate.dir.appendingPathComponent("fixture.zip")
let bytes = Data("verified archive fixture".utf8)
try bytes.write(to: file)
let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
try UpdateArtifact.verify(file, hash: digest, bytes: UInt64(bytes.count))
let signingKey = Curve25519.Signing.PrivateKey()
let signature = try signingKey.signature(for: bytes).base64EncodedString()
let publicKey = signingKey.publicKey.rawRepresentation.base64EncodedString()
try UpdateArtifact.verifySignature(file, signature: signature, publicKey: publicKey)
mustRefuse("bad Ed25519") { try UpdateArtifact.verifySignature(file, signature: Data(repeating: 0, count: 64).base64EncodedString(), publicKey: publicKey) }
mustRefuse("wrong Ed25519 key") { try UpdateArtifact.verifySignature(file, signature: signature, publicKey: Curve25519.Signing.PrivateKey().publicKey.rawRepresentation.base64EncodedString()) }
mustRefuse("wrong size") { try UpdateArtifact.verify(file, hash: digest, bytes: UInt64(bytes.count + 1)) }
mustRefuse("wrong SHA") { try UpdateArtifact.verify(file, hash: String(repeating: "0", count: 64), bytes: UInt64(bytes.count)) }
print("UpdateArtifact capacity, scheme, stale-sweep, size and digest contracts: PASS")
#if WIZARD_UPDATE_QA
// Repeated close/reconnect must not exhaust a lifetime connection counter.
// This runs the actual private relay and downloader, not a transport mock.
let fixtureQueue = DispatchQueue(label: "artifact-source-fixture")
let origin = try NWListener(using: .tcp, on: .any)
let artifact = UpdateArtifact()
func readRelay(_ url: URL, remaining: Int) {
    var request = URLRequest(url: url); request.cachePolicy = .reloadIgnoringLocalCacheData
    URLSession.shared.dataTask(with: request) { body, response, error in
        check(error == nil && (response as? HTTPURLResponse)?.statusCode == 200 && body == bytes, "relay request \(remaining): \(String(describing: error))")
        if remaining > 1 { readRelay(url, remaining: remaining - 1) }
        else {
            artifact.cancel(); origin.cancel()
            print("UpdateArtifact relay accepts 12 consecutive connections and prunes closed slots: PASS")
            exit(0)
        }
    }.resume()
}
origin.newConnectionHandler = { connection in
    connection.start(queue: fixtureQueue)
    connection.receive(minimumIncompleteLength: 1, maximumLength: 16384) { _, _, _, _ in
        var response = Data("HTTP/1.1 200 OK\r\nContent-Length: \(bytes.count)\r\nConnection: close\r\n\r\n".utf8)
        response.append(bytes)
        connection.send(content: response, completion: .contentProcessed { _ in connection.cancel() })
    }
}
origin.stateUpdateHandler = { state in
    guard case .ready = state, let port = origin.port else { return }
    do {
        try artifact.fetch(URL(string: "http://127.0.0.1:\(port.rawValue)/fixture.zip")!, hash: digest,
                           bytes: UInt64(bytes.count), progress: { _, _ in }) { result in
            switch result {
            case .success(let url): readRelay(url, remaining: 12)
            case .failure(let error): fatalError("private relay fixture failed: \(error)")
            }
        }
    } catch { fatalError("private relay fixture start failed: \(error)") }
}
origin.start(queue: fixtureQueue)
DispatchQueue.global().asyncAfter(deadline: .now() + 45) { fputs("Relay fixture timed out\n", stderr); exit(2) }
dispatchMain()
#endif
