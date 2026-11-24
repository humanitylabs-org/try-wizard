import XCTest
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
@testable import WizardShellToken

/// wizard-os#133: the Mac app's own owner calls (dictation) carry the shell token on a Wizard with the browser
/// boundary on, read the way the window's shell reads it (one page load of that Wizard's shell), never elsewhere.
final class StubProtocol: URLProtocol {
    static var answer: (URLRequest) -> (Int, String, URL?) = { _ in (404, "", nil) }
    static var seen: [URLRequest] = []
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.seen.append(request)
        let (status, body, url) = Self.answer(request)
        let response = HTTPURLResponse(url: url ?? request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: [:])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

/// The path as sent (URL.path drops a trailing slash).
func path(_ req: URLRequest) -> String { req.url.flatMap { URLComponents(url: $0, resolvingAgainstBaseURL: false)?.path } ?? "" }

final class ShellTokenTests: XCTestCase {
    let token = String(repeating: "ab", count: 32)
    let refusal = #"{"error":"shell_token_required","check":"browser_boundary"}"#
    var session: URLSession!

    override func setUp() {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubProtocol.self]
        session = URLSession(configuration: config)
        StubProtocol.seen = []
    }

    func page(_ value: String) -> String {
        "<!doctype html><html><head>\n  <meta name=\"wizard-shell-token\" content=\"\(value)\">\n  <script src=\"core/shell-token.js\"></script>"
    }

