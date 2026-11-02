import Foundation
import Darwin

// Links the unmodified production UpdateContract.swift. Only transport and paths
// are isolated. This proves fail-closed admission, NOT a completed legacy upgrade.
enum WizardShared {
    static let appBundleID = "org.humanitylabs.wizard.mvp"
    static let hostBundleID = "org.humanitylabs.wizard.mvp.host"
    static let supportDir = URL(fileURLWithPath: CommandLine.arguments[1])
    static var statusFile: URL { supportDir.appendingPathComponent("host-status.json") }
    static let localUXHealthURL = URL(string: "http://127.0.0.1:47993/wizard/health")!
}

final class AdmissionTransport: URLProtocol {
    static var status = 404
    static var body = Data("{}".utf8)
    static var paths: [String] = []
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        precondition(request.url?.host == "127.0.0.1")
        Self.paths.append(request.url!.path)
        let response = HTTPURLResponse(url: request.url!, statusCode: Self.status, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Self.body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

func awaitReason(_ operation: (@escaping (String?) -> Void) -> Void) -> String? {
    var done = false
    var result: String?
    operation { reason in result = reason; done = true }
    let end = Date().addingTimeInterval(5)
    while !done && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.01)) }
    precondition(done, "bounded transport completion")
    return result
}

precondition(!FileManager.default.fileExists(atPath: WizardShared.supportDir.path), "fresh test directory only")
try FileManager.default.createDirectory(at: WizardShared.supportDir, withIntermediateDirectories: true)
precondition(URLProtocol.registerClass(AdmissionTransport.self))
let cases: [(Int, String, Bool, String)] = [
    (404, "{}", false, "LEGACY_MISSING_MAINTENANCE_REFUSED"),
    (409, "{\"ok\":false,\"error\":\"agent_busy\"}", false, "ACTIVE_AGENT_REFUSED"),
    (503, "{}", false, "UNKNOWN_RUNTIME_REFUSED"),
    (201, "{}", false, "MALFORMED_SUCCESS_REFUSED"),
    (200, "{\"ok\":true}", false, "WRONG_STATUS_REFUSED"),
    (201, "{\"ok\":true}", true, "MODERN_LEASE_ACCEPTED")
]
for (status, body, accepted, label) in cases {
    try? FileManager.default.removeItem(at: WizardUpdate.maintenanceJournal)
    AdmissionTransport.status = status
    AdmissionTransport.body = Data(body.utf8)
    let reason = awaitReason { WizardUpdate.maintenance(UUID().uuidString, $0) }
    precondition((reason == nil) == accepted, label)
    precondition(AdmissionTransport.paths.last == "/wizard/v1/maintenance")
    precondition(!FileManager.default.fileExists(atPath: WizardUpdate.journal.path), "a lease probe cannot invent an install transaction")
    print(label)
}
try WizardUpdate.write(["pid": getpid(), "state": "running"], WizardShared.statusFile)
AdmissionTransport.status = 200
for (body, accepted, label) in [
    ("{\"upstream_reachable\":true,\"queue\":{\"liveness_available\":true,\"active\":1,\"queued\":0}}", false, "ACTIVE_QUEUE_REFUSED"),
    ("{\"upstream_reachable\":true,\"queue\":{\"liveness_available\":true,\"active\":0,\"queued\":1}}", false, "QUEUED_WORK_REFUSED"),
    ("{\"upstream_reachable\":true,\"queue\":{\"active\":0,\"queued\":0}}", false, "UNKNOWN_LIVENESS_REFUSED"),
    ("{\"upstream_reachable\":true,\"queue\":{\"liveness_available\":true,\"active\":0,\"queued\":0}}", true, "KNOWN_IDLE_ACCEPTED")
] {
    AdmissionTransport.body = Data(body.utf8)
    precondition((awaitReason(WizardUpdate.idle) == nil) == accepted, label)
    print(label)
}
print("TEN_PRODUCTION_ADMISSION_CHECKS_PASS_NOT_LEGACY_UPGRADE_ACCEPTANCE")
