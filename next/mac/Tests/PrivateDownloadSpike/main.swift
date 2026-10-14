// Disposable route probe, not compiled into Wizard. No cookies or credentials are read.
import AppKit
import WebKit
import CryptoKit

final class Probe: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var download: WKDownload?
    let args = CommandLine.arguments
    var output: URL { URL(fileURLWithPath: args[3]) }
    var login: URL { URL(string: args[1])! }
    var release: URL { URL(string: args[2])! }
    var started = false
    var releaseAccessible = false
    var receipt: [[String: Any]] = []
    func record(_ value: [String: Any]) {
        receipt.append(value)
        let file = output.deletingLastPathComponent().appendingPathComponent("receipt.json")
        try? JSONSerialization.data(withJSONObject: receipt, options: [.prettyPrinted, .sortedKeys]).write(to: file, options: .atomic)
        print(value); fflush(stdout)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let config = WKWebViewConfiguration()
        // A fresh isolated visible login. Never inspect/copy another browser's cookies.
        config.websiteDataStore = .nonPersistent()
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 960, height: 760), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Wizard private download route probe — sign in at github.com"
        window.contentView = web; window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        web.load(URLRequest(url: login))
        let deadline = min(Double(ProcessInfo.processInfo.environment["WIZARD_SPIKE_AUTH_SECONDS"] ?? "45") ?? 45, 900)
        DispatchQueue.main.asyncAfter(deadline: .now() + deadline) { [self] in
            if !started { record(["result":"human-sign-in-required", "downloadStarted":false]); NSApp.terminate(nil) }
        }
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let u = action.request.url else { decisionHandler(.cancel); return }
        let allowed = login.host == "github.com"
            ? u.scheme == "https" && ["github.com", "release-assets.githubusercontent.com"].contains(u.host ?? "")
            : u.scheme == "http" && u.host == "127.0.0.1" && u.port == 48937
        guard allowed else { record(["blockedNavigationHost":u.host ?? ""]); decisionHandler(.cancel); return }
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if response.isForMainFrame, let r = response.response as? HTTPURLResponse, let u = r.url {
            record(["mainFrameHost":u.host ?? "", "path":u.path, "httpStatus":r.statusCode])
            if u == release { releaseAccessible = r.statusCode == 200 }
            let directAsset = u == URL(string: args[4])!
            let githubAsset = login.host == "github.com" && u.scheme == "https" && u.host == "release-assets.githubusercontent.com"
            if started, (directAsset || githubAsset), r.statusCode == 200, r.mimeType != "text/html" {
                decisionHandler(.download); return
            }
        }
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // No DOM, cookie, input, local-storage or token inspection.
        record(["navigationFinished":true, "pageTitle":webView.title ?? ""])
        if webView.url == release, releaseAccessible, !started {
            started = true
            webView.load(URLRequest(url: URL(string: args[4])!))
        }
        // Deliberately no screenshots or page-content capture during sign-in.
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).domain == "WebKitErrorDomain", (error as NSError).code == 102 { return }
        record(["navigationError":(error as NSError).code]); NSApp.terminate(nil)
    }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        self.download = download; download.delegate = self
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        self.download = download; download.delegate = self
    }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        record(["downloadHTTPStatus":code,"expectedLength":response.expectedContentLength])
        guard code == 200, response.mimeType != "text/html" else { completionHandler(nil); return }
        completionHandler(output)
    }
    func downloadDidFinish(_ download: WKDownload) {
        DispatchQueue.global().async { [self] in
            do {
                let file = try FileHandle(forReadingFrom: output); defer { try? file.close() }
                var hash = SHA256(); var bytes = 0
                while let data = try file.read(upToCount: 1 << 20), !data.isEmpty { hash.update(data: data); bytes += data.count }
                let digest = hash.finalize().map { String(format:"%02x",$0) }.joined()
                DispatchQueue.main.async { [self] in
                    record(["downloadFinished":true,"bytes":bytes,"sha256":digest]); NSApp.terminate(nil)
                }
            } catch { DispatchQueue.main.async { [self] in record(["fileError":true]); NSApp.terminate(nil) } }
        }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        record(["downloadError":(error as NSError).code]); NSApp.terminate(nil)
    }
}
let app = NSApplication.shared
let probe = Probe()
app.delegate = probe
app.run()