    /// A Wizard with the boundary on: refuses without the token, shows it in the shell page for a page load only.
    func boundaryOn(_ req: URLRequest) -> (Int, String, URL?) {
        if path(req) == "/wizard-os-home/" {
            let load = req.value(forHTTPHeaderField: "Sec-Fetch-Mode") == "navigate" && req.value(forHTTPHeaderField: "Sec-Fetch-Dest") == "document"
            return (200, page(load ? token : ""), nil)
        }
        return req.value(forHTTPHeaderField: WizardShellToken.header) == token ? (200, #"{"text":"hello"}"#, nil) : (401, refusal, nil)
    }

    func call(_ url: String) -> (Int?, String) {
        var req = URLRequest(url: URL(string: url)!); req.httpMethod = "POST"; req.httpBody = Data("RIFF".utf8)
        let done = expectation(description: "send")
        var out: (Int?, String) = (nil, "")
        WizardShellToken.send(req, session: session) { data, response, _ in
            out = ((response as? HTTPURLResponse)?.statusCode, String(decoding: data ?? Data(), as: UTF8.self)); done.fulfill()
        }
        wait(for: [done], timeout: 5)
        return out
    }

    func testParseTakesOnlyARealToken() {
        XCTAssertEqual(WizardShellToken.parse(Data(page(token).utf8)), token)
        XCTAssertNil(WizardShellToken.parse(Data(page("off").utf8)))
        XCTAssertNil(WizardShellToken.parse(Data(page("").utf8)))
        XCTAssertNil(WizardShellToken.parse(Data(page(token.uppercased()).utf8)))
        XCTAssertNil(WizardShellToken.parse(Data(page(String(token.dropLast())).utf8)))
        XCTAssertNil(WizardShellToken.parse(nil))
    }

    func testPageRequestIsATopLevelPageLoadOfTheSameOrigin() throws {
        let req = try XCTUnwrap(WizardShellToken.pageRequest(origin: URL(string: "https://box.tail.ts.net/wizard-os-home/?app=notes#x")!))
        XCTAssertEqual(req.url?.absoluteString, "https://box.tail.ts.net/wizard-os-home/")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Sec-Fetch-Mode"), "navigate")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Sec-Fetch-Dest"), "document")
        XCTAssertNil(WizardShellToken.pageRequest(origin: URL(string: "file:///tmp/x")!))
        XCTAssertEqual(WizardShellToken.originKey(URL(string: "http://127.0.0.1:48023/wizard/voice/transcribe")), "http://127.0.0.1:48023")
        XCTAssertEqual(WizardShellToken.originKey(URL(string: "HTTPS://Box.example/x")), "https://box.example:443")
    }

    func testRefusedIsOnlyTheBoundaryRefusal() {
        XCTAssertTrue(WizardShellToken.refused(status: 401, body: Data(refusal.utf8)))
        XCTAssertFalse(WizardShellToken.refused(status: 401, body: Data(#"{"error":"access_required"}"#.utf8)))
        XCTAssertFalse(WizardShellToken.refused(status: 403, body: Data(refusal.utf8)))
        XCTAssertFalse(WizardShellToken.refused(status: 401, body: nil))
    }

    func testBoundaryOnReadsTheTokenOnceAndRetries() {
        StubProtocol.answer = boundaryOn
        let first = call("http://127.0.0.1:48023/wizard/voice/transcribe")
        XCTAssertEqual(first.0, 200)
        XCTAssertEqual(StubProtocol.seen.map(path), ["/wizard/voice/transcribe", "/wizard-os-home/", "/wizard/voice/transcribe"])
        XCTAssertNil(StubProtocol.seen[0].value(forHTTPHeaderField: WizardShellToken.header))
        XCTAssertNil(StubProtocol.seen[1].value(forHTTPHeaderField: WizardShellToken.header))
        XCTAssertEqual(StubProtocol.seen[2].value(forHTTPHeaderField: WizardShellToken.header), token)
        // The next call carries it at once.
        StubProtocol.seen = []
        XCTAssertEqual(call("http://127.0.0.1:48023/wizard/voice/transcribe").0, 200)
        XCTAssertEqual(StubProtocol.seen.count, 1)
        XCTAssertEqual(StubProtocol.seen[0].value(forHTTPHeaderField: WizardShellToken.header), token)
    }

    func testBoundaryOffChangesNothing() {
        StubProtocol.answer = { req in path(req) == "/wizard-os-home/" ? (200, self.page("off"), nil) : (200, #"{"text":"hi"}"#, nil) }
        XCTAssertEqual(call("http://127.0.0.1:48100/wizard/voice/transcribe").0, 200)
        XCTAssertEqual(StubProtocol.seen.count, 1)
        XCTAssertNil(StubProtocol.seen[0].value(forHTTPHeaderField: WizardShellToken.header))
    }

    func testNoTokenInThePageHandsBackTheRefusal() {
        StubProtocol.answer = { req in path(req) == "/wizard-os-home/" ? (200, self.page("off"), nil) : (401, self.refusal, nil) }
        let out = call("http://127.0.0.1:48101/wizard/voice/transcribe")
        XCTAssertEqual(out.0, 401)
        XCTAssertEqual(StubProtocol.seen.count, 2)
    }

    func testATokenFromAnotherOriginIsNeverUsed() {
        // The shell page answered from somewhere else (a redirect): its token is not this Wizard's.
        StubProtocol.answer = { req in
            path(req) == "/wizard-os-home/" ? (200, self.page(self.token), URL(string: "https://elsewhere.example/wizard-os-home/")) : (401, self.refusal, nil)
        }
        XCTAssertEqual(call("http://127.0.0.1:48102/wizard/voice/transcribe").0, 401)
        XCTAssertEqual(StubProtocol.seen.count, 2)
        XCTAssertNil(WizardShellToken.cached("http://127.0.0.1:48102"))
    }

    func testOtherAnswersAreNotRetried() {
        StubProtocol.answer = { _ in (401, #"{"error":"access_required"}"#, nil) }
        XCTAssertEqual(call("http://127.0.0.1:48103/wizard/voice/transcribe").0, 401)
        XCTAssertEqual(StubProtocol.seen.count, 1)
    }

    func testTokensStayPerOrigin() {
        StubProtocol.answer = boundaryOn
        XCTAssertEqual(call("http://127.0.0.1:48104/wizard/voice/transcribe").0, 200)
        XCTAssertEqual(WizardShellToken.cached("http://127.0.0.1:48104"), token)
        XCTAssertNil(WizardShellToken.cached("http://127.0.0.1:48105"))
    }
}
